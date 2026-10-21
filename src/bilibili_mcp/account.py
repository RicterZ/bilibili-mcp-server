import asyncio
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

from bilibili_api import Credential
from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginChannel, QrCodeLoginEvents
from mcp.types import ImageContent, TextContent
import base64


class Account:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'credential.json'
        self.lock = asyncio.Lock()
        self.session = None
        self.login_id = None
        self.expires = 0

    def credential(self):
        try:
            data = json.loads(self.path.read_text())
            keys = ('sessdata', 'bili_jct', 'buvid3', 'dedeuserid', 'ac_time_value')
            if not isinstance(data, dict) or not data.get('sessdata'):
                return None
            if any(not isinstance(data.get(k, ''), str) for k in keys):
                return None
            return Credential(**{k: data.get(k, '') for k in keys})
        except (OSError, ValueError, TypeError):
            return None

    def save(self, cred):
        fd, name = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({k: (getattr(cred, k, '') or '') for k in
                           ('sessdata', 'bili_jct', 'buvid3', 'dedeuserid', 'ac_time_value')}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    async def start(self):
        async with self.lock:
            qr = QrCodeLogin(QrCodeLoginChannel.TV)
            await qr.generate_qrcode()
            self.session = qr
            self.login_id = secrets.token_urlsafe(24)
            self.expires = time.monotonic() + 180
            return [TextContent(type='text', text=json.dumps({
                'login_id': self.login_id, 'expires_in': 180,
                'next': 'Scan in Bilibili app then call login_poll. Previous login_id is replaced.'})),
                ImageContent(type='image', mimeType='image/png',
                             data=base64.b64encode(qr.get_qrcode_picture().content).decode())]

    async def poll(self, login_id):
        async with self.lock:
            if login_id != self.login_id or not self.session:
                return {'status': 'unknown_or_replaced'}
            if time.monotonic() >= self.expires:
                self.session = None
                return {'status': 'expired'}
            state = await self.session.check_state()
            if state == QrCodeLoginEvents.DONE:
                cred = self.session.get_credential()
                if not cred or not cred.sessdata:
                    self.session = None
                    return {'status': 'credential_missing',
                            'message': 'Bilibili confirmed the QR login but returned no session cookie; start a new login.'}
                self.save(cred)
                self.session = None
                return {'status': 'done'}
            if state == QrCodeLoginEvents.TIMEOUT:
                self.session = None
                return {'status': 'expired'}
            return {'status': 'waiting_confirmation' if state == QrCodeLoginEvents.CONF else 'waiting_scan'}

    async def logout(self):
        async with self.lock:
            self.session = None
            self.login_id = None
            self.path.unlink(missing_ok=True)
        return {'status': 'logged_out', 'note': 'Local credentials removed; remote sessions are not revoked.'}
