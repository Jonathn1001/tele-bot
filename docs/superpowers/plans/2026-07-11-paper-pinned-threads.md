# /paper Pinned Megathread Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** /paper (and the scheduled press push) appends a short Vietnamese news-update section per pinned news megathread on voz f/Điểm báo.

**Architecture:** `voz.fetch_pinned_news_threads()` scrapes the forum page's sticky block (meta stickies filtered by an anchored title regex), the existing `voz.fetch_thread` pulls each megathread's recent posts, a new `analyzer.megathread_update` Gemini call turns them into a bulleted update, and a new `bot.build_press_report()` composes digest + sections for both `cmd_paper` and main.py's `press_job`.

**Tech Stack:** Python 3, curl_cffi (Chrome impersonation), BeautifulSoup, google-genai, pytest + AsyncMock.

**Spec:** `docs/superpowers/specs/2026-07-11-paper-pinned-threads-design.md`

## Global Constraints

- No new dependencies.
- Pinned megathreads capped at `limit=2` per digest (Gemini cost bound).
- All network fetches fail soft: log + empty result, never crash the bot.
- Megathread update replies are Vietnamese only (`"Chỉ trả lời bằng tiếng Việt."`).
- Meta-sticky filter MUST be anchored at title start (`^\s*(nội quy|report)`, case-insensitive) — the Iran megathread's title contains "nội quy" mid-string ("… | Đọc kỹ nội quy trước khi cmt | …") and must NOT be filtered.
- Run tests with `.venv/bin/python3 -m pytest tests/ -q` (plain `python`/bare `python3` is the system interpreter without deps).
- Commit specific files only; never commit `docker-compose.yml`.

---

### Task 1: voz.py — pinned thread discovery

**Files:**
- Modify: `voz.py` (add `FORUM_URL`, `META_STICKY_RE`, `PinnedThread`, `parse_pinned_threads`, `fetch_pinned_news_threads`)
- Test: `tests/test_digests.py`

**Interfaces:**
- Consumes: existing `normalize_thread_url(raw: str) -> str | None`, `_fetch_page_sync(url: str) -> str`.
- Produces: `voz.PinnedThread` dataclass with fields `title: str`, `url: str` (canonical `https://voz.vn/t/<slug>.<id>/`); `voz.parse_pinned_threads(html_text: str) -> list[PinnedThread]`; `async voz.fetch_pinned_news_threads(limit: int = 2) -> list[PinnedThread]`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_digests.py`:

```python
# ---------------------------------------------------------------------------
# pinned news threads (f/Điểm báo sticky block)
# ---------------------------------------------------------------------------

FORUM_HTML = """
<html><body>
  <div class="structItemContainer-group structItemContainer-group--sticky">
    <div class="structItem structItem--thread">
      <div class="structItem-title"><a href="/t/report-f33.111/">Report F33</a></div>
    </div>
    <div class="structItem structItem--thread">
      <div class="structItem-title">
        <a href="/t/tinh-hinh-iran.222/">Tình hình Iran và các bên liên quan | Đọc kỹ nội quy trước khi cmt</a>
      </div>
    </div>
    <div class="structItem structItem--thread">
      <div class="structItem-title"><a href="/t/noi-quy-box.333/">NỘI QUY box Điểm báo</a></div>
    </div>
    <div class="structItem structItem--thread">
      <div class="structItem-title"><a href="/t/chien-su-gaza.444/">Chiến sự Gaza cập nhật</a></div>
    </div>
    <div class="structItem structItem--thread">
      <div class="structItem-title"><a href="/f/not-a-thread.9/">Nhãn chuyên mục</a></div>
    </div>
  </div>
  <div class="structItemContainer-group js-threadList">
    <div class="structItem structItem--thread">
      <div class="structItem-title"><a href="/t/tin-thuong.555/">Tin thường không ghim</a></div>
    </div>
  </div>
</body></html>
"""


def test_parse_pinned_threads_filters_meta_and_non_threads():
    pinned = voz.parse_pinned_threads(FORUM_HTML)
    titles = [p.title for p in pinned]
    # meta stickies (title STARTS with Report / Nội quy, any case) are dropped;
    # "nội quy" mid-title (the Iran megathread) must survive
    assert titles == [
        "Tình hình Iran và các bên liên quan | Đọc kỹ nội quy trước khi cmt",
        "Chiến sự Gaza cập nhật",
    ]
    # relative hrefs become canonical absolute thread URLs
    assert pinned[0].url == "https://voz.vn/t/tinh-hinh-iran.222/"
    # non-sticky threads are never included
    assert all("tin-thuong" not in p.url for p in pinned)


async def test_fetch_pinned_news_threads_caps_at_limit():
    with patch.object(voz, "_fetch_page_sync", return_value=FORUM_HTML):
        pinned = await voz.fetch_pinned_news_threads(limit=1)
    assert len(pinned) == 1
    assert pinned[0].url == "https://voz.vn/t/tinh-hinh-iran.222/"


async def test_fetch_pinned_news_threads_survives_fetch_failure():
    with patch.object(voz, "_fetch_page_sync", side_effect=RuntimeError("cf")):
        assert await voz.fetch_pinned_news_threads() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_digests.py -q -k "pinned"`
Expected: FAIL — `AttributeError: module 'voz' has no attribute 'parse_pinned_threads'`

- [ ] **Step 3: Implement** — in `voz.py`:

Below `FEED_URL`, add:

```python
# Forum landing page — pinned rolling-news megathreads live in its sticky
# block and never appear in the RSS feed (which only carries new threads).
FORUM_URL = "https://voz.vn/f/diem-bao.33/"

# Meta stickies (rules, report-to-mods) — anchored: the Iran megathread's
# title CONTAINS "nội quy" mid-string and must not be filtered.
META_STICKY_RE = re.compile(r"^\s*(nội quy|report)", re.IGNORECASE)
```

Below the `Headline` dataclass, add:

```python
@dataclass
class PinnedThread:
    title: str
    url: str  # canonical "https://voz.vn/t/<slug>.<id>/"
```

Below `fetch_headlines`, add:

```python
def parse_pinned_threads(html_text: str) -> list[PinnedThread]:
    """News megathreads from the forum page's sticky block; meta stickies dropped."""
    soup = BeautifulSoup(html_text, "html.parser")
    pinned: list[PinnedThread] = []
    for item in soup.select(".structItemContainer-group--sticky .structItem--thread"):
        link = item.select_one(".structItem-title a[href*='/t/']")
        if link is None:
            continue
        title = link.get_text(strip=True)
        href = link["href"]
        absolute = href if href.startswith("http") else f"https://voz.vn{href}"
        url = normalize_thread_url(absolute)
        if url is None or META_STICKY_RE.search(title):
            continue
        pinned.append(PinnedThread(title=title, url=url))
    return pinned


async def fetch_pinned_news_threads(limit: int = 2) -> list[PinnedThread]:
    try:
        body = await asyncio.to_thread(_fetch_page_sync, FORUM_URL)
    except Exception:
        logger.exception("VOZ: failed to fetch Điểm báo forum page")
        return []
    return parse_pinned_threads(body)[:limit]
```

Note: `_fetch_page_sync` is defined lower in the file (thread-reading section); Python resolves it at call time, no reordering needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add voz.py tests/test_digests.py
git commit -m "feat(voz): discover pinned news megathreads on f/Diem bao"
```

---

### Task 2: analyzer.py — megathread update summary

**Files:**
- Modify: `analyzer.py` (add `megathread_update` below `thread_summary`)
- Test: `tests/test_digests.py`

**Interfaces:**
- Consumes: existing `_ask(system, messages, raw_contents=...)`, `PLAIN_TEXT_FORMAT_INSTRUCTION`, `Thread` (from voz).
- Produces: `async analyzer.megathread_update(thread: Thread) -> str` — `""` when `thread.posts` is empty; note `_ask` returns `ANALYSIS_FAILED_REPLY` on Gemini failure (the composer in Task 3 filters that out).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_digests.py`:

```python
# ---------------------------------------------------------------------------
# megathread update (pinned thread → news brief)
# ---------------------------------------------------------------------------

async def test_megathread_update_empty_posts_returns_empty():
    thread = voz.Thread(title="T", url="https://voz.vn/t/x.9/", posts=[])
    assert await analyzer.megathread_update(thread) == ""


async def test_megathread_update_prompt_vietnamese_and_delimited():
    thread = voz.Thread(
        title="Tình hình Iran", url="https://voz.vn/t/x.9/",
        posts=[voz.Post(author="alice", text="Iran vừa tuyên bố X")],
    )
    with patch.object(analyzer, "_ask", new=AsyncMock(return_value="• cập nhật")) as ask:
        result = await analyzer.megathread_update(thread)
    assert result == "• cập nhật"
    system = ask.call_args[0][0]
    assert "Chỉ trả lời bằng tiếng Việt." in system
    assert "Tình hình Iran" in system
    assert "Tiếng Việt:" not in system  # no bilingual section labels
    raw = ask.call_args.kwargs["raw_contents"]
    assert "<thread_posts>" in raw and "[alice]: Iran vừa tuyên bố X" in raw
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_digests.py -q -k "megathread"`
Expected: FAIL — `AttributeError: module 'analyzer' has no attribute 'megathread_update'`

- [ ] **Step 3: Implement** — in `analyzer.py`, below `thread_summary`:

```python
async def megathread_update(thread: Thread) -> str:
    """Vietnamese news-update brief from a pinned megathread's recent comments."""
    if not thread.posts:
        return ""
    body = "\n".join(f"[{p.author}]: {p.text}" for p in thread.posts)
    return await _ask(
        "Bạn đang theo dõi thread tin nóng trên diễn đàn voz có tiêu đề "
        f"'{thread.title}'. Từ các bình luận mới nhất dưới đây, tóm tắt những "
        "diễn biến mới nhất mà người bình luận đang đưa tin hoặc thảo luận — "
        "dạng bản tin cập nhật, tối đa 8 dòng bắt đầu bằng '•'. "
        "Không phân tích cảm xúc cộng đồng. "
        "Chỉ trả lời bằng tiếng Việt. "
        f"{PLAIN_TEXT_FORMAT_INSTRUCTION}",
        [],
        raw_contents=f"<thread_posts>\n{body}\n</thread_posts>",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add analyzer.py tests/test_digests.py
git commit -m "feat(analyzer): Vietnamese news-update brief for pinned megathreads"
```

---

### Task 3: bot.build_press_report() + rewire cmd_paper and press_job

**Files:**
- Modify: `bot.py` (add `build_press_report`; `cmd_paper` uses it)
- Modify: `main.py` (`press_job` uses it; extend the `from bot import ...` line)
- Test: `tests/test_digests.py` (new composition tests; update `test_cmd_paper_replies_with_digest`)

**Interfaces:**
- Consumes: `voz.fetch_headlines()`, `voz.fetch_pinned_news_threads()` (Task 1), `voz.fetch_thread(url, max_posts=40)`, `analyzer.press_digest(headlines)`, `analyzer.megathread_update(thread)` (Task 2), `analyzer.ANALYSIS_FAILED_REPLY`.
- Produces: `async bot.build_press_report() -> str` — used by `cmd_paper` and `main.press_job`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_digests.py`:

```python
# ---------------------------------------------------------------------------
# build_press_report — digest + megathread sections
# ---------------------------------------------------------------------------

def _pinned(title="Tình hình Iran", url="https://voz.vn/t/iran.222/"):
    return voz.PinnedThread(title=title, url=url)


async def test_press_report_appends_megathread_section():
    thread = voz.Thread(title="Tình hình Iran", url="https://voz.vn/t/iran.222/",
                        posts=[voz.Post("a", "b")])
    with patch.object(bot.voz, "fetch_headlines", new=AsyncMock(return_value=[])), \
         patch.object(bot.analyzer, "press_digest", new=AsyncMock(return_value="điểm báo")), \
         patch.object(bot.voz, "fetch_pinned_news_threads", new=AsyncMock(return_value=[_pinned()])), \
         patch.object(bot.voz, "fetch_thread", new=AsyncMock(return_value=thread)), \
         patch.object(bot.analyzer, "megathread_update", new=AsyncMock(return_value="• diễn biến")):
        report = await bot.build_press_report()
    assert "điểm báo" in report
    assert "🔴 Tình hình Iran\n• diễn biến" in report


async def test_press_report_without_pinned_is_digest_only():
    with patch.object(bot.voz, "fetch_headlines", new=AsyncMock(return_value=[])), \
         patch.object(bot.analyzer, "press_digest", new=AsyncMock(return_value="điểm báo")), \
         patch.object(bot.voz, "fetch_pinned_news_threads", new=AsyncMock(return_value=[])):
        report = await bot.build_press_report()
    assert report == "điểm báo"


async def test_press_report_skips_failed_megathread():
    with patch.object(bot.voz, "fetch_headlines", new=AsyncMock(return_value=[])), \
         patch.object(bot.analyzer, "press_digest", new=AsyncMock(return_value="điểm báo")), \
         patch.object(bot.voz, "fetch_pinned_news_threads", new=AsyncMock(return_value=[_pinned()])), \
         patch.object(bot.voz, "fetch_thread", new=AsyncMock(return_value=None)):
        report = await bot.build_press_report()
    assert report == "điểm báo"


async def test_press_report_skips_analysis_failed_update():
    thread = voz.Thread(title="T", url="https://voz.vn/t/iran.222/", posts=[voz.Post("a", "b")])
    with patch.object(bot.voz, "fetch_headlines", new=AsyncMock(return_value=[])), \
         patch.object(bot.analyzer, "press_digest", new=AsyncMock(return_value="điểm báo")), \
         patch.object(bot.voz, "fetch_pinned_news_threads", new=AsyncMock(return_value=[_pinned()])), \
         patch.object(bot.voz, "fetch_thread", new=AsyncMock(return_value=thread)), \
         patch.object(bot.analyzer, "megathread_update",
                      new=AsyncMock(return_value=analyzer.ANALYSIS_FAILED_REPLY)):
        report = await bot.build_press_report()
    assert report == "điểm báo"
```

Replace `test_cmd_paper_replies_with_digest` with:

```python
async def test_cmd_paper_replies_with_digest():
    msg = _mock_msg()
    with patch.object(bot, "build_press_report", new=AsyncMock(return_value="điểm báo")):
        await bot.cmd_paper(msg)
    all_texts = [c[0][0] for c in msg.answer.call_args_list]
    assert any("điểm báo" in t for t in all_texts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_digests.py -q -k "press_report or cmd_paper"`
Expected: FAIL — `AttributeError: module 'bot' has no attribute 'build_press_report'`

- [ ] **Step 3: Implement**

In `bot.py`, replace `cmd_paper` with:

```python
async def build_press_report() -> str:
    """Điểm báo digest plus a short update per pinned news megathread."""
    headlines = await voz.fetch_headlines()
    parts = [await analyzer.press_digest(headlines)]
    for pinned in await voz.fetch_pinned_news_threads():
        thread = await voz.fetch_thread(pinned.url, max_posts=40)
        if thread is None or not thread.posts:
            continue
        update = await analyzer.megathread_update(thread)
        if update and update != analyzer.ANALYSIS_FAILED_REPLY:
            parts.append(f"🔴 {pinned.title}\n{update}")
    return "\n\n".join(parts)


@router.message(Command("paper"))
async def cmd_paper(message: TgMessage) -> None:
    await message.answer("📰 Đang soạn điểm báo từ voz (f/Điểm báo)… (~30s)")
    result = await build_press_report()
    await _reply_analysis(message, result)
```

In `main.py`, change the import line and `press_job`:

```python
from bot import build_dispatcher, build_press_report, send_to_owner, setup_bot_commands
```

```python
    async def press_job() -> None:
        text = await build_press_report()
        await send_to_owner(bot, f"📰 Điểm báo sáng (voz)\n\n{text}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py main.py tests/test_digests.py
git commit -m "feat(paper): append pinned megathread updates to the press report"
```

---

### Task 4: Docs + live smoke test

**Files:**
- Modify: `CLAUDE.md` (Scheduled digests paragraph)

- [ ] **Step 1: Update CLAUDE.md** — in the **Scheduled digests** paragraph, after the sentence describing `voz.py` fetching, add:

```markdown
/paper additionally crawls the forum's pinned news megathreads (sticky block on the forum page; meta stickies like "Nội quy"/"Report" filtered by an anchored title regex) and appends a Vietnamese `megathread_update` section per thread (max 2) via `bot.build_press_report`.
```

- [ ] **Step 2: Run the full suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 3: Live smoke test of the parser (network, no Gemini)**

Run:
```bash
.venv/bin/python3 - <<'EOF'
import asyncio, voz
pinned = asyncio.run(voz.fetch_pinned_news_threads())
print([f"{p.title[:40]} -> {p.url}" for p in pinned])
EOF
```
Expected: the Iran megathread appears; "Report F33" and "Nội quy box Điểm báo" do not.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: /paper pinned megathread updates"
```
