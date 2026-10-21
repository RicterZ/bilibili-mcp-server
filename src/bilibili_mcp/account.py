import asyncio
import json
import os
import secrets
import tempfile
import time
from http.cookies import SimpleCookie
from pathlib import Path

import aiohttp
from bilibili_api import Credential
from bilibili_api.login_v2 import QrCodeLogin
from mcp.types import ImageContent, TextContent
import base64

_POLL_URL = 'https://passport.bilibili.com/x/passport-login/web/qrcode/poll'
_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'


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
            qr = QrCodeLogin()
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
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as client:
                async with client.get(
                    _POLL_URL,
                    params={'qrcode_key': self.session._QrCodeLogin__qr_key,
                            'source': 'main-fe-header'},
                    headers={'User-Agent': _USER_AGENT},
                    allow_redirects=False,
                ) as response:
                    payload = await response.json()
                    cookies = SimpleCookie()
                    for header in response.headers.getall('Set-Cookie', []):
                        cookies.load(header)
            code = payload.get('data', {}).get('code')
            if code == 0:
                cred = Credential(
                    sessdata=cookies.get('SESSDATA', {}).value if 'SESSDATA' in cookies else '',
                    bili_jct=cookies.get('bili_jct', {}).value if 'bili_jct' in cookies else '',
                    buvid3=cookies.get('buvid3', {}).value if 'buvid3' in cookies else '',
                    dedeuserid=cookies.get('DedeUserID', {}).value if 'DedeUserID' in cookies else '',
                )
                if not cred.sessdata:
                    self.session = None
                    return {'status': 'credential_missing',
                            'message': 'Bilibili confirmed the QR login but returned no session cookie; start a new login.'}
                self.save(cred)
                self.session = None
                return {'status': 'done'}
            if code == 86038:
                self.session = None
                return {'status': 'expired'}
            if code == 86090:
                return {'status': 'waiting_confirmation'}
            if code == 86101:
                return {'status': 'waiting_scan'}
            return {'status': 'unknown', 'code': code}

    async def logout(self):
        async with self.lock:
            self.session = None
            self.login_id = None
            self.path.unlink(missing_ok=True)
        return {'status': 'logged_out', 'note': 'Local credentials removed; remote sessions are not revoked.'}
