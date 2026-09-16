


Sidecar
Overview
Sidecar is a lightweight cross-device screen-capture tool for
personal coding practice. It connects an Ubuntu laptop to a mobile web
interface, allowing the user to remotely request a screenshot, receive
it on their phone, and manually share it with the ChatGPT mobile app for
analysis.

Sidecar itself does not require an LLM API.

Core Flow
Phone Web App
     │
 [CAPTURE]
     ▼
Authenticated connection / relay
     │
     ▼
Ubuntu Sidecar Agent
     │
     ├── captures one screenshot
     ├── compresses it in memory
     └── sends it back
     ▼
Phone Web App
     │
 [SHARE]
     ▼
ChatGPT App
Ubuntu Agent
A small background process runs on Ubuntu and remains idle until an
authenticated capture request arrives from the paired phone.

When triggered, it: 1. Uses normal OS-supported screen-capture
mechanisms. 2. Captures one screenshot. 3. Encodes it in memory as
JPEG/WebP. 4. Sends it securely to the phone. 5. Discards its temporary
copy.

It does not need to continuously capture the screen, perform OCR, call
an AI model, or display a foreground window. It respects Ubuntu's normal
permissions and security controls. Development can begin as a Python
process and later be packaged as a lightweight .deb.

Phone Interface
The phone uses a mobile-responsive webpage rather than a native app.

┌─────────────────────────┐
│        SIDECAR          │
│ Laptop connected ●      │
│                         │
│      [ CAPTURE ]        │
│                         │
│ [ latest screenshot ]   │
│                         │
│       [ SHARE ]         │
└─────────────────────────┘
It can later become an installable Progressive Web App (PWA).

Networking
V0 uses the same Wi-Fi network:

Phone ─── local network ─── Ubuntu
A later version introduces an authenticated Internet relay:

Phone ─── Internet relay ─── Ubuntu
Each installation should have a unique device identity and secret so
only a paired phone can issue capture requests.

Privacy
Screenshots are ephemeral by default:

Capture → RAM → Compress → Encrypted transport → Phone → Expire
Permanent screenshot storage should be avoided because screens may
contain passwords, messages, source code, API keys, or other sensitive
information.

Development Roadmap
V0: Phone button → HTTP request → Ubuntu screenshot → image appears
on phone.

V1: Add Share so the screenshot can be manually sent to ChatGPT.

V2: Add secure phone/laptop pairing and authentication.

V3: Add an Internet relay so both devices do not need the same
Wi-Fi.

V4: Package the Ubuntu agent as a .deb and the phone interface as
a PWA.

Stack
Laptop agent: Python

Backend: FastAPI

Capture: Ubuntu-supported screen-capture APIs

Images: JPEG/WebP

Phone: HTML/CSS/JavaScript

V0 transport: HTTP over LAN

Later transport: HTTPS/WebSocket relay

Phone packaging: PWA

Ubuntu packaging: .deb

Final Experience
Coding problem on laptop
        ↓
Press CAPTURE on phone
        ↓
Ubuntu captures current screen
        ↓
Screenshot appears on phone
        ↓
Press SHARE
        ↓
Choose ChatGPT
        ↓
Ask ChatGPT about screenshot
Sidecar stays deliberately small: capture → transport → display →
share. ChatGPT provides the intelligence rather than Sidecar
duplicating it.