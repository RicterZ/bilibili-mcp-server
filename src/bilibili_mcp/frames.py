import asyncio
import math
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from .api import bounded


async def video_frame(api, bvid, seconds, part=1):
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('seconds must be finite and non-negative')
    video = api.video(bvid)
    pages = (await video.get_info()).get('pages') or []
    bounded(part, 1, len(pages))
    selected = pages[part - 1]
    if seconds >= selected.get('duration', 0):
        raise ValueError('seconds must be before the end of the selected part')
    streams = await video.get_download_url(cid=selected['cid'])
    tracks = (streams.get('dash') or {}).get('video') or []
    if tracks:
        track = min(tracks, key=lambda item: item.get('bandwidth', float('inf')))
        url = track.get('baseUrl') or track.get('base_url')
    else:
        tracks = streams.get('durl') or []
        if len(tracks) != 1:
            raise ValueError('No supported single video stream')
        url = tracks[0]['url']
    parsed = urlparse(url or '')
    if (parsed.scheme != 'https' or parsed.port not in (None, 443)
            or parsed.username or parsed.password
            or not (parsed.hostname or '').endswith(('.bilivideo.com', '.hdslb.com', '.bilivideo.cn'))):
        raise ValueError('Unexpected video CDN')

    # Download a bounded local file so ffmpeg cannot follow upstream URLs or redirects.
    with tempfile.TemporaryDirectory(prefix='frame-', dir=api.account.path.parent) as directory:
        source = Path(directory) / 'video'
        target = Path(directory) / 'frame.jpg'
        limit = 100_000_000
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(url, allow_redirects=False, headers={
                'Referer': 'https://www.bilibili.com/', 'User-Agent': 'Mozilla/5.0',
            }) as response:
                if response.status != 200:
                    raise ValueError('Video download failed')
                if response.content_length is not None and response.content_length > limit:
                    raise ValueError('Video exceeds 100 MB screenshot limit')
                size = 0
                with source.open('wb') as stream:
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise ValueError('Video exceeds 100 MB screenshot limit')
                        stream.write(chunk)
        proc = await asyncio.create_subprocess_exec(
            'ffmpeg', '-nostdin', '-v', 'error', '-threads', '2',
            '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mov,matroska,webm,flv',
            '-ss', str(seconds), '-i', str(source), '-map', '0:v:0', '-frames:v', '1',
            '-vf', 'scale=min(1280\\,iw):-2', '-threads', '2', '-q:v', '3',
            '-fs', '2000000', str(target),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            async with asyncio.timeout(15):
                await proc.wait()
            if proc.returncode or not target.exists() or not 0 < target.stat().st_size < 2_000_000:
                raise ValueError('Frame extraction failed')
            return target.read_bytes()
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
