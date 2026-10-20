import asyncio
import json
import os
import signal
import sys
import tempfile
import uuid
from pathlib import Path


class Jobs:
    """Bounded in-memory result cache; jobs are intentionally lost on restart."""
    def __init__(self, account, model='small', timeout=900, capacity=8):
        self.account = account
        self.model = model
        self.timeout = timeout
        self.capacity = capacity
        self.entries = {}
        self.tasks = set()
        self.slot = asyncio.Semaphore(1)

    def submit(self, bvid, cid, part):
        key = (bvid, cid, self.model, 'auto')
        for job_id, entry in self.entries.items():
            if entry['key'] == key and entry['status'] != 'error':
                return {'job_id': job_id, 'status': entry['status']}
        if sum(e['status'] in ('queued', 'running') for e in self.entries.values()) >= 3:
            raise ValueError('Transcription queue full')
        while len(self.entries) >= self.capacity:
            old = next((k for k, v in self.entries.items() if v['status'] not in ('queued', 'running')), None)
            if old is None:
                raise ValueError('Transcription capacity full')
            del self.entries[old]
        job_id = uuid.uuid4().hex
        self.entries[job_id] = {'key': key, 'status': 'queued'}
        task = asyncio.create_task(self.run(job_id, bvid, part))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return {'job_id': job_id, 'status': 'queued'}

    async def run(self, job_id, bvid, part):
        entry = self.entries[job_id]
        try:
            async with self.slot:
                entry['status'] = 'running'
                with tempfile.TemporaryDirectory(prefix='bili-asr-') as tmp:
                    request = Path(tmp) / 'request.json'
                    cred = self.account.credential()
                    cookies = {k: getattr(cred, k, '') for k in ('sessdata', 'bili_jct', 'buvid3', 'dedeuserid')} if cred else {}
                    request.write_text(json.dumps({'bvid': bvid, 'part': part, 'model': self.model, 'cookies': cookies}))
                    request.chmod(0o600)
                    proc = await asyncio.create_subprocess_exec(
                        sys.executable, '-m', 'bilibili_mcp.worker', str(request),
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                        start_new_session=True)
                    try:
                        await asyncio.wait_for(proc.wait(), self.timeout)
                        output = Path(tmp) / 'result.json'
                        if proc.returncode or not output.exists() or output.stat().st_size > 2_000_000:
                            raise ValueError('worker_failed')
                        entry.update(status='done', result=json.loads(output.read_text()))
                    finally:
                        if proc.returncode is None:
                            os.killpg(proc.pid, signal.SIGKILL)
                            await proc.wait()
        except asyncio.CancelledError:
            entry.update(status='error', error='interrupted')
            raise
        except TimeoutError:
            entry.update(status='error', error='timeout')
        except Exception:
            entry.update(status='error', error='download_or_transcription_failed')

    def status(self, job_id):
        entry = self.entries.get(job_id)
        return {k: v for k, v in entry.items() if k != 'key'} if entry else {'status': 'unknown_or_restart_or_evicted'}

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
