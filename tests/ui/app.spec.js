import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

async function signedIn(page, failure = false, seed = true) {
  const token = ['eyJhbGciOiJSUzI1NiJ9', Buffer.from(JSON.stringify({ sub: 'owner', exp: 4102444800, iat: 1700000000 })).toString('base64url'), 'signature'].join('.');
  if (seed) await page.addInitScript(({ token }) => {
    if (localStorage.getItem('sidecar-test-seeded')) return;
    localStorage.setItem('sidecar-test-seeded', 'true');
    localStorage.setItem('firebase:authUser:sidecar-test:[DEFAULT]', JSON.stringify({
      uid: 'owner', email: 'owner@example.com', emailVerified: true, isAnonymous: false,
      providerData: [], apiKey: 'sidecar-test', appName: '[DEFAULT]',
      stsTokenManager: { accessToken: token, refreshToken: 'test-refresh', expirationTime: 4102444800000 },
    }));
  }, { token });
  await page.route('**/config.json', route => route.fulfill({ json: {
    relayUrl: 'https://relay.test', firebase: { apiKey: 'sidecar-test', projectId: 'sidecarpic', authDomain: 'sidecarpic.firebaseapp.com', appId: 'test' },
  } }));
  await page.route('https://identitytoolkit.googleapis.com/**', route => route.fulfill({ json: {
    users: [{ localId: 'owner', email: 'owner@example.com', emailVerified: true, providerUserInfo: [] }],
  } }));
  await page.route('https://relay.test/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204,
      headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'authorization', 'Access-Control-Allow-Methods': '*' } });
    expect(route.request().headers().authorization).toContain('Bearer ');
    if (path === '/api/status') return route.fulfill({ json: { connected: true } });
    if (path === '/api/captures') return route.fulfill({ status: 202, json: { id: 'test-capture' } });
    if (path.endsWith('/image')) return route.fulfill({ contentType: 'image/jpeg', body: readFileSync('public/icon.png') });
    return route.fulfill({ json: failure ? { status: 'failed', error: 'permission' } : { status: 'ready' } });
  });
}

for (const width of [320, 390, 1440]) {
  test(`phone interface fits ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/config.json', route => route.fulfill({ json: { firebase: {} } }));
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'A little closer.' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Capture screen' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Share screenshot' })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.getByRole('button', { name: 'Account', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('button', { name: 'Close account' }).click();
    await page.screenshot({ path: `artifacts/sidecar-${width}.png`, fullPage: true });
  });
}

test('capture, preview, download, discard and sign out', async ({ page }) => {
  await signedIn(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Capture screen' })).toBeEnabled();
  await page.getByRole('button', { name: 'Capture screen' }).click();
  await expect(page.getByRole('button', { name: 'Share screenshot' })).toBeEnabled();
  await expect(page.locator('#screenshot')).toBeVisible();
  expect(await page.locator('#screenshot').evaluate(img => img.naturalWidth)).toBeGreaterThan(0);
  await page.screenshot({ path: 'artifacts/sidecar-captured.png', fullPage: true });
  await page.getByRole('button', { name: 'Open screenshot' }).click();
  await expect(page.locator('#image-dialog')).toBeVisible();
  await page.getByRole('button', { name: 'Close screenshot' }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download screenshot' }).click();
  expect((await download).suggestedFilename()).toMatch(/^sidecar-.*\.jpg$/);
  await page.getByRole('button', { name: 'Discard screenshot' }).click();
  await expect(page.locator('#screenshot')).not.toBeVisible();
  await page.getByRole('button', { name: 'Account', exact: true }).click();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Capture screen' })).toBeDisabled();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Sign in with Google' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Capture screen' })).toBeDisabled();
});

test('saved sign-in survives reload and a new browser context', async ({ page, browser }) => {
  await signedIn(page);
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Capture screen' })).toBeEnabled();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Capture screen' })).toBeEnabled();
  await expect(page.locator('#signin-section')).toBeHidden();
  const saved = await page.context().storageState();
  const context = await browser.newContext({ storageState: saved });
  try {
    const reopened = await context.newPage();
    await signedIn(reopened, false, false);
    await reopened.goto('/');
    await expect(reopened.getByRole('button', { name: 'Capture screen' })).toBeEnabled();
    await expect(reopened.locator('#signin-section')).toBeHidden();
  } finally { await context.close(); }
});

test('permission failure restores capture control', async ({ page }) => {
  await signedIn(page, true);
  await page.goto('/');
  await page.getByRole('button', { name: 'Capture screen' }).click();
  await expect(page.getByRole('status')).toContainText('Ubuntu needs screen-capture permission');
  await expect(page.getByRole('button', { name: 'Capture screen' })).toBeEnabled();
});

test('phone screenshot expires after two minutes', async ({ page }) => {
  await signedIn(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Capture screen' }).click();
  await expect(page.getByRole('button', { name: 'Share screenshot' })).toBeEnabled();
  await page.clock.install();
  await page.clock.fastForward(121000);
  await expect(page.getByRole('button', { name: 'Share screenshot' })).toBeDisabled();
  await expect(page.locator('#screenshot')).not.toBeVisible();
});
