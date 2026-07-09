import asyncio
import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

import aiohttp

logger = logging.getLogger(__name__)

FEEDS = {
    "VnExpress": "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "Tuổi Trẻ": "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "Thanh Niên": "https://thanhnien.vn/rss/home.rss",
}

_TAG_RE = re.compile(r"<[^>]+>")

# Feeds occasionally reject default client UAs.
_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) telegram-intel-bot/1.0"}


@dataclass
class Headline:
    source: str
    title: str
    url: str
    summary: str
    published: datetime | None = None


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text)).strip()


def parse_feed(xml_text: str, source: str, per_feed: int = 10) -> list[Headline]:
    """Parse an RSS 2.0 feed into Headlines; malformed items are skipped."""
    headlines: list[Headline] = []
    root = ET.fromstring(xml_text)
    for item in root.iter("item"):
        if len(headlines) >= per_feed:
            break
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if not title or not url:
            continue
        summary = _strip_html(item.findtext("description") or "")[:200]
        published: datetime | None = None
        pub_date = item.findtext("pubDate")
        if pub_date:
            try:
                published = parsedate_to_datetime(pub_date)
            except (TypeError, ValueError):
                pass
        headlines.append(Headline(
            source=source, title=title, url=url,
            summary=summary, published=published,
        ))
    return headlines


async def _fetch_one(session: aiohttp.ClientSession, source: str, url: str,
                     per_feed: int) -> list[Headline]:
    try:
        async with session.get(url, headers=_HEADERS) as resp:
            resp.raise_for_status()
            body = await resp.text()
        return parse_feed(body, source, per_feed=per_feed)
    except Exception:
        logger.exception("VN news: failed to fetch %s feed", source)
        return []


async def fetch_headlines(per_feed: int = 10) -> list[Headline]:
    """All feeds concurrently; a dead feed just drops out of the digest."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        results = await asyncio.gather(
            *(_fetch_one(session, src, url, per_feed) for src, url in FEEDS.items())
        )
    return [h for feed in results for h in feed]
