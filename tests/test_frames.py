import asyncio
import io
import shutil
import subprocess

import pytest
from PIL import Image

from bilibili_mcp.account import Account
from bilibili_mcp.api import Bilibili, validate_bvid
from bilibili_mcp.frames import video_frame


def setup_video(monkeypatch, tmp_path, url='https://video.bilivideo.com/mock'):
    calls = []
    class Video:
        async def get_info(self):
            return {'pages': [{'cid': 11, 'duration': 2}, {'cid': 22, 'duration': 2}]}
        async def get_download_url(self, cid):
            calls.append(cid)
            return {'dash': {'video': [
                {'bandwidth': 200, 'baseUrl': 'https://video.bilivideo.com/large'},
                {'bandwidth': 100, 'baseUrl': url}]}}
    api = Bilibili(Account(tmp_path))
    def video(bvid):
        validate_bvid(bvid)
        return Video()
    monkeypatch.setattr(api, 'video', video)
    return api, calls


def setup_download(monkeypatch, payload=b'', status=200, length=None):
    class Content:
        async def iter_chunked(self, size):
            yield payload
    class Response:
        content_length = length
        content = Content()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    response = Response()
    response.status = status
    class Session:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, url, **kwargs):
            assert url == 'https://video.bilivideo.com/mock'
            assert kwargs['allow_redirects'] is False
            assert 'Cookie' not in kwargs['headers']
            return response
    monkeypatch.setattr('bilibili_mcp.frames.aiohttp.ClientSession', Session)


@pytest.mark.parametrize('bvid,seconds,part', [
    ('https://localhost', 0, 1), ('BV1234567890', -1, 1),
    ('BV1234567890', float('nan'), 1), ('BV1234567890', float('inf'), 1),
    ('BV1234567890', 2, 1), ('BV1234567890', 0, 0), ('BV1234567890', 0, 3),
])
async def test_invalid_frame_arguments(monkeypatch, tmp_path, bvid, seconds, part):
    api, calls = setup_video(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        await video_frame(api, bvid, seconds, part)
    assert not calls


@pytest.mark.parametrize('url', [
    'https://localhost/private', 'http://video.bilivideo.com/mock',
    'https://video.bilivideo.com.evil.test/mock', 'https://video.bilivideo.com:444/mock',
    'https://user@video.bilivideo.com/mock',
])
async def test_reject_unexpected_cdn(monkeypatch, tmp_path, url):
    api, _ = setup_video(monkeypatch, tmp_path, url)
    with pytest.raises(ValueError, match='Unexpected video CDN'):
        await video_frame(api, 'BV1234567890', 0)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('status,length', [(302, None), (403, None), (200, 100_000_001)])
async def test_download_rejected_and_cleaned(monkeypatch, tmp_path, status, length):
    api, _ = setup_video(monkeypatch, tmp_path)
    setup_download(monkeypatch, status=status, length=length)
    with pytest.raises(ValueError):
        await video_frame(api, 'BV1234567890', 0)
    assert not list(tmp_path.iterdir())


async def test_frame_cancellation_kills_process(monkeypatch, tmp_path):
    api, _ = setup_video(monkeypatch, tmp_path)
    setup_download(monkeypatch)
    started = asyncio.Event()
    class Process:
        returncode = None
        killed = False
        async def wait(self):
            if self.killed:
                return
            started.set()
            await asyncio.Event().wait()
        def kill(self):
            self.killed = True
            self.returncode = -9
    proc = Process()
    async def spawn(*args, **kwargs): return proc
    monkeypatch.setattr('bilibili_mcp.frames.asyncio.create_subprocess_exec', spawn)
    task = asyncio.create_task(video_frame(api, 'BV1234567890', 0))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert proc.killed
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg is required for frame extraction')
async def test_extract_selected_time_and_part(monkeypatch, tmp_path):
    fixture = tmp_path / 'fixture.mp4'
    subprocess.run([
        'ffmpeg', '-nostdin', '-v', 'error',
        '-f', 'lavfi', '-i', 'color=red:s=64x64:d=1:r=10',
        '-f', 'lavfi', '-i', 'color=blue:s=64x64:d=1:r=10',
        '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0',
        '-c:v', 'mpeg4', str(fixture),
    ], check=True, timeout=15, capture_output=True)
    payload = fixture.read_bytes()
    fixture.unlink()
    api, calls = setup_video(monkeypatch, tmp_path)
    setup_download(monkeypatch, payload=payload)
    for seconds, channel in [(0, 0), (1.5, 2)]:
        result = await video_frame(api, 'BV1234567890', seconds, part=2)
        with Image.open(io.BytesIO(result)) as image:
            assert image.format == 'JPEG'
            assert image.size == (64, 64)
            assert image.convert('RGB').getpixel((32, 32))[channel] > 200
    assert calls == [22, 22]
    assert not list(tmp_path.iterdir())
