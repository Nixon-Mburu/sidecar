"""Install the agent's login startup entry and private configuration."""

import getpass
import json
import os
from pathlib import Path
import shlex
import sys
from urllib.parse import urlparse


def main():
    root = Path(__file__).resolve().parent.parent
    url = input('Render relay URL (https://...): ').strip().rstrip('/')
    if urlparse(url).scheme != 'https':
        raise SystemExit('An HTTPS relay URL is required.')
    secret = getpass.getpass('Render AGENT_SECRET: ')
    if len(secret) < 32:
        raise SystemExit('The secret must have at least 32 characters.')
    directory = Path.home() / '.config/sidecar'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = directory / 'agent.json'
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'relay_url': url, 'secret': secret}, stream)
    # Desktop autostart inherits the actual Wayland/X11 and session-bus environment.
    launcher = directory / 'start-agent'
    launcher.write_text('#!/bin/sh\ncd ' + shlex.quote(str(root)) + '\nexec ' +
        shlex.quote(sys.executable) + ' -m agent.main\n')
    launcher.chmod(0o700)
    autostart = Path.home() / '.config/autostart'
    autostart.mkdir(parents=True, exist_ok=True)
    escaped = str(launcher).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    (autostart / 'sidecar.desktop').write_text('[Desktop Entry]\nType=Application\nName=Sidecar Agent\n'
        f'Exec="{escaped}"\nTerminal=false\nX-GNOME-Autostart-enabled=true\n')
    print('Installed. Sidecar starts at your next desktop login. Run python -m agent.main to start now.')


if __name__ == '__main__':
    main()
