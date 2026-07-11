# /paper pinned-thread megathread updates — design

**Date:** 2026-07-11
**Status:** approved

## Goal

The f/Điểm báo RSS feed only carries newly created threads, so /paper never
sees the pinned rolling-news megathreads (today: "Tình hình Iran và các bên
liên quan"), where fresh developments land as comments. /paper should crawl
the pinned news threads and append a short update section per thread.

## Findings (2026-07-11)

- Pinned threads live in a `.structItemContainer-group--sticky` block on
  `https://voz.vn/f/diem-bao.33/`; each is a `.structItem--thread` with the
  title/link under `.structItem-title a[href*='/t/']` (relative href).
- Currently 3 pinned: "Report F33" (meta), "Tình hình Iran và các bên liên
  quan" (news megathread), "Nội quy box Điểm báo" (meta).

## Design

### 1. voz.py — pinned thread discovery

```python
@dataclass
class PinnedThread:
    title: str
    url: str      # canonical "https://voz.vn/t/<slug>.<id>/"
```

`fetch_pinned_news_threads(limit: int = 2) -> list[PinnedThread]`:
- GET the forum page with the existing curl_cffi Chrome impersonation
  (`_fetch_page_sync`), in `asyncio.to_thread`.
- Parse `.structItemContainer-group--sticky .structItem--thread`; take the
  title text and href, absolutize (`https://voz.vn` + href), canonicalize via
  `normalize_thread_url` — items that don't normalize are skipped.
- Drop meta stickies: title matching `META_STICKY_RE = re.compile(r"nội quy|report", re.IGNORECASE)`.
- Cap at `limit` (default 2) to bound Gemini cost.
- Fail-soft like `fetch_headlines`: any exception → log + return `[]`.
- Pure parsing goes in a separate `parse_pinned_threads(html_text) -> list[PinnedThread]`
  so it's testable from a fixture without network.

### 2. analyzer.py — megathread update

`megathread_update(thread: Thread) -> str`:
- Same `_ask(...)`/`raw_contents` pattern as `thread_summary`, over the same
  `<thread_posts>` delimited block (untrusted-data notice already covers it).
- Prompt: news-update briefing — "what are the latest developments commenters
  are reporting/discussing", NOT sentiment analysis (that's /thread's job).
  Vietnamese only (`"Chỉ trả lời bằng tiếng Việt."`), concise (≤ 8 bullet
  lines), plain-text format instruction.
- Empty `thread.posts` → return `""` (section skipped by the composer).

### 3. Composition — bot.build_press_report()

`async def build_press_report() -> str` in bot.py:

```
headlines = await voz.fetch_headlines()
parts = [await analyzer.press_digest(headlines)]
for pinned in await voz.fetch_pinned_news_threads():
    thread = await voz.fetch_thread(pinned.url, max_posts=40)
    if thread is None or not thread.posts:
        continue
    update = await analyzer.megathread_update(thread)
    if update:
        parts.append(f"🔴 {pinned.title}\n{update}")
return "\n\n".join(parts)
```

- `cmd_paper` calls it (keeps its status message first).
- main.py `press_job` calls it instead of duplicating the
  fetch_headlines + press_digest pair (still prepends the push header).
- Any megathread failure only loses that section — the RSS digest still ships.

### 4. Tests

- `parse_pinned_threads`: fixture HTML with a sticky group (2 news + 1 "Nội
  quy" + 1 "Report") and a normal thread list → returns only news stickies,
  absolute canonical URLs, normal threads ignored.
- Meta filter case-insensitivity ("NỘI QUY", "Report F33").
- `fetch_pinned_news_threads` returns [] on fetch error.
- `megathread_update`: prompt is Vietnamese-only (no 'Tiếng Việt:' section
  labels), posts go in `<thread_posts>` raw_contents, empty posts → "".
- `build_press_report`: with a pinned thread → digest + 🔴 section; pinned
  list empty → digest only; fetch_thread None → section skipped;
  megathread_update "" → section skipped.
- `cmd_paper` and `press_job` still send/push (existing tests keep passing,
  updated to mock `build_press_report` where they mocked the pair).

## Out of scope

- Summarizing more than 2 megathreads per digest.
- Caching / dedup of megathread updates between the scheduled push and /paper.
- Changing /thread behavior.
