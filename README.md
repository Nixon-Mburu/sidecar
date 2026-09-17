# Sidecar

Phone-triggered Ubuntu screen capture. Flask runs on Render, the phone app lives on Firebase Hosting, and an outbound-only agent runs in your Ubuntu desktop session. No LLM API or browser extension; only requested frames leave the laptop.

## Local development

Use Python 3.12+ and Node 22.12+.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r agent/requirements.txt pytest
npm ci
npm run dev
```

The phone interface opens at http://localhost:5173. Configure `public/config.json` with the Firebase web app's public configuration and your HTTPS Render relay URL. No agent secret belongs in that file. Unconfigured installs show a disconnected state; they do not simulate a laptop.

## Firebase: sidecarpic.web.app

1. Register a Firebase web app in project `sidecarpic` and put its SDK config into `public/config.json`.
2. Enable Google in Authentication > Sign-in method. Add `sidecarpic.web.app`, `sidecarpic.firebaseapp.com`, and `localhost` to Authentication > Settings > Authorized domains as needed.
3. Run `npm run build`, then `npx firebase-tools deploy --only hosting --project sidecarpic`.
4. Sign in on the deployed site. Your account dialog shows your Firebase UID; set that as Render's `OWNER_UID`.

## Render relay

Create a Blueprint from https://github.com/Nixon-Mburu/sidecar using `render.yaml`. Set `OWNER_UID` to your Firebase Authentication UID. Render generates `AGENT_SECRET`; retrieve it privately for the laptop agent. Copy the resulting HTTPS URL into `public/config.json` as `relayUrl`, rebuild and redeploy Hosting.

The Blueprint uses one Gunicorn worker with eight threads. **Keep exactly one process and one instance:** pending jobs and images live in process memory. Scaling requires a shared expiring store and is not supported by this release. Restarts discard pending captures. The free Render plan may cold-start; use a paid instance if you need consistently low latency. Agent long polling generates continuous requests while your laptop is online.

Environment variables are listed in `.env.example`; Render supplies them directly. For a local relay, export them in your shell, include `http://localhost:5173` in `ALLOWED_ORIGINS`, and run `.venv/bin/gunicorn relay.app:app --workers 1 --threads 8 --bind 127.0.0.1:8000`.

## Ubuntu agent

```sh
.venv/bin/python -m agent.install
.venv/bin/python -m agent.main --check
.venv/bin/python -m agent.main
```

The installer prompts for your relay URL and secret, writes a mode-600 config to `~/.config/sidecar/agent.json`, and adds a desktop autostart entry. It starts automatically at future desktop logins, with no terminal window. Keep this checkout and its virtual environment in place. Run only one agent per laptop. To uninstall startup, remove `~/.config/autostart/sidecar.desktop` and `~/.config/sidecar`.

Wayland uses a permission-approved `org.freedesktop.portal.ScreenCast` session with PipeWire. On the first capture after starting the agent, select your monitor in Ubuntu's screen-sharing prompt. Later captures reuse that session and do not call the screenshot API, avoiding its per-screenshot flash and shutter sound. Manual screenshots are unaffected. Ubuntu's sharing indicator remains visible; this is not undetectable capture.

The local stream stays active while the agent runs, with a bounded frame queue in RAM. Only a requested frame is encoded and uploaded; no video is recorded or streamed to Render. Stopping sharing revokes access; the next attempt fails instead of returning cached pixels. A subsequent request can ask for permission again. The agent never falls back to the flashing screenshot portal. On X11, MSS still captures into memory.

The Wayland helper uses Ubuntu's `/usr/bin/python3` with `python3-gi`, `gir1.2-gstreamer-1.0`, `gir1.2-gst-plugins-base-1.0`, `gstreamer1.0-pipewire`, and `gstreamer1.0-plugins-base`. These are available on the development laptop. The agent needs an active, unlocked graphical session. No browser extension or page interaction is involved.

## Privacy and boundaries

- Firebase ID tokens are verified against the project and restricted to one owner UID.
- The device uses an independent secret over HTTPS. Rotate `AGENT_SECRET` on Render and in the agent config to revoke a device.
- Pending requests expire after 90 seconds. Relay images expire after 120 seconds, with a five-second cleanup interval, or are removed immediately after retrieval. The phone clears its image after two minutes, including when resuming from the background.
- Image responses use `Cache-Control: no-store`; images are never put into localStorage, IndexedDB, Firebase Storage, or a service-worker cache.
- The relay can read image bytes while forwarding them; this is HTTPS transport encryption, not end-to-end encryption. Memory release is not a promise of cryptographic RAM erasure.
- Downloading, copying, or sharing creates copies outside Sidecar's expiry policy. The clipboard is controlled by your OS and is not cleared by Sidecar's image timer.
- The main **Copy & open ChatGPT** action converts the image to PNG in memory, writes it to the clipboard, and opens ChatGPT in the same tab. Paste into the composer to attach it; no download or gallery step is required. The preview share icon still opens the native app chooser. The OS decides which apps appear there; a webpage cannot force ChatGPT into the list or automatically attach a clipboard image in another app.
- This release uses a web app manifest but deliberately has no offline screenshot cache or service worker.

## Verification

```sh
.venv/bin/python -m pytest tests/test_relay.py tests/test_capture.py
npm run build
npm run test:ui
```

UI tests use `/usr/bin/google-chrome`; change the Playwright executable path for another environment. Relay tests cover owner isolation, device authentication, capture delivery, expiry, CORS, invalid uploads, and cancellation. Live OS capture and native phone sharing also need a real-device check.
