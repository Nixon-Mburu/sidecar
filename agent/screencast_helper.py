"""System-Python helper for consented PipeWire capture; pixels only cross a pipe."""
import json
import os
import secrets
import sys
import threading

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
from gi.repository import Gio, GLib, Gst, GstVideo

DEST = 'org.freedesktop.portal.Desktop'
PATH = '/org/freedesktop/portal/desktop'
INTERFACE = 'org.freedesktop.portal.ScreenCast'


class ScreenCast:
    def __init__(self):
        Gst.init(None)
        GLib.set_application_name('Sidecar')
        GLib.set_prgname('sidecar')
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.loop.run, daemon=True)
        self.thread.start()
        self.session = self.pipeline = self.remote_fd = self.subscription = None
        self.closed = threading.Event()

    def request(self, method, signature, args, options):
        token = 'sidecar_' + secrets.token_hex(12)
        sender = self.bus.get_unique_name()[1:].replace('.', '_')
        path = f'{PATH}/request/{sender}/{token}'
        event, result = threading.Event(), []

        def response(_bus, _sender, _path, _interface, _signal, params, _data):
            result.append(params.unpack())
            event.set()

        subscription = self.bus.signal_subscribe(DEST, 'org.freedesktop.portal.Request',
            'Response', path, None, Gio.DBusSignalFlags.NONE, response, None)
        try:
            options = {**options, 'handle_token': GLib.Variant('s', token)}
            reply = self.bus.call_sync(DEST, PATH, INTERFACE, method,
                GLib.Variant(signature, (*args, options)), None, Gio.DBusCallFlags.NONE, 10000, None)
            if reply.unpack()[0] != path:
                raise RuntimeError('Unexpected portal request path')
            if not event.wait(65):
                self.bus.call_sync(DEST, path, 'org.freedesktop.portal.Request', 'Close',
                    None, None, Gio.DBusCallFlags.NONE, 2000, None)
                raise PermissionError('Screen sharing permission timed out')
            code, values = result[0]
            if code != 0:
                raise PermissionError('Screen sharing was declined')
            return values
        finally:
            self.bus.signal_unsubscribe(subscription)

    def start(self):
        result = self.request('CreateSession', '(a{sv})', (), {
            'session_handle_token': GLib.Variant('s', 'sidecar_' + secrets.token_hex(12))})
        self.session = result['session_handle']
        self.subscription = self.bus.signal_subscribe(DEST, 'org.freedesktop.portal.Session',
            'Closed', self.session, None, Gio.DBusSignalFlags.NONE, self.on_closed, None)
        self.request('SelectSources', '(oa{sv})', (self.session,), {
            'types': GLib.Variant('u', 1), 'multiple': GLib.Variant('b', False)})
        result = self.request('Start', '(osa{sv})', (self.session, ''), {})
        streams = result.get('streams', [])
        if len(streams) != 1 or self.closed.is_set():
            raise PermissionError('Screen sharing is not active')
        node_id, properties = streams[0]
        reply, descriptors = self.bus.call_with_unix_fd_list_sync(DEST, PATH, INTERFACE,
            'OpenPipeWireRemote', GLib.Variant('(oa{sv})', (self.session, {})),
            GLib.VariantType.new('(h)'), Gio.DBusCallFlags.NONE, 10000, None, None)
        self.remote_fd = descriptors.get(reply.unpack()[0])
        self.pipeline = Gst.parse_launch(
            'pipewiresrc name=source keepalive-time=1000 ! '
            'videoconvert ! video/x-raw,format=RGB ! '
            'appsink name=sink max-buffers=1 drop=true sync=false enable-last-sample=false')
        source = self.pipeline.get_by_name('source')
        source.set_property('fd', self.remote_fd)
        source.set_property('client-name', 'Sidecar')
        serial = properties.get('pipewire-serial')
        if serial is not None and source.find_property('target-object'):
            source.set_property('target-object', str(serial))
        else:
            source.set_property('path', str(node_id))
        if source.find_property('on-disconnect'):
            source.set_property('on-disconnect', 2)
        self.sink = self.pipeline.get_by_name('sink')
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message::error', self.on_closed)
        bus.connect('message::eos', self.on_closed)
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('Could not start PipeWire capture')

    def on_closed(self, *_args):
        self.closed.set()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)

    def capture(self):
        if self.closed.is_set():
            raise PermissionError('Screen sharing ended')
        # Drop the queued sample and wait for the next frame, rather than reusing stale pixels.
        self.sink.emit('try-pull-sample', 0)
        sample = self.sink.emit('try-pull-sample', 10 * Gst.SECOND)
        if self.closed.is_set():
            raise PermissionError('Screen sharing ended')
        if sample is None:
            raise RuntimeError('No screen frame received')
        info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
        if info.width * info.height > 40_000_000:
            raise RuntimeError('Screen is too large')
        buffer = sample.get_buffer()
        ok, mapping = buffer.map(Gst.MapFlags.READ)
        if not ok:
            raise RuntimeError('Could not read screen frame')
        try:
            data = bytes(mapping.data)
        finally:
            buffer.unmap(mapping)
        if self.closed.is_set():
            raise PermissionError('Screen sharing ended')
        return {'width': info.width, 'height': info.height, 'stride': info.stride[0], 'size': len(data)}, data

    def close(self):
        self.on_closed()
        if self.subscription:
            self.bus.signal_unsubscribe(self.subscription)
        if self.session:
            try:
                self.bus.call_sync(DEST, self.session, 'org.freedesktop.portal.Session', 'Close',
                    None, None, Gio.DBusCallFlags.NONE, 2000, None)
            except GLib.Error:
                pass
        if self.remote_fd is not None:
            os.close(self.remote_fd)
        self.loop.quit()
        self.thread.join(timeout=2)


def send(header, data=b''):
    sys.stdout.buffer.write(json.dumps(header).encode() + b'\n')
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def main():
    session = ScreenCast()
    try:
        session.start()
        send({'ready': True})
        for command in sys.stdin:
            if command.strip() != 'capture':
                break
            try:
                header, data = session.capture()
                send(header, data)
                del data
            except PermissionError:
                send({'error': 'permission'})
                break
            except Exception:
                send({'error': 'capture_failed'})
                break
    except PermissionError:
        send({'error': 'permission'})
    except Exception as error:
        print(f'Sidecar screen stream: {type(error).__name__}: {error}', file=sys.stderr)
        send({'error': 'capture_failed'})
    finally:
        session.close()


if __name__ == '__main__':
    main()
