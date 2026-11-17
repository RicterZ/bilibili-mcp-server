import asyncio
import base64
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bilibili_mcp import server


@pytest.mark.parametrize('transport_args', [[], ['--transport', 'streamable-http']])
def test_http_remains_default(monkeypatch, tmp_path, transport_args):
    monkeypatch.setenv('BILI_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('BILI_MCP_TOKEN', raising=False)
    monkeypatch.setattr(sys, 'argv', ['bilibili-mcp', *transport_args])
    with pytest.raises(ValueError, match='BILI_MCP_TOKEN'):
        server.main()


@pytest.mark.parametrize('entrypoint', [
    ['-m', 'bilibili_mcp.server'],
    [str(Path(sys.executable).parent / 'bilibili-mcp')],
])
async def test_stdio_entrypoints_without_http_token(monkeypatch, tmp_path, entrypoint):
    monkeypatch.setenv('BILI_DATA_DIR', str(tmp_path))
    expected = {tool.name for tool in await server.create_server().list_tools()}
    params = StdioServerParameters(
        command=sys.executable, args=[*entrypoint, '--transport', 'stdio'],
        env={'BILI_DATA_DIR': str(tmp_path)}, cwd=tmp_path)
    async with asyncio.timeout(20):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert {tool.name for tool in tools} == expected
                assert {'post_comment', 'read_video', 'screenshot_video'} <= expected
                result = await session.call_tool('login_status', {})
                assert not result.isError
                assert json.loads(result.content[0].text) == {'logged_in': False}
                result = await session.call_tool('video_info', {'bvid': 'invalid'})
                assert result.isError


async def test_stdio_mocked_tools_and_asr_shutdown(tmp_path):
    # Mock in the child so the real CLI and stdio framing run without upstream access.
    bootstrap = '''
import asyncio
from pathlib import Path
from bilibili_mcp import server

async def info(self, bvid):
    return {'title': '测试视频', 'bvid': bvid}

async def subtitles(self, bvid, part):
    return {'duration': 5}, {'cid': 1, 'duration': 5}, None

async def frame(api, bvid, seconds, part):
    return b'mock-jpeg'

async def run(self, *args):
    await asyncio.Event().wait()

original_close = server.Jobs.close
async def close(self):
    assert self.tasks
    await original_close(self)
    assert all(task.done() for task in self.tasks)
    Path(self.account.path.parent, 'closed').touch()

server.Bilibili.info = info
server.Bilibili.subtitles = subtitles
server.video_frame = frame
server.Jobs.run = run
server.Jobs.close = close
server.main()
'''
    params = StdioServerParameters(
        command=sys.executable, args=['-c', bootstrap, '--transport', 'stdio'],
        env={'BILI_DATA_DIR': str(tmp_path)}, cwd=tmp_path)
    async with asyncio.timeout(20):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool('video_info', {'bvid': 'BV1234567890'})
                assert not result.isError
                assert json.loads(result.content[0].text)['video']['title'] == '测试视频'
                result = await session.call_tool('screenshot_video', {
                    'bvid': 'BV1234567890', 'seconds': 1})
                assert not result.isError
                assert any(item.type == 'image' and base64.b64decode(item.data) == b'mock-jpeg'
                           for item in result.content)
                result = await session.call_tool('read_video', {'bvid': 'BV1234567890'})
                assert not result.isError
                job_id = json.loads(result.content[0].text)['job_id']
                result = await session.call_tool('transcription_status', {'job_id': job_id})
                assert not result.isError
                assert json.loads(result.content[0].text)['status'] == 'queued'
    assert (tmp_path / 'closed').exists()
