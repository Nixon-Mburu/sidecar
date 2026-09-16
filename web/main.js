import './style.css';
import { createIcons, UserRound, ShieldCheck, Laptop, ScanLine, ArrowUpRight, Monitor, Plus, Clock3, Trash2, Share2, Download, LogIn, X } from 'lucide';
import { initializeApp } from 'firebase/app';
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged, setPersistence, browserLocalPersistence } from 'firebase/auth';

createIcons({ icons: { UserRound, ShieldCheck, Laptop, ScanLine, ArrowUpRight, Monitor, Plus, Clock3, Trash2, Share2, Download, LogIn, X } });
const $ = (id) => document.getElementById(id);
let auth, user, config, connected = false, busy = false, imageUrl, imageFile, expiresAt = 0, generation = 0;
let jobId, sharing = false;
const notice = (message = '') => { $('notice').textContent = message; };

function controls() {
  $('capture-button').disabled = !user || !connected || busy;
  $('capture-button').querySelector('span').textContent = busy ? 'Capturing...' : 'Capture screen';
  $('capture-progress').hidden = !busy;
  for (const id of ['share-button', 'preview-share-button']) $(id).disabled = !imageFile || busy || sharing;
  for (const id of ['download-button', 'discard-button']) $(id).disabled = !imageFile || busy;
}

function connection(value, text) {
  connected = value;
  $('connection-text').textContent = text || (value ? 'Connected to your workspace' : 'Waiting for your laptop');
  $('connection-badge').classList.toggle('online', value);
  $('connection-badge').querySelector('b').textContent = value ? 'Online' : 'Offline';
  controls();
}

function clearImage() {
  if (imageUrl) URL.revokeObjectURL(imageUrl);
  imageUrl = undefined; imageFile = undefined; expiresAt = 0;
  $('screenshot').removeAttribute('src'); $('full-image').removeAttribute('src');
  $('image-button').hidden = true; $('empty-state').hidden = false;
  $('capture-time').textContent = 'No captures yet';
  $('expiry-text').textContent = 'Nothing stored. Just the moment.';
  $('image-dialog').close();
  controls();
}

async function api(path, options = {}) {
  if (!user) throw new Error('Sign in to continue.');
  const token = await user.getIdToken();
  const response = await fetch(config.relayUrl + path, {
    ...options, cache: 'no-store', signal: AbortSignal.timeout(35000),
    headers: { ...options.headers, Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || 'Could not reach your laptop. Please try again.');
  }
  return response;
}

let checking = false;
async function checkStatus() {
  if (!user || checking || document.hidden) return;
  checking = true;
  const version = generation;
  try {
    const result = await (await api('/api/status')).json();
    if (version === generation) connection(result.connected);
  } catch (error) {
    if (version === generation) { connection(false, 'Relay unavailable'); notice(error.message); }
  } finally { checking = false; }
}

$('capture-button').addEventListener('click', async () => {
  if (busy) return;
  busy = true; notice(); clearImage(); controls();
  const version = generation;
  let localJob;
  try {
    const result = await (await api('/api/captures', { method: 'POST' })).json();
    localJob = result.id;
    if (version !== generation) return;
    jobId = localJob;
    const deadline = Date.now() + 95000;
    while (version === generation && Date.now() < deadline) {
      const result = await (await api(`/api/captures/${localJob}`)).json();
      if (version !== generation) return;
      if (result.status === 'failed') throw new Error(result.error === 'permission'
        ? 'Ubuntu needs screen-capture permission. Check your laptop and try again.'
        : 'Your laptop could not capture the screen. Check the Sidecar agent.');
      if (result.status === 'ready') {
        const blob = await (await api(`/api/captures/${localJob}/image`)).blob();
        if (version !== generation) return;
        imageFile = new File([blob], `sidecar-${Date.now()}.jpg`, { type: 'image/jpeg' });
        imageUrl = URL.createObjectURL(imageFile);
        $('screenshot').src = imageUrl; $('full-image').src = imageUrl;
        $('image-button').hidden = false; $('empty-state').hidden = true;
        $('capture-time').textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        expiresAt = Date.now() + 120000;
        jobId = undefined;
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    if (version === generation) throw new Error('Capture timed out. Check your laptop and try again.');
  } catch (error) {
    if (version === generation) notice(error.message);
  } finally {
    if (version === generation) {
      if (jobId) api(`/api/captures/${jobId}`, { method: 'DELETE' }).catch(() => {});
      jobId = undefined; busy = false; controls();
    }
  }
});

function download() {
  if (!imageFile) return;
  const link = document.createElement('a'); link.href = imageUrl; link.download = imageFile.name; link.click();
}
$('download-button').addEventListener('click', download);
async function shareScreenshot() {
  if (!imageFile || sharing) return;
  notice();
  sharing = true; controls();
  try {
    if (typeof navigator.share === 'function' && navigator.canShare?.({ files: [imageFile] })) {
      await navigator.share({ files: [imageFile] });
    } else if (typeof ClipboardItem === 'function' && typeof navigator.clipboard?.write === 'function') {
      await navigator.clipboard.write([new ClipboardItem({ [imageFile.type]: imageFile })]);
      notice('Image copied to the clipboard. Paste it into ChatGPT.');
    } else notice('Image sharing is unavailable in this browser. Try Sidecar in your phone browser, or use Download.');
  } catch (error) {
    if (error.name !== 'AbortError') notice('Sharing failed. You can download the screenshot instead.');
  } finally { sharing = false; controls(); }
}
$('share-button').addEventListener('click', shareScreenshot);
$('preview-share-button').addEventListener('click', shareScreenshot);
$('discard-button').addEventListener('click', () => { clearImage(); notice(); });
$('image-button').addEventListener('click', () => $('image-dialog').showModal());
$('close-image').addEventListener('click', () => $('image-dialog').close());
$('account-button').addEventListener('click', () => $('account-dialog').showModal());
$('close-account').addEventListener('click', () => $('account-dialog').close());
$('signout-button').addEventListener('click', async () => {
  try {
    if (jobId) await api(`/api/captures/${jobId}`, { method: 'DELETE' }).catch(() => {});
    if (auth) await signOut(auth);
    $('account-dialog').close();
  } catch { notice('Could not sign out. Please try again.'); }
});
$('signin-button').addEventListener('click', async () => {
  if (!auth) return;
  $('signin-button').disabled = true; notice();
  try { await signInWithPopup(auth, new GoogleAuthProvider()); }
  catch (error) { notice(error.code === 'auth/popup-blocked' ? 'Allow the sign-in popup and try again.' : 'Sign-in did not complete. Please try again.'); }
  finally { $('signin-button').disabled = false; }
});

setInterval(() => {
  if (!expiresAt) return;
  const seconds = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
  if (!seconds) { clearImage(); notice('Screenshot expired. Ready for another.'); }
  else $('expiry-text').textContent = `Clears in ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}, 1000);
setInterval(checkStatus, 10000);
document.addEventListener('visibilitychange', () => {
  if (expiresAt && Date.now() >= expiresAt) clearImage();
  if (!document.hidden) checkStatus();
});

async function init() {
  try {
    config = await (await fetch('/config.json', { cache: 'no-store' })).json();
    if (!config.firebase?.apiKey) throw new Error('Sign-in is being connected.');
    const relayReady = /^https:\/\//.test(config.relayUrl || '');
    config.relayUrl = (config.relayUrl || '').replace(/\/$/, '');
    auth = getAuth(initializeApp(config.firebase));
    await setPersistence(auth, browserLocalPersistence);
    onAuthStateChanged(auth, (nextUser) => {
      generation++; user = nextUser; busy = false; jobId = undefined; clearImage(); notice();
      $('signin-section').hidden = !!user;
      $('signin-button').disabled = false;
      $('account-email').textContent = user?.email || 'Not signed in';
      $('account-uid').textContent = user ? `Account ID: ${user.uid}` : '';
      $('signout-button').hidden = !user;
      connection(false, user ? 'Connecting to your laptop...' : 'Sign in to connect');
      if (user && relayReady) checkStatus();
      else if (user) { connection(false, 'Relay setup pending'); notice('Your account is ready. The laptop relay is not connected yet.'); }
    });
    if (!relayReady) checkStatus = async () => {};
  } catch (error) {
    $('signin-section').hidden = false;
    $('signin-button').disabled = true;
    $('signin-description').textContent = 'Your workspace is being connected.';
    connection(false, 'Connection unavailable');
    notice(error.code === 'auth/web-storage-unsupported'
      ? 'Allow site storage for Sidecar to remember your sign-in.'
      : error.message === 'Sign-in is being connected.' ? error.message : 'Sidecar could not restore your session. Please reload.');
  }
}
init();
