import asyncio
import base64
import json
import socket
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from bilibili_mcp.account import Account
from bilibili_mcp.api import Bilibili, validate_bvid
from bilibili_mcp.jobs import Jobs
from bilibili_mcp.server import create_app


async def test_http(monkeypatch, tmp_path):
    monkeypatch.setenv('BILI_MCP_TOKEN', 'x' * 48)
    monkeypatch.setenv('BILI_DATA_DIR', str(tmp_path))
    async def info(self, bvid):
        validate_bvid(bvid)
        return {'bvid': bvid, 'title': 'mock'}
    monkeypatch.setattr(Bilibili, 'info', info)
    async def subtitles(self, bvid, part):
        if part == 3:
            raise RuntimeError('upstream unavailable')
        result = {'source': 'subtitle_untrusted', 'segments': []} if part == 2 else None
        return {'duration': 5}, {'cid': part, 'duration': 1801 if part == 4 else 5}, result
    submissions = []
    def submit(self, bvid, cid, part):
        submissions.append((bvid, cid, part))
        return {'job_id': 'mock-job', 'status': 'queued'}
    monkeypatch.setattr(Bilibili, 'subtitles', subtitles)
    monkeypatch.setattr(Jobs, 'submit', submit)
    class QR:
        async def generate_qrcode(self): pass
        def get_qrcode_picture(self):
            return SimpleNamespace(content=b'png-test')
    monkeypatch.setattr('bilibili_mcp.account.QrCodeLogin', QR)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), log_level='critical'))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started: break
            await asyncio.sleep(.01)
        url = f'http://127.0.0.1:{port}'
        async with httpx.AsyncClient() as client:
            assert (await client.get(url + '/health')).status_code == 200
            for method in ('GET', 'POST', 'DELETE'):
                assert (await client.request(method, url + '/mcp')).status_code == 401
            assert (await client.post(url + '/mcp', headers={'Authorization': 'Bearer ' + 'x'*48, 'Host': 'evil.example', 'Content-Type': 'application/json'})).status_code == 421
        async with streamable_http_client(url + '/mcp', http_client=httpx.AsyncClient(headers={'Authorization': 'Bearer ' + 'x'*48})) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                assert names == {'post_comment', 'login_start', 'login_poll', 'login_status', 'logout', 'search_videos', 'video_info', 'get_comments', 'read_video', 'transcription_status'}
                result = await session.call_tool('video_info', {'bvid': 'BV1234567890'})
                assert not result.isError
                assert (await session.call_tool('video_info', {'bvid': 'http://localhost'})).isError
                read_tool = next(t for t in (await session.list_tools()).tools if t.name == 'read_video')
                assert 'allow_asr' not in read_tool.inputSchema['properties']
                result = await session.call_tool('read_video', {'bvid': 'BV1234567890'})
                assert not result.isError
                assert json.loads(result.content[0].text)['job_id'] == 'mock-job'
                result = await session.call_tool('read_video', {'bvid': 'BV1234567890', 'part': 2})
                assert json.loads(result.content[0].text)['source'] == 'subtitle_untrusted'
                for part in (3, 4):
                    assert (await session.call_tool('read_video', {'bvid': 'BV1234567890', 'part': part})).isError
                assert submissions == [('BV1234567890', 1, 1)]
                qr = await session.call_tool('login_start', {})
                assert any(x.type == 'image' and base64.b64decode(x.data) == b'png-test' for x in qr.content)
    finally:
        server.should_exit = True
        await task
        sock.close()


async def test_account(monkeypatch, tmp_path):
    account = Account(tmp_path)
    account.path.write_text('{broken')
    assert account.credential() is None
    cred = SimpleNamespace(sessdata='secret', bili_jct='csrf', buvid3=None, dedeuserid='123', ac_time_value=None)
    account.save(cred)
    assert account.path.stat().st_mode & 0o777 == 0o600
    assert account.credential().sessdata == 'secret'
    assert Account(tmp_path).credential().sessdata == 'secret'
    account.session = object()
    account.login_id = 'id'
    account.expires = 0
    assert (await account.poll('id'))['status'] == 'expired'
    assert (await account.poll('wrong'))['status'] == 'unknown_or_replaced'
    await account.logout()
    assert not account.path.exists()


async def test_jobs(monkeypatch, tmp_path):
    jobs = Jobs(Account(tmp_path))
    async def fake_run(*args):
        await asyncio.sleep(10)
    monkeypatch.setattr(jobs, 'run', fake_run)
    first = jobs.submit('BV1234567890', 1, 1)
    assert jobs.submit('BV1234567890', 1, 1) == first
    jobs.submit('BV1234567890', 2, 2)
    jobs.submit('BV1234567890', 3, 3)
    with pytest.raises(ValueError):
        jobs.submit('BV1234567890', 4, 4)
    assert jobs.status('missing')['status'].startswith('unknown')
    await jobs.close()


async def test_subtitle_no_fallback(monkeypatch, tmp_path):
    api = Bilibili(Account(tmp_path))
    class V:
        async def get_info(self): return {'pages': [{'cid': 1, 'duration': 5}]}
        async def get_subtitle(self, cid): raise RuntimeError('upstream failure')
    monkeypatch.setattr(api, 'video', lambda _: V())
    with pytest.raises(RuntimeError):
        await api.subtitles('BV1234567890', 1)
    with pytest.raises(ValueError):
        await api.subtitles('BV1234567890', 0)


def test_token_required(monkeypatch):
    monkeypatch.delenv('BILI_MCP_TOKEN', raising=False)
    with pytest.raises(ValueError): create_app()


async def test_login_states_and_atomic_completion(monkeypatch, tmp_path):
    from bilibili_api.login_v2 import QrCodeLoginEvents
    account = Account(tmp_path)
    calls = []
    class QR:
        async def generate_qrcode(self): pass
        def get_qrcode_picture(self): return SimpleNamespace(content=b'png')
        async def check_state(self):
            calls.append(1)
            await asyncio.sleep(.01)
            return QrCodeLoginEvents.DONE
        def get_credential(self):
            return SimpleNamespace(sessdata='secret', bili_jct='csrf', buvid3=None, dedeuserid='123', ac_time_value=None)
    monkeypatch.setattr('bilibili_mcp.account.QrCodeLogin', QR)
    await account.start()
    old = account.login_id
    await account.start()
    assert (await account.poll(old))['status'] == 'unknown_or_replaced'
    results = await asyncio.gather(account.poll(account.login_id), account.poll(account.login_id))
    assert len(calls) == 1
    assert {r['status'] for r in results} == {'done', 'unknown_or_replaced'}


async def test_worker_timeout_and_cleanup(monkeypatch, tmp_path):
    import sys
    from pathlib import Path
    real_spawn = asyncio.create_subprocess_exec
    roots = []
    processes = []
    async def spawn(*args, **kwargs):
        roots.append(Path(args[-1]).parent)
        proc = await real_spawn(sys.executable, '-c', 'import time; time.sleep(30)', **kwargs)
        processes.append(proc)
        return proc
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    jobs = Jobs(Account(tmp_path), timeout=.05)
    job = jobs.submit('BV1234567890', 1, 1)
    await asyncio.gather(*jobs.tasks)
    assert jobs.status(job['job_id']) == {'status': 'error', 'error': 'timeout'}
    assert all(p.returncode is not None for p in processes)
    assert all(not p.exists() for p in roots)


async def test_worker_error(monkeypatch, tmp_path):
    import sys
    real_spawn = asyncio.create_subprocess_exec
    async def spawn(*args, **kwargs):
        return await real_spawn(sys.executable, '-c', 'raise SystemExit(1)', **kwargs)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    jobs = Jobs(Account(tmp_path))
    job = jobs.submit('BV1234567890', 1, 1)
    await asyncio.gather(*jobs.tasks)
    assert jobs.status(job['job_id'])['error'] == 'download_or_transcription_failed'


async def test_post_comment(monkeypatch, tmp_path):
    account = Account(tmp_path)
    api = Bilibili(account)
    calls = []
    async def info(bvid):
        validate_bvid(bvid)
        return {'aid': 123}
    async def send(**kwargs):
        calls.append(kwargs)
        return {'rpid': 456}
    monkeypatch.setattr(api, 'info', info)
    monkeypatch.setattr('bilibili_mcp.api.comment.send_comment', send)
    with pytest.raises(ValueError):
        await api.post_comment('BV1234567890', 'hello')
    monkeypatch.setattr(account, 'credential', lambda: object())
    for text in (' ', 'x' * 1001):
        with pytest.raises(ValueError):
            await api.post_comment('BV1234567890', text)
    result = await api.post_comment('BV1234567890', 'hello')
    assert result['rpid'] == '456'
    assert len(calls) == 1 and calls[0]['oid'] == 123
