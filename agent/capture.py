"""Capture through the desktop portal on Wayland, or MSS on X11."""

import asyncio
import io
import os
import secrets
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image


async def portal_capture():
    from dbus_next import Message, MessageType, Variant
    from dbus_next.aio import MessageBus

    bus = await MessageBus().connect()
    token = 'sidecar_' + secrets.token_hex(12)
    sender = bus.unique_name[1:].replace('.', '_')
    path = f'/org/freedesktop/portal/desktop/request/{sender}/{token}'
    result = asyncio.get_running_loop().create_future()

    def response(message):
        if message.message_type == MessageType.SIGNAL and message.path == path and message.member == 'Response':
            if not result.done():
                result.set_result(message.body)

    bus.add_message_handler(response)
    try:
        match = await bus.call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus', member='AddMatch', signature='s',
            body=[f"type='signal',interface='org.freedesktop.portal.Request',path='{path}'"]))
        if match.message_type == MessageType.ERROR:
            raise RuntimeError('Unable to subscribe to desktop portal')
        reply = await bus.call(Message(destination='org.freedesktop.portal.Desktop',
            path='/org/freedesktop/portal/desktop', interface='org.freedesktop.portal.Screenshot',
            member='Screenshot', signature='sa{sv}', body=['', {
                'handle_token': Variant('s', token), 'interactive': Variant('b', False),
                'modal': Variant('b', False)}]))
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError('Desktop screenshot portal unavailable')
        try:
            code, values = await asyncio.wait_for(result, 65)
        except asyncio.TimeoutError:
            await bus.call(Message(destination='org.freedesktop.portal.Desktop', path=path,
                interface='org.freedesktop.portal.Request', member='Close'))
            raise PermissionError('Screenshot permission timed out')
        if code != 0:
            raise PermissionError('Screenshot permission was declined')
        uri = urlparse(values['uri'].value)
        if uri.scheme != 'file' or uri.netloc not in ('', 'localhost'):
            raise RuntimeError('Unexpected screenshot URI')
        temporary = Path(unquote(uri.path))
        try:
            with Image.open(temporary) as source:
                return encode(source)
        finally:
            temporary.unlink(missing_ok=True)
    finally:
        bus.disconnect()


def encode(source):
    image = source.convert('RGB')
    output = io.BytesIO()
    image.save(output, format='JPEG', quality=90, subsampling=0, optimize=True)
    return output.getvalue()


def capture():
    if os.getenv('XDG_SESSION_TYPE') == 'wayland' or os.getenv('WAYLAND_DISPLAY'):
        return asyncio.run(portal_capture())
    import mss
    with mss.mss() as screen:
        shot = screen.grab(screen.monitors[0])
        return encode(Image.frombytes('RGB', shot.size, shot.rgb))
