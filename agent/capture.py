"""Quiet frame capture from a consented Wayland session, or MSS on X11."""
import atexit
import io
import json
import os
from pathlib import Path
import select
import subprocess
import threading
import time

from PIL import Image


class ScreenStream:
    def __init__(self):
        self.process = None
        self.lock = threading.Lock()

    def _read(self, count, deadline):
        chunks = bytearray()
        while len(chunks) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise TimeoutError('Screen stream timed out')
            chunk = os.read(self.process.stdout.fileno(), count - len(chunks))
            if not chunk:
                raise RuntimeError('Screen stream closed')
            chunks.extend(chunk)
        return bytes(chunks)

    def _header(self, timeout):
        deadline = time.monotonic() + timeout
        line = bytearray()
        while len(line) < 2048:
            char = self._read(1, deadline)
            if char == b'\n':
                result = json.loads(line)
                if result.get('error') == 'permission':
                    raise PermissionError('Approve screen sharing on your laptop')
                if result.get('error'):
                    raise RuntimeError('Screen stream failed; check agent diagnostics')
                return result
            line.extend(char)
        raise RuntimeError('Invalid screen stream response')

    def _start(self):
        self.process = subprocess.Popen(
            ['/usr/bin/python3', '-u', str(Path(__file__).with_name('screencast_helper.py'))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        if self._header(75).get('ready') is not True:
            raise RuntimeError('Screen stream did not start')

    def capture(self):
        with self.lock:
            try:
                if self.process is None or self.process.poll() is not None:
                    self.close()
                    self._start()
                self.process.stdin.write(b'capture\n')
                header = self._header(15)
                width, height, stride, size = (header[key] for key in ('width', 'height', 'stride', 'size'))
                if not all(isinstance(value, int) for value in (width, height, stride, size)):
                    raise RuntimeError('Invalid frame dimensions')
                if not (0 < width * height <= 40_000_000 and width > 0 and height > 0
                        and width * 3 <= stride <= width * 3 + 64
                        and stride * height <= size <= 160_000_000):
                    raise RuntimeError('Invalid frame size')
                data = self._read(size, time.monotonic() + 10)
                return encode(Image.frombytes('RGB', (width, height), data, 'raw', 'RGB', stride))
            except Exception:
                self.close()
                raise

    def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdout:
            process.stdout.close()


_stream = ScreenStream()
atexit.register(_stream.close)


def encode(source):
    output = io.BytesIO()
    with source.convert('RGB') as image:
        image.save(output, format='JPEG', quality=90, subsampling=0, optimize=True)
    return output.getvalue()


def capture():
    if os.getenv('XDG_SESSION_TYPE') == 'wayland' or os.getenv('WAYLAND_DISPLAY'):
        return _stream.capture()
    import mss
    with mss.mss() as screen:
        shot = screen.grab(screen.monitors[0])
        return encode(Image.frombytes('RGB', shot.size, shot.rgb))
