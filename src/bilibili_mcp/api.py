import json
import re
from urllib.parse import urlparse

import aiohttp
from bilibili_api import video, search, comment
from bilibili_api import favorite_list, hot, rank, user


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

    async def user_info(self, uid):
        bounded(uid, 1, 2**63 - 1)
        u = user.User(uid=uid, credential=self.account.credential())
        info = await u.get_user_info()
        return {'uid': uid, 'name': info.get('name', ''), 'sign': info.get('sign', ''),
                'level': info.get('level', 0), 'face': info.get('face', ''),
                'fans': info.get('follower', 0), 'following': info.get('following', 0)}

    async def user_videos(self, uid, page, page_size, order, keyword):
        bounded(uid, 1, 2**63 - 1)
        bounded(page, 1, 100)
        bounded(page_size, 1, 50)
        orders = {'pubdate': user.VideoOrder.PUBDATE, 'click': user.VideoOrder.VIEW,
                  'stow': user.VideoOrder.FAVORITE}
        if order not in orders:
            raise ValueError('Unsupported user video order')
        result = await user.User(uid=uid, credential=self.account.credential()).get_videos(
            pn=page, ps=page_size, order=orders[order], keyword=keyword)
        return {'uid': uid, 'page': page, 'total': result.get('page', {}).get('count', 0),
                'videos': result.get('list', {}).get('vlist', [])}

    async def favorite_folders(self, uid=0):
        cred = self.account.credential()
        if not cred:
            raise ValueError('Login required')
        uid = uid or int(cred.dedeuserid)
        bounded(uid, 1, 2**63 - 1)
        result = await favorite_list.get_video_favorite_list(uid=uid, credential=cred)
        return {'uid': uid, 'folders': result.get('list') or []}

    async def favorite_content(self, media_id, page, keyword):
        bounded(media_id, 1, 2**63 - 1)
        bounded(page, 1, 100)
        result = await favorite_list.get_video_favorite_list_content(
            media_id=media_id, page=page, keyword=keyword or None,
            credential=self.account.credential())
        return {'media_id': media_id, 'page': page, 'has_more': result.get('has_more', False),
                'medias': result.get('medias') or []}

    async def hot_videos(self, page, page_size):
        bounded(page, 1, 100)
        bounded(page_size, 1, 50)
        result = await hot.get_hot_videos(pn=page, ps=page_size)
        return result.get('list') or []

    async def weekly_hot(self, week):
        if week <= 0:
            return await hot.get_weekly_hot_videos_list()
        bounded(week, 1, 10000)
        return await hot.get_weekly_hot_videos(week=week)

    async def ranking(self, category, days):
        categories = {'all': rank.RankType.All, 'original': rank.RankType.Original,
                      'rookie': rank.RankType.Rookie, 'douga': rank.RankType.Douga,
                      'music': rank.RankType.Music, 'dance': rank.RankType.Dance,
                      'game': rank.RankType.Game, 'knowledge': rank.RankType.Knowledge,
                      'technology': rank.RankType.Technology, 'sports': rank.RankType.Sports,
                      'car': rank.RankType.Car, 'life': rank.RankType.Life,
                      'food': rank.RankType.Food, 'animal': rank.RankType.Animal,
                      'fashion': rank.RankType.Fashion, 'ent': rank.RankType.Ent,
                      'cinephile': rank.RankType.Cinephile}
        day_types = {3: rank.RankDayType.THREE_DAY, 7: rank.RankDayType.WEEK}
        if category not in categories or days not in day_types:
            raise ValueError('Unsupported rank category or period')
        result = await rank.get_rank(type_=categories[category], day=day_types[days])
        return result.get('list') or []

    async def add_to_favorites(self, bvid, folder_id):
        bounded(folder_id, 1, 2**63 - 1)
        cred = self.account.credential()
        if not cred:
            raise ValueError('Login required')
        info = await self.video(bvid).get_info()
        try:
            folders = await self.favorite_folders(int(cred.dedeuserid))
            source = next((item for item in folders['folders'] if int(item.get('id', 0)) == folder_id), None)
            if not source:
                raise ValueError('Favorite folder does not belong to logged-in account')
            existing = await favorite_list.get_video_favorite_list_content(
                media_id=folder_id, page=1, credential=cred)
            if any(int(item.get('id', 0)) == int(info['aid']) for item in existing.get('medias') or []):
                return {'status': 'already_favorited', 'bvid': bvid, 'folder_id': folder_id}
            await favorite_list.copy_video_favorite_list_content(
                media_id_from=0, media_id_to=folder_id, aids=[int(info['aid'])], credential=cred)
        except Exception as exc:
            raise
        return {'status': 'added', 'bvid': bvid, 'folder_id': folder_id}

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
