"""Outbound-only Ubuntu agent. Credentials never reach the phone."""

import argparse
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from agent.capture import capture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=Path.home() / '.config/sidecar/agent.json')
    parser.add_argument('--check', action='store_true', help='Check configuration and relay authentication without capturing')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    config = json.loads(args.config.read_text())
    if args.config.stat().st_mode & 0o077:
        raise SystemExit('Agent config must be private: chmod 600 ' + str(args.config))
    url = config['relay_url'].rstrip('/')
    parsed = urlparse(url)
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')):
        raise SystemExit('The relay must use HTTPS.')
    if len(config['secret']) < 32:
        raise SystemExit('Use an agent secret of at least 32 characters.')
    session = requests.Session()
    session.headers['Authorization'] = 'Bearer ' + config['secret']
    if args.check:
        try:
            session.get(url + '/api/agent/health', timeout=(10, 30)).raise_for_status()
        except requests.RequestException:
            raise SystemExit('Relay connection or authentication failed.')
        print('Relay authentication OK. Desktop session: ' + os.getenv('XDG_SESSION_TYPE', 'unknown'))
        return
    delay = 1
    while True:
        try:
            response = session.get(url + '/api/agent/poll', timeout=(10, 30))
            response.raise_for_status()
            delay = 1
            if response.status_code == 204:
                continue
            job_id = response.json()['id']
            try:
                data = capture()
            except PermissionError:
                result = session.post(url + '/api/agent/captures/' + job_id, json={'error': 'permission'}, timeout=20)
            except Exception:
                logging.warning('Capture failed; check desktop portal availability.')
                result = session.post(url + '/api/agent/captures/' + job_id, json={'error': 'capture_failed'}, timeout=20)
            else:
                try:
                    result = session.post(url + '/api/agent/captures/' + job_id, data=data,
                        headers={'Content-Type': 'image/jpeg'}, timeout=30)
                finally:
                    del data
            result.raise_for_status()
        except requests.RequestException:
            logging.warning('Relay unavailable; retrying in %s seconds.', delay)
            time.sleep(delay)
            delay = min(delay * 2, 30)


if __name__ == '__main__':
    main()
