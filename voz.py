import asyncio
import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

# "Điểm báo" subforum: one thread per curated news article.
# voz.vn sits behind Cloudflare, which fingerprints the client TLS/HTTP2 stack;
# curl_cffi impersonating Chrome passes where requests/cloudscraper get 403.
FEED_URL = "https://voz.vn/f/diem-bao.33/index.rss"

# Only voz thread URLs are fetchable — guards against pointing the fetcher at
# arbitrary hosts (SSRF). Captures the canonical base "https://voz.vn/t/<slug>.<id>/".
THREAD_URL_RE = re.compile(r"^https?://(?:www\.)?voz\.vn/t/[\w%-]+\.\d+/")

POSTS_PER_PAGE = 20

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


@dataclass
class Post:
    author: str
    text: str


@dataclass
class Thread:
    title: str
    url: str
    posts: list[Post]


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
    resp = curl_requests.get(FEED_URL, impersonate="chrome", timeout=40)
    resp.raise_for_status()
    return resp.text


async def fetch_headlines(limit: int = 20) -> list[Headline]:
    try:
        body = await asyncio.to_thread(_fetch_sync)
    except Exception:
        # Cloudflare arms race: challenge changes can break the fetch any day.
        logger.exception("VOZ: failed to fetch Điểm báo feed")
        return []
    return parse_feed(body, limit=limit)


# --- thread comment reading ----------------------------------------------

def normalize_thread_url(raw: str) -> str | None:
    """Canonical thread base ('.../t/slug.id/') from any of its page URLs, or None."""
    match = THREAD_URL_RE.match(raw.strip())
    return match.group(0) if match else None


def _fetch_page_sync(url: str) -> str:
    resp = curl_requests.get(url, impersonate="chrome", timeout=40)
    resp.raise_for_status()
    return resp.text


def parse_thread_page(html_text: str) -> tuple[str, int, list[Post]]:
    """Return (thread title, last page number, posts on this page)."""
    soup = BeautifulSoup(html_text, "html.parser")

    title_el = soup.select_one("h1.p-title-value")
    title = title_el.get_text(strip=True) if title_el else ""

    last_page = 1
    nav = soup.select_one(".pageNav")
    if nav:
        nums = [
            int(m)
            for a in nav.select("a[href]")
            for m in re.findall(r"page-(\d+)", a["href"])
        ]
        if nums:
            last_page = max(nums)

    posts: list[Post] = []
    for article in soup.select("article.message--post"):
        name_el = article.select_one(".message-name .username")
        author = name_el.get_text(strip=True) if name_el else (article.get("data-author") or "?")
        body = article.select_one(".message-body .bbWrapper")
        if body is None:
            continue
        # Drop quoted blocks so the summary sees each poster's own words, not echoes.
        for quote in body.select("blockquote"):
            quote.decompose()
        text = " ".join(body.get_text(" ", strip=True).split())
        if text:
            posts.append(Post(author=author, text=text[:600]))
    return title, last_page, posts


async def fetch_thread(url: str, max_posts: int = 60) -> Thread | None:
    """Fetch the latest ~max_posts comments of a voz thread. None if the URL is not a voz thread."""
    base = normalize_thread_url(url)
    if base is None:
        return None
    try:
        first_html = await asyncio.to_thread(_fetch_page_sync, base)
        title, last_page, first_posts = parse_thread_page(first_html)

        pages_needed = (max_posts + POSTS_PER_PAGE - 1) // POSTS_PER_PAGE
        start_page = max(1, last_page - pages_needed + 1)
        page_map: dict[int, list[Post]] = {1: first_posts}

        to_fetch = [p for p in range(start_page, last_page + 1) if p != 1]
        if to_fetch:
            htmls = await asyncio.gather(
                *(asyncio.to_thread(_fetch_page_sync, f"{base}page-{p}") for p in to_fetch)
            )
            for p, page_html in zip(to_fetch, htmls):
                _, _, page_map[p] = parse_thread_page(page_html)

        posts: list[Post] = []
        for p in range(start_page, last_page + 1):
            posts.extend(page_map.get(p, []))
        return Thread(title=title, url=base, posts=posts[-max_posts:])
    except Exception:
        logger.exception("VOZ: failed to fetch thread %s", url)
        return None
