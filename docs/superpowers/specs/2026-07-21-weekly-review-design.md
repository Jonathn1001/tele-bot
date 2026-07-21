# Weekly Review Digest — Design

**Date:** 2026-07-21
**Status:** Approved (brainstorm)
**Repo:** `telegram-intel-bot` (reuses existing scheduler + Gemini analyzer + owner push)

## Goal

Every Sunday 19:00 (`Asia/Ho_Chi_Minh`), the bot reads the user's current-week
Notion "Weekly To-do List" page, computes a deterministic completion scoreboard,
has Gemini turn it into a written weekly review (recap · insights · next-week focus
· motivation line), and pushes it to the owner via Telegram. A `/weekly` command
runs the same flow on demand.

## Why reuse `telegram-intel-bot`

The bot already provides every non-Notion piece:

- **`analyzer.py`** — Gemini 2.5 Flash client, `_ask()` helper, prompt-injection
  guard (`UNTRUSTED_DATA_NOTICE`), plain-text Telegram formatting instruction.
- **`scheduler.py`** — `run_scheduler(jobs)` fires `(time, name, coro)` jobs at fixed
  `Asia/Ho_Chi_Minh` times; wired as a `gather` task in `main.py`.
- **`bot.py`** — `send_to_owner()`, command router with `OwnerOnlyMiddleware` +
  `RateLimitMiddleware`, `_split()` chunking, `setup_bot_commands()`.

Only the **Notion source** and the **weekly analysis prompt** are new. This mirrors
the existing "one source module per feed" shape (`hn.py`, `voz.py`).

## Notion data model (as observed)

The weekly tasks are **not** a database. Each week is a **page** created by
**duplicating a template under a shared parent page**. Structure of a week page
(`👨‍💻 Weekly To-do List  (July 20 - July 26)`):

- Title carries the **date range**: `Weekly To-do List (<Mon DD> - <Mon DD>)`.
- A habit-goals header block (colored bullet list) — recurring weekly targets.
- A **7-column layout** (`column_list` → 7 × `column`), one per weekday Mon→Sun.
  Each column: a `heading` (day name), a `divider`, then `to_do` blocks with a
  `checked: bool` — these are the task completion signals.
- Trailing quote + long-term "2026 Core Targets" (out of scope; not weekly).

> Note: `📅 Weekly Progress Tracker` (a separate Notion **database** of DSA/LeetCode
> study rows) is **unrelated** to this feature and is not read.

## Architecture

Four touch points. New file `notion.py`; edits to `analyzer.py`, `main.py`,
`bot.py`, `config.py`, `.env.example`, `requirements.txt`, `CLAUDE.md`.

### 1. `notion.py` — new source module

Thin async Notion REST client (new dep `httpx`; `curl_cffi.requests.AsyncSession`
is the zero-new-dep fallback). Auth header `Authorization: Bearer <NOTION_API_KEY>`,
`Notion-Version: 2022-06-28`. Two responsibilities:

**A. Find the current week's page** — `find_current_week_page(today) -> Page | None`
1. `GET /v1/blocks/{NOTION_TODO_PARENT_ID}/children` (paginated) → keep `child_page`
   blocks. The block's title text holds `Weekly To-do List (<range>)`.
2. Parse the date range from each title. Pick the page whose range **contains
   `today`**. Titles without a parseable current range (e.g. the template) are
   skipped. If none contains today, fall back to the most-recently-created match
   and log a warning.

**B. Read the tasks** — `fetch_week(page_id) -> Week`
- Recursively fetch block children (`GET /v1/blocks/{id}/children`, follow
  `has_children`, handle `next_cursor` pagination) to reach the nested
  `column_list → column → to_do` tree.
- Build `Week`:
  ```python
  @dataclass
  class Task:  text: str; checked: bool
  @dataclass
  class Day:   name: str; tasks: list[Task]
  @dataclass
  class Week:  label: str; days: list[Day]; goals: list[str]
  ```
  `label` = page title; `goals` = the header habit-goal bullet texts (plain text,
  colors dropped).

**Failure policy:** any network / parse error → return `None` (find) or raise, caught
by the caller which sends a soft "couldn't read this week's page" notice. Never
crashes the bot — same contract as `voz.py` / `hn.py`.

**SSRF / scope:** the client only ever calls `api.notion.com`; page IDs come from the
configured parent's own children, never from untrusted input.

### 2. `analyzer.py` — `weekly_review(week: Week) -> str`

**Code computes the scoreboard (deterministic — LLMs miscount).** Numbers come from
Python; Gemini only narrates.

- `overall`: total `checked` / total tasks across all days.
- `per_category`: tasks grouped by a normalized label (leading emoji + first word,
  e.g. `🏃 Running`, `🔥 Gym`, `📗 Reading`, `💻 Working`, `🇬🇧 English`, `🥊 Muay`) →
  `done/total` each.
- `per_day`: `checked/total` per weekday.

Build a numbered plain-text scoreboard string, then call the existing `_ask()` with:
- **system prompt:** "You are a personal productivity coach. Given this week's task
  completion scoreboard and the raw per-day checklist, write a short weekly review with
  four labeled sections — Recap, Insights, Next Week, One-liner — where Recap restates
  the key numbers, Insights names 2-3 patterns (categories consistently missed, heavy
  vs light days), Next Week suggests 2-3 concrete priorities from what's still open, and
  One-liner is a single motivating (or bluntly honest) closing line. Respond in English."
  + `PLAIN_TEXT_FORMAT_INSTRUCTION`.
- **contents:** `<weekly_tasks>` block containing the label, scoreboard, per-day items,
  and goals — under the existing `UNTRUSTED_DATA_NOTICE` (task text is user-authored but
  treated strictly as data).

Empty week (0 tasks) → early return a fixed "No tasks found for this week" reply,
mirroring `NO_HN_STORIES_REPLY`.

### 3. `scheduler.py` + `main.py` — Sunday job

Scheduler fires **daily** at each configured time and has no weekday concept. Rather
than change the scheduler, the **job self-guards** (minimal, matches the existing job
style in `main.py`):

```python
async def weekly_review_job() -> None:
    now = datetime.now(VN_TZ)
    if now.weekday() != 6:  # 6 = Sunday
        return
    page = await notion.find_current_week_page(now.date())
    if page is None:
        await send_to_owner(bot, "📝 Weekly review: couldn't find this week's Notion page.")
        return
    week = await notion.fetch_week(page.id)
    text = await analyzer.weekly_review(week)
    await send_to_owner(bot, f"📝 Weekly Review — {week.label}\n\n{text}")
```

Registered in `main.py`'s `jobs` list:
```python
*((t, "weekly_review", weekly_review_job) for t in parse_times(config.WEEKLY_REVIEW_TIME)),
```
`WEEKLY_REVIEW_TIME` defaults to `19:00`; empty string disables (via `parse_times`).

> Alternative considered — extend `Job` with a weekday field. Rejected: touches the
> scheduler core and all existing jobs for a single caller. The self-guard is local.

### 4. `bot.py` — `/weekly` command

On-demand trigger so the flow is testable without waiting for Sunday. The command
runs the fetch + analyze inline (no weekday guard) and replies in-chat via
`_reply_analysis`. Touch points:
- New `@router.message(Command("weekly"))` handler.
- Add `/weekly` to `ANALYSIS_COMMANDS` (it makes a paid Gemini call → rate-limited).
- Add to `BOT_COMMANDS`, `QUICK_KEYBOARD`, and the `/start` help text.

## Configuration (new)

| Var | Required | Default | Description |
|---|---|---|---|
| `NOTION_API_KEY` | Yes | — | Notion internal integration token (secret) |
| `NOTION_TODO_PARENT_ID` | Yes | — | Parent page ID whose child pages are the weekly to-do lists |
| `WEEKLY_REVIEW_TIME` | No | `19:00` | Sunday push time, `Asia/Ho_Chi_Minh`; empty disables |

Added to `config.py`, `.env.example`, and the CLAUDE.md config table + a "Weekly
review" architecture paragraph.

## One-time setup (documented for the user)

1. Create a Notion **internal integration** at notion.so/my-integrations → copy the
   token → `NOTION_API_KEY`.
2. Open the **parent page** that holds the weekly to-do pages → `•••` → *Connections* →
   add the integration. Child pages (new weeks) inherit access.
3. Copy the parent page ID (the 32-hex in its URL) → `NOTION_TODO_PARENT_ID`.
4. Restart the bot (`docker compose up -d --build`).

## Testing

`tests/test_notion.py`:
- Title date-range parser: picks the page containing `today`; skips the template;
  falls back to newest with a warning when none match.
- Block walker: `column_list → column → to_do` yields correct `Day`/`Task` with
  `checked` states; nested pagination followed.
- Soft-fail: network error → `None` / caught, no crash.

`tests/test_analyzer.py`:
- `weekly_review` scoreboard math: overall and per-category `done/total` correct for a
  fixed `Week` fixture; empty week returns the fixed reply. Gemini call mocked.

## Out of scope (YAGNI)

- Reading the `📅 Weekly Progress Tracker` DSA database.
- Writing results back to Notion.
- Multi-week trends / history storage.
- The trailing "2026 Core Targets" long-term list.

## Security notes

- `NOTION_API_KEY` is a secret: `.env` only, never logged (per repo logging rule).
  Errors log status codes / page IDs, never the token.
- Task text is user-authored and low-risk, but still wrapped under
  `UNTRUSTED_DATA_NOTICE` so template/task text can't steer the model.
- Notion client is pinned to `api.notion.com`; page IDs are drawn only from the
  configured parent's children.
