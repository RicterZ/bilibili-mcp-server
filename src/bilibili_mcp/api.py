import json
import re
from urllib.parse import urlparse

import aiohttp
from bilibili_api import video, search, comment


def validate_bvid(bvid):
    if not re.fullmatch(r'BV[0-9A-Za-z]{10}', bvid):
        raise ValueError('Expected a BV identifier, not a URL')
    return bvid


def bounded(value, low, high):
    if not low <= value <= high:
        raise ValueError(f'Expected {low}..{high}')
    return value


class Bilibili:
    def __init__(self, account):
        self.account = account

    def video(self, bvid):
        return video.Video(bvid=validate_bvid(bvid), credential=self.account.credential())

    async def info(self, bvid):
        return await self.video(bvid).get_info()

    async def search(self, keyword, page, page_size, order):
        bounded(len(keyword.strip()), 1, 200)
        bounded(page, 1, 100)
        bounded(page_size, 1, 20)
        orders = {'totalrank': search.OrderVideo.TOTALRANK, 'click': search.OrderVideo.CLICK,
                  'pubdate': search.OrderVideo.PUBDATE}
        if order not in orders:
            raise ValueError('Unsupported order')
        result = await search.search_by_type(keyword=keyword, search_type=search.SearchObjectType.VIDEO,
                                            page=page, order_type=orders[order])
        return {'source': 'bilibili_search_untrusted', 'page': page,
                'videos': (result.get('result') or [])[:page_size]}

    async def comments(self, bvid, page):
        bounded(page, 1, 100)
        info = await self.info(bvid)
        data = await comment.get_comments(oid=info['aid'], type_=comment.CommentResourceType.VIDEO,
                                          page_index=page, credential=self.account.credential())
        return {'source': 'bilibili_comments_untrusted', 'page': page,
                'comments': (data.get('replies') or [])[:20]}

    async def post_comment(self, bvid, text):
        bounded(len(text.strip()), 1, 1000)
        cred = self.account.credential()
        if cred is None:
            raise ValueError('Login required')
        info = await self.info(bvid)
        result = await comment.send_comment(
            text=text, oid=info['aid'], type_=comment.CommentResourceType.VIDEO,
            credential=cred)
        return {'status': 'submitted', 'bvid': bvid,
                'rpid': str(result.get('rpid_str') or result.get('rpid') or ''),
                'note': 'API accepted submission; public visibility is not verified. Do not retry blindly.'}

    async def subtitles(self, bvid, part):
        v = self.video(bvid)
        info = await v.get_info()
        pages = info.get('pages') or []
        bounded(part, 1, len(pages))
        selected = pages[part - 1]
        tracks = (await v.get_subtitle(cid=selected['cid'])).get('subtitles') or []
        if not tracks:
            return info, selected, None
        track = min(tracks, key=lambda t: {'ai-zh': 0, 'zh-CN': 1, 'zh': 2}.get(t.get('lan'), 3))
        url = track['subtitle_url']
        if url.startswith('//'):
            url = 'https:' + url
        parsed = urlparse(url)
        # Only Bilibili's subtitle CDN, including on redirects (redirects are rejected).
        if parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.hdslb.com') or parsed.port not in (None, 443):
            raise ValueError('Unexpected subtitle CDN')
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(url, allow_redirects=False) as response:
                response.raise_for_status()
                if response.status != 200:
                    raise ValueError('Unexpected subtitle redirect')
                raw = await response.content.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError('Subtitle exceeds result limit')
                data = json.loads(raw)
        segments = [{'start': x['from'], 'end': x['to'], 'text': x['content']}
                    for x in data.get('body', [])]
        return info, selected, {'source': 'subtitle_untrusted', 'language': track.get('lan'),
                                'segments': segments, 'status': 'ok' if segments else 'empty_subtitle'}
