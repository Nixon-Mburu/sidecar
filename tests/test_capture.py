import io
import subprocess
import sys

from PIL import Image
import pytest

from agent.capture import ScreenStream


class FakeStream(ScreenStream):
    def __init__(self, header=None):
        super().__init__()
        self.header = header or {'width': 3, 'height': 2, 'stride': 12, 'size': 24}
        self.starts = 0

    def _start(self):
        self.starts += 1
        script = """
import json, sys
header = json.loads(sys.argv[1])
for line in sys.stdin:
    sys.stdout.buffer.write(json.dumps(header).encode() + b'\\n')
    if 'error' not in header:
        sys.stdout.buffer.write(bytes([255, 0, 0] * 3 + [0, 0, 0]) * 2)
    sys.stdout.buffer.flush()
"""
        import json
        self.process = subprocess.Popen([sys.executable, '-u', '-c', script, json.dumps(self.header)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)


def test_reuses_session_and_decodes_padded_rgb():
    stream = FakeStream()
    try:
        first = stream.capture()
        second = stream.capture()
        assert stream.starts == 1
        for data in (first, second):
            image = Image.open(io.BytesIO(data))
            assert image.size == (3, 2)
            assert image.getpixel((2, 1))[0] > 240
        process = stream.process
    finally:
        stream.close()
    assert process.poll() is not None


@pytest.mark.parametrize('header,error', [
    ({'error': 'permission'}, PermissionError),
    ({'width': 3, 'height': 2, 'stride': 1, 'size': 24}, RuntimeError),
    ({'width': 3, 'height': 2, 'stride': 12, 'size': 1}, RuntimeError),
])
def test_failed_stream_is_closed_without_fallback(header, error):
    stream = FakeStream(header)
    with pytest.raises(error):
        stream.capture()
    assert stream.process is None


def test_gstreamer_frame_and_revocation():
    script = """
import threading
from agent.screencast_helper import ScreenCast, Gst
Gst.init(None)
stream = ScreenCast.__new__(ScreenCast)
stream.closed = threading.Event()
stream.pipeline = Gst.parse_launch('videotestsrc is-live=true pattern=red ! video/x-raw,format=RGB,width=3,height=2,framerate=5/1 ! appsink name=sink max-buffers=1 drop=true sync=false')
stream.sink = stream.pipeline.get_by_name('sink')
stream.pipeline.set_state(Gst.State.PLAYING)
try:
    header, pixels = stream.capture()
    assert header['width'] == 3 and header['height'] == 2
    assert pixels[:3] == bytes([255, 0, 0])
    stream.on_closed()
    try:
        stream.capture()
        raise AssertionError('Capture succeeded after revocation')
    except PermissionError:
        pass
finally:
    stream.pipeline.set_state(Gst.State.NULL)
"""
    subprocess.run(['/usr/bin/python3', '-c', script], check=True, timeout=20)
