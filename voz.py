import asyncio
import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

import cloudscraper

logger = logging.getLogger(__name__)

# "Điểm báo" subforum: one thread per curated news article.
# voz.vn sits behind Cloudflare; plain HTTP clients get a 403 challenge page,
# so fetching goes through cloudscraper (sync, run in a thread).
FEED_URL = "https://voz.vn/f/diem-bao.33/index.rss"

_NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "slash": "http://purl.org/rss/1.0/modules/slash/",
}

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Headline:
    title: str
    url: str
    summary: str
    comments: int = 0
    published: datetime | None = None


def _clean(text: str, limit: int = 300) -> str:
    """Strip tags, unescape entities, collapse whitespace, cap length."""
    text = html.unescape(_TAG_RE.sub(" ", text))
    return " ".join(text.split())[:limit]


def parse_feed(xml_text: str, limit: int = 20) -> list[Headline]:
    """Parse the XenForo RSS feed into Headlines; malformed items are skipped."""
    headlines: list[Headline] = []
    root = ET.fromstring(xml_text)
    for item in root.iter("item"):
        if len(headlines) >= limit:
            break
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip().split("?")[0]
        if not title or not url:
            continue
        summary = _clean(item.findtext("content:encoded", default="", namespaces=_NS))
        try:
            comments = int(item.findtext("slash:comments", default="0", namespaces=_NS))
        except ValueError:
            comments = 0
        published: datetime | None = None
        pub_date = item.findtext("pubDate")
        if pub_date:
            try:
                published = parsedate_to_datetime(pub_date)
            except (TypeError, ValueError):
                pass
        headlines.append(Headline(
            title=title, url=url, summary=summary,
            comments=comments, published=published,
        ))
    return headlines


def _fetch_sync() -> str:
    scraper = cloudscraper.create_scraper()
    resp = scraper.get(FEED_URL, timeout=40)
    resp.raise_for_status()
    return resp.text


async def fetch_headlines(limit: int = 20) -> list[Headline]:
    try:
        body = await asyncio.to_thread(_fetch_sync)
    except Exception:
        # Cloudflare arms race: challenge changes can break cloudscraper any day.
        logger.exception("VOZ: failed to fetch Điểm báo feed")
        return []
    return parse_feed(body, limit=limit)
