"""Disposable ASR process. Inspired by c1overzz's lib/asr.py (MIT)."""
import json
import os
import resource
import sys
from pathlib import Path


def main():
    from yt_dlp import YoutubeDL
    from faster_whisper import WhisperModel

    request = Path(sys.argv[1])
    data = json.loads(request.read_text())
    root = request.parent
    # Enforced by the kernel even if content length is unknown or misleading.
    original_limit = resource.getrlimit(resource.RLIMIT_FSIZE)
    resource.setrlimit(resource.RLIMIT_FSIZE, (200_000_000, original_limit[1]))
    cookiefile = root / 'cookies.txt'
    mapping = {'sessdata': 'SESSDATA', 'bili_jct': 'bili_jct', 'buvid3': 'buvid3', 'dedeuserid': 'DedeUserID'}
    cookiefile.write_text('# Netscape HTTP Cookie File\n' + ''.join(
        f'.bilibili.com\tTRUE\t/\tTRUE\t0\t{mapping[k]}\t{v}\n'
        for k, v in data['cookies'].items() if v and not any(c in v for c in '\r\n\t')))
    cookiefile.chmod(0o600)
    opts = {'format': 'bestaudio', 'outtmpl': str(root / 'audio.%(ext)s'),
            'cookiefile': str(cookiefile), 'quiet': True, 'no_warnings': True,
            'noplaylist': True, 'cachedir': False, 'socket_timeout': 20,
            'retries': 2, 'max_filesize': 200_000_000,
            'match_filter': lambda info, **kw: 'duration_limit' if (info.get('duration') or 0) > 1800 else None}
    with YoutubeDL(opts) as downloader:
        info = downloader.extract_info(f"https://www.bilibili.com/video/{data['bvid']}?p={data['part']}", download=True)
        audio = downloader.prepare_filename(info)
    resource.setrlimit(resource.RLIMIT_FSIZE, original_limit)
    model = WhisperModel(data['model'], device='cpu', compute_type='int8', cpu_threads=2,
                         download_root=os.environ.get('BILI_MODEL_DIR', '/data/models'))
    segments, info = model.transcribe(audio, vad_filter=True)
    result = []
    size = 0
    for segment in segments:
        size += len(segment.text.encode())
        if size > 1_000_000:
            raise ValueError('result_limit')
        result.append({'start': segment.start, 'end': segment.end, 'text': segment.text})
    (root / 'result.json').write_text(json.dumps({'source': 'asr_untrusted', 'language': info.language,
                                                'segments': result, 'status': 'ok' if result else 'no_speech'}))


if __name__ == '__main__':
    main()
