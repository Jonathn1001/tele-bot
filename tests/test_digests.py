import os

# Must be set before any project module is imported (config.py reads these at import time)
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "dummy_hash")
os.environ.setdefault("BOT_TOKEN", "0:AADummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy_key")
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("OWNER_ID", "5730878656")

from datetime import datetime, time

import pytest
from unittest.mock import AsyncMock, patch

import analyzer
import bot
import hn
import voz
from scheduler import VN_TZ, next_run, parse_times


# ---------------------------------------------------------------------------
# scheduler
# ---------------------------------------------------------------------------

def test_parse_times_multiple():
    assert parse_times("08:30,20:00") == [time(8, 30), time(20, 0)]


def test_parse_times_empty_disables():
    assert parse_times("") == []


def test_parse_times_rejects_junk():
    with pytest.raises(ValueError):
        parse_times("morning")


def test_next_run_later_today():
    now = datetime(2026, 7, 9, 6, 0, tzinfo=VN_TZ)
    assert next_run(now, time(8, 30)) == datetime(2026, 7, 9, 8, 30, tzinfo=VN_TZ)


def test_next_run_rolls_to_tomorrow():
    now = datetime(2026, 7, 9, 21, 0, tzinfo=VN_TZ)
    assert next_run(now, time(8, 30)) == datetime(2026, 7, 10, 8, 30, tzinfo=VN_TZ)


def test_next_run_exact_minute_rolls_forward():
    # At 08:30:00 sharp the candidate is not in the future -> tomorrow,
    # so a just-fired job can't retrigger the same minute.
    now = datetime(2026, 7, 9, 8, 30, 0, tzinfo=VN_TZ)
    assert next_run(now, time(8, 30)).day == 10


# ---------------------------------------------------------------------------
# hn filtering
# ---------------------------------------------------------------------------

def _hit(title: str, points: int = 10, object_id: str = "1") -> dict:
    return {"title": title, "points": points, "objectID": object_id,
            "url": f"https://example.com/{object_id}", "num_comments": 5}


def test_filter_keeps_security_stories():
    hits = [
        _hit("Critical CVE-2026-1234 in OpenSSL", points=300, object_id="a"),
        _hit("Show HN: My new static site generator", object_id="b"),
        _hit("Massive data breach at Example Corp", points=150, object_id="c"),
    ]
    titles = [s.title for s in hn.filter_stories(hits)]
    assert titles == ["Critical CVE-2026-1234 in OpenSSL", "Massive data breach at Example Corp"]


def test_filter_sorts_by_points():
    hits = [
        _hit("Small malware writeup", points=5, object_id="a"),
        _hit("Huge ransomware attack", points=500, object_id="b"),
    ]
    assert hn.filter_stories(hits)[0].points == 500


def test_filter_respects_limit():
    hits = [_hit(f"security issue {i}", points=i, object_id=str(i)) for i in range(30)]
    assert len(hn.filter_stories(hits, limit=12)) == 12


def test_filter_missing_url_falls_back_to_hn_link():
    hit = _hit("Zero-day in router firmware", object_id="xyz")
    hit["url"] = None
    story = hn.filter_stories([hit])[0]
    assert story.url == "https://news.ycombinator.com/item?id=xyz"


def test_filter_skips_untitled():
    assert hn.filter_stories([{"points": 100, "objectID": "a"}]) == []


# ---------------------------------------------------------------------------
# voz Điểm báo RSS parsing
# ---------------------------------------------------------------------------

SAMPLE_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:slash="http://purl.org/rss/1.0/modules/slash/">
<channel>
  <title>Điểm báo</title>
  <item>
    <title>Tin thứ nhất</title>
    <link>https://voz.vn/t/tin-1.111/?utm_source=rss&amp;utm_medium=rss</link>
    <content:encoded><![CDATA[<div><blockquote>Mô tả &amp;   chi tiết</blockquote></div>]]></content:encoded>
    <slash:comments>42</slash:comments>
    <pubDate>Wed, 09 Jul 2026 06:00:00 +0700</pubDate>
  </item>
  <item>
    <title>Tin thiếu link</title>
    <link></link>
  </item>
  <item>
    <title>Tin thứ hai</title>
    <link>https://voz.vn/t/tin-2.222/</link>
  </item>
</channel></rss>"""


def test_parse_feed_extracts_items():
    headlines = voz.parse_feed(SAMPLE_RSS)
    assert [h.title for h in headlines] == ["Tin thứ nhất", "Tin thứ hai"]


def test_parse_feed_strips_tracking_params():
    assert voz.parse_feed(SAMPLE_RSS)[0].url == "https://voz.vn/t/tin-1.111/"


def test_parse_feed_strips_html_and_collapses_whitespace():
    assert voz.parse_feed(SAMPLE_RSS)[0].summary == "Mô tả & chi tiết"


def test_parse_feed_reads_comment_count():
    headlines = voz.parse_feed(SAMPLE_RSS)
    assert headlines[0].comments == 42 and headlines[1].comments == 0


def test_parse_feed_parses_pubdate():
    h = voz.parse_feed(SAMPLE_RSS)[0]
    assert h.published is not None and h.published.hour == 6


def test_parse_feed_limit():
    assert len(voz.parse_feed(SAMPLE_RSS, limit=1)) == 1


async def test_fetch_headlines_survives_cloudflare_failure():
    with patch.object(voz, "_fetch_sync", side_effect=RuntimeError("403 challenge")):
        assert await voz.fetch_headlines() == []


# ---------------------------------------------------------------------------
# digest formatting (Gemini mocked)
# ---------------------------------------------------------------------------

async def test_hn_digest_empty():
    assert await analyzer.hn_digest([]) == analyzer.NO_HN_STORIES_REPLY


async def test_hn_digest_appends_real_links():
    stories = [hn.Story(title="CVE in X", url="https://x.com/a", points=10,
                        comments=2, hn_url="https://news.ycombinator.com/item?id=1")]
    with patch.object(analyzer, "_ask", new=AsyncMock(return_value="overview")) as ask:
        result = await analyzer.hn_digest(stories)
    assert "https://x.com/a" in result and "overview" in result
    assert "<hn_stories>" in ask.call_args.kwargs["raw_contents"]


async def test_press_digest_empty():
    assert await analyzer.press_digest([]) == analyzer.NO_HEADLINES_REPLY


async def test_press_digest_numbers_items():
    headlines = [voz.Headline(title="Tin A", url="https://voz.vn/t/a.1/",
                              summary="tóm tắt", comments=7)]
    with patch.object(analyzer, "_ask", new=AsyncMock(return_value="điểm báo")) as ask:
        result = await analyzer.press_digest(headlines)
    assert "https://voz.vn/t/a.1/" in result
    assert "Tin A — tóm tắt (7 bình luận)" in ask.call_args.kwargs["raw_contents"]


# ---------------------------------------------------------------------------
# voz thread parsing + summary
# ---------------------------------------------------------------------------

THREAD_HTML = """
<html><body>
  <h1 class="p-title-value">Chủ đề thử nghiệm</h1>
  <nav class="pageNav">
    <a href="/t/x.9/page-2">2</a>
    <a href="/t/x.9/page-3">3</a>
    <a href="/t/x.9/page-5">5</a>
  </nav>
  <article class="message message--post" data-author="alice">
    <div class="message-name"><a class="username">alice</a></div>
    <div class="message-body"><div class="bbWrapper">
      <blockquote>trích dẫn người khác</blockquote>
      Ý kiến của tôi là A
    </div></div>
  </article>
  <article class="message message--post" data-author="bob">
    <div class="message-name"><a class="username">bob</a></div>
    <div class="message-body"><div class="bbWrapper">Tôi   không    đồng ý</div></div>
  </article>
  <article class="message message--post" data-author="empty">
    <div class="message-name"><a class="username">empty</a></div>
    <div class="message-body"><div class="bbWrapper"><blockquote>chỉ có quote</blockquote></div></div>
  </article>
</body></html>
"""


def test_parse_thread_page_title_and_last_page():
    title, last_page, _ = voz.parse_thread_page(THREAD_HTML)
    assert title == "Chủ đề thử nghiệm"
    assert last_page == 5


def test_parse_thread_page_strips_quotes_and_collapses_ws():
    _, _, posts = voz.parse_thread_page(THREAD_HTML)
    assert posts[0].author == "alice"
    assert posts[0].text == "Ý kiến của tôi là A"
    assert posts[1].text == "Tôi không đồng ý"


def test_parse_thread_page_skips_quote_only_post():
    _, _, posts = voz.parse_thread_page(THREAD_HTML)
    # 'empty' had only a quote -> no own words -> dropped
    assert [p.author for p in posts] == ["alice", "bob"]


@pytest.mark.parametrize("url,ok", [
    ("https://voz.vn/t/abc.123456/", True),
    ("https://voz.vn/t/abc.123456/page-7", True),
    ("http://www.voz.vn/t/x.9/", True),
    ("https://voz.vn/f/diem-bao.33/", False),
    ("https://evil.com/t/x.1/", False),
    ("not a url", False),
])
def test_normalize_thread_url(url, ok):
    result = voz.normalize_thread_url(url)
    assert (result is not None) == ok
    if ok:
        assert result.endswith(".123456/") or result.endswith(".9/")


async def test_fetch_thread_rejects_non_voz_url():
    assert await voz.fetch_thread("https://evil.com/t/x.1/") is None


async def test_fetch_thread_single_page():
    import re as _re
    page = _re.sub(r'<nav class="pageNav">.*?</nav>', "", THREAD_HTML, flags=_re.DOTALL)
    with patch.object(voz, "_fetch_page_sync", return_value=page) as fetch:
        thread = await voz.fetch_thread("https://voz.vn/t/x.9/")
    assert thread is not None
    assert thread.title == "Chủ đề thử nghiệm"
    assert [p.author for p in thread.posts] == ["alice", "bob"]
    assert fetch.call_count == 1  # no pagination -> single fetch


async def test_fetch_thread_returns_none_on_fetch_error():
    with patch.object(voz, "_fetch_page_sync", side_effect=RuntimeError("403")):
        assert await voz.fetch_thread("https://voz.vn/t/x.9/") is None


async def test_thread_summary_empty_posts():
    thread = voz.Thread(title="T", url="https://voz.vn/t/x.9/", posts=[])
    assert await analyzer.thread_summary(thread) == analyzer.EMPTY_THREAD_REPLY


async def test_thread_summary_wraps_posts_and_titles():
    thread = voz.Thread(
        title="Chủ đề X", url="https://voz.vn/t/x.9/",
        posts=[voz.Post(author="alice", text="quan điểm A")],
    )
    with patch.object(analyzer, "_ask", new=AsyncMock(return_value="tóm tắt")) as ask:
        result = await analyzer.thread_summary(thread)
    assert "Chủ đề X" in result and "1 bình luận" in result
    raw = ask.call_args.kwargs["raw_contents"]
    assert "<thread_posts>" in raw and "[alice]: quan điểm A" in raw


async def test_cmd_thread_requires_url():
    msg = _mock_msg()
    cmd = type("C", (), {"args": None})()
    await bot.cmd_thread(msg, cmd)
    assert "Usage" in msg.answer.call_args[0][0]


async def test_cmd_thread_rejects_bad_url():
    msg = _mock_msg()
    cmd = type("C", (), {"args": "https://evil.com/t/x.1/"})()
    await bot.cmd_thread(msg, cmd)
    assert "voz" in msg.answer.call_args[0][0].lower()


async def test_cmd_thread_summarizes():
    msg = _mock_msg()
    cmd = type("C", (), {"args": "https://voz.vn/t/x.9/"})()
    fake = voz.Thread(title="T", url="https://voz.vn/t/x.9/", posts=[voz.Post("a", "b")])
    with patch.object(bot.voz, "fetch_thread", new=AsyncMock(return_value=fake)), \
         patch.object(bot.analyzer, "thread_summary", new=AsyncMock(return_value="summary")):
        await bot.cmd_thread(msg, cmd)
    assert msg.answer.call_count == 2  # status + summary


async def test_cmd_thread_fetch_failure_sanitized():
    msg = _mock_msg()
    cmd = type("C", (), {"args": "https://voz.vn/t/x.9/"})()
    with patch.object(bot.voz, "fetch_thread", new=AsyncMock(return_value=None)):
        await bot.cmd_thread(msg, cmd)
    assert msg.answer.call_args[0][0] == analyzer.ANALYSIS_FAILED_REPLY


def test_thread_command_is_rate_limited():
    assert "/thread" in bot.ANALYSIS_COMMANDS


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def _mock_msg() -> AsyncMock:
    m = AsyncMock()
    m.answer = AsyncMock()
    return m


async def test_cmd_hn_replies_with_digest():
    msg = _mock_msg()
    with patch.object(bot.hn, "fetch_security_stories", new=AsyncMock(return_value=[])), \
         patch.object(bot.analyzer, "hn_digest", new=AsyncMock(return_value="digest")):
        await bot.cmd_hn(msg)
    assert msg.answer.call_count == 2  # status + digest


async def test_cmd_hn_fetch_failure_is_sanitized():
    msg = _mock_msg()
    with patch.object(bot.hn, "fetch_security_stories", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await bot.cmd_hn(msg)
    assert msg.answer.call_args[0][0] == analyzer.ANALYSIS_FAILED_REPLY


async def test_cmd_paper_replies_with_digest():
    msg = _mock_msg()
    with patch.object(bot.voz, "fetch_headlines", new=AsyncMock(return_value=[])), \
         patch.object(bot.analyzer, "press_digest", new=AsyncMock(return_value="điểm báo")):
        await bot.cmd_paper(msg)
    assert msg.answer.call_count == 2


async def test_hn_command_is_rate_limited():
    assert "/hn" in bot.ANALYSIS_COMMANDS and "/paper" in bot.ANALYSIS_COMMANDS
