# Weekly Review Digest — Design

**Date:** 2026-07-21
**Status:** Approved (brainstorm)
**Repo:** `telegram-intel-bot` (reuses existing scheduler + Gemini analyzer + owner push)

## Goal

Every Sunday 19:00 (`Asia/Ho_Chi_Minh`), the bot reads the user's current-week
Notion "Weekly To-do List" page, computes a deterministic completion scoreboard,
has Gemini turn it into a written weekly review (recap · insights · next-week focus
· motivation line), and pushes it to the owner via Telegram. **Immediately after the
review, the same job clones the user's Notion template page into next week's fresh
page** (correct date range, checkboxes reset) so it's ready before Monday. `/weekly`
and `/newweek` commands run each half on demand.

## Why reuse `telegram-intel-bot`

The bot already provides every non-Notion piece:

- **`analyzer.py`** — Gemini 2.5 Flash client, `_ask()` helper, prompt-injection
  guard (`UNTRUSTED_DATA_NOTICE`), plain-text Telegram formatting instruction.
- **`scheduler.py`** — `run_scheduler(jobs)` fires `(time, name, coro)` jobs at fixed
  `Asia/Ho_Chi_Minh` times; wired as a `gather` task in `main.py`.
- **`bot.py`** — `send_to_owner()`, command router with `OwnerOnlyMiddleware` +
  `RateLimitMiddleware`, `_split()` chunking, `setup_bot_commands()`.

Only the **Notion read/create client** and the **weekly analysis prompt** are new.
This mirrors the existing "one source module per feed" shape (`hn.py`, `voz.py`) —
extended with a write path (page creation).

## Notion data model (as observed)

The weekly tasks are **not** a database. Each week is a **page** under the parent
**`📅 Weekly To-do Lists`** (`3a435e09628b81758610e824be221ded` — created + populated
during this design; the existing July 20-26 page was moved under it). There is **no
separate template**: the bot seeds next week by **cloning the current week's page**
(the only page today). Structure of a week page
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

New file `notion.py` (read + create); edits to `analyzer.py`, `main.py`, `bot.py`,
`config.py`, `.env.example`, `requirements.txt`, `CLAUDE.md`.

### 1. `notion.py` — new source module

Thin async Notion REST client (new dep `httpx`; `curl_cffi.requests.AsyncSession`
is the zero-new-dep fallback). One `httpx.AsyncClient` per call via
`async with` (created/closed per invocation — no long-lived global). Headers:
`Authorization: Bearer <NOTION_API_KEY>`, `Notion-Version: 2022-06-28` (older but
stable; blocks + children endpoints are unchanged in it). **Network I/O and pure
parsing are split** so parsing is fixture-testable without the network — the house
convention (`paper-pinned-threads-design.md`: pure `parse_pinned_threads(html_text)`).

**Dataclasses:**
```python
@dataclass
class WeekPage: id: str; title: str          # a candidate week page
@dataclass
class Task:     text: str; checked: bool
@dataclass
class Day:      name: str; tasks: list[Task]
@dataclass
class Week:     label: str; days: list[Day]; goals: list[str]
```

**A. Find the current week's page** — `find_current_week_page(today: date) -> WeekPage | None`
1. `GET /v1/blocks/{NOTION_TODO_PARENT_ID}/children` (paginated via `next_cursor`)
   → keep `child_page` blocks; each carries `id` + `child_page.title`.
2. `parse_title_range(title) -> tuple[date, date] | None` (pure) selects candidates:
   - Regex on the range in the title, tolerant of the emoji prefix and extra
     whitespace: `r"\(\s*([A-Za-z]{3,9})\s+(\d{1,2})\s*[-–]\s*([A-Za-z]{3,9})\s+(\d{1,2})\s*\)"`.
   - No year in titles → assume `today.year`. Cross-month handled by parsing each
     month name independently (`July 27 - Aug 2`). **Cross-year:** if computed
     `end < start`, roll `end` to `start.year + 1` (`Dec 29 - Jan 4`).
   - Unparseable (e.g. the template, whose title has no valid range) → `None`, skipped.
3. Pick the candidate whose `[start, end]` **contains `today`**. Fallback when none
   contains today: sort remaining candidates by the block's `created_time`
   (children come in document order, not creation order) and take the newest,
   logging a warning. If there are no candidates at all → `None`.

**B. Read the tasks** — `fetch_week(page_id) -> Week` (network) + `parse_week(blocks) -> Week` (pure)
- `fetch_week` recursively fetches block children (`GET /v1/blocks/{id}/children`,
  follow `has_children`, page `next_cursor`) to materialize the nested
  `column_list → column → to_do` tree, then hands the tree to `parse_week`.
- `parse_week` walks it: each `column` → a `Day` (name from the column's leading
  `heading`), its `to_do` blocks → `Task(text, checked)`. `goals` = the header
  habit-goal bullet texts.
- **Text extraction:** join `rich_text[].plain_text` for each block. Notion **custom
  emoji** (e.g. `:programming:`) do **not** appear in `plain_text`; such items still
  parse (bare text) and fall into the "Other" category bucket (see §2). Standard
  unicode emoji (`🏃`, `🔥`, …) are in `plain_text` and drive grouping.
- `goals` are **context only** — their color-encoded status (green/red) is dropped
  and is **not** counted in the scoreboard (the scoreboard counts only the 7-day
  `to_do` checkboxes).

**C. Create next week's page (clone the current week)** —
`create_next_week(today: date, source_page_id: str) -> str | None` returns the new
page's id (or `None`). **`source_page_id` defaults to the current-week page** (the
Sunday job passes the page it just reviewed); the optional `NOTION_TEMPLATE_PAGE_ID`
overrides it with a fixed template when set.

1. **Compute the target week.** From the Sunday run date, next Monday = `today + 1d`,
   next Sunday = `today + 7d`. Build the title by taking the **source page's own
   title prefix** (everything before its last `(`) and appending
   `f"({start:%B} {start.day} - {end:%B} {end.day})"` → e.g.
   `Weekly To-do List  (July 27 - August 2)`. (`strftime("%-d")` is avoided; use
   `.day` for portability.)
2. **Idempotency guard.** Call `find_current_week_page(next_monday)` first; if a page
   already covers next week, **skip** and log — never create a duplicate (guards
   against a double-fire or a page the user already made).
3. **Read the source page** (`GET /v1/pages/{source_page_id}` for `icon` +
   `GET /v1/blocks/{id}/children` recursively) into a raw block tree.
4. **Transform to a create payload** — pure `to_create_blocks(tree) -> list[dict]`:
   - Drop read-only fields (`id`, `created_time`, `last_edited_time`, `has_children`,
     `parent`); keep `type` + the type-specific object.
   - **Reset every `to_do.checked` to `false`** — the current week's ticks do **not**
     carry into next week; the task *text* does (recurring tasks are the point).
   - Rebuild `rich_text`: keep `text` parts with their `annotations` (colors are
     writable, preserved). **Unsupported mention types (Notion custom emoji like
     `:programming:`) degrade to a plain `text` element from their `plain_text`** —
     accepted minor fidelity loss.
   - Skip block types the API cannot create; log each skipped type.
5. **Create in one request.** `POST /v1/pages` with `parent={page_id: NOTION_TODO_PARENT_ID}`,
   `icon` (copied from source), `properties={title:[...]}`, and `children=[…]`.
   The shape `page → column_list → column → to_do` is **exactly two levels
   of nested children**, within Notion's single-request limits (≤2 nesting levels,
   ≤100 blocks per `children` array, ≤1000 total — verified against
   developers.notion.com). A `column_list` must have ≥2 columns and each `column`
   ≥1 child — satisfied by the 7-day layout.
   - **Robustness guard:** `to_create_blocks` validates the precondition; if the page
     ever exceeds 2 nesting levels or a 100-block array, the overflow is appended in
     follow-up `PATCH /v1/blocks/{id}/children` calls (needs returned ids) rather than
     silently truncated.

**Failure policy:** any network / parse error → `find_current_week_page` returns
`None`; `fetch_week` and `create_next_week` raise, caught by the caller.
`create_next_week` failure is **isolated from the review** — the review is pushed
first, so a create error only costs the new page (soft owner notice), never the
delivered review. Never crashes the bot — same contract as `voz.py` / `hn.py`.

**SSRF / scope:** the client only ever calls `api.notion.com`; page IDs come from the
configured parent's own children, never from untrusted input.

### 2. `analyzer.py` — `weekly_review(week: Week) -> str`

**Code computes the scoreboard (deterministic — LLMs miscount).** Numbers come from
Python; Gemini only narrates.

- `overall`: total `checked` / total tasks across all days.
- `per_category`: tasks grouped by their **leading unicode emoji only** (not
  emoji + first word — that would split `🔥 Chest`, `🔥 Back`, `🔥 Leg` into three
  instead of one `🔥` gym bucket). An explicit emoji→label map names them for the
  output; unmapped-emoji or no-emoji items (incl. custom-emoji like `:programming:`)
  fall into an **`Other`** bucket:
  ```python
  CATEGORY = {"🏃": "Running", "🔥": "Gym", "🥊": "Muay",
              "📗": "Reading", "🇬🇧": "English", "🙏": "Buddhist", "☕": "Coffee",
              "📝": "Review"}   # extend as the template evolves; unknown → "Other"
  ```
  → `done/total` per category.
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
    # 1. Review this week (delivered first — must survive a later create failure).
    page = await notion.find_current_week_page(now.date())
    if page is None:
        await send_to_owner(bot, "📝 Weekly review: couldn't find this week's Notion page.")
    else:
        week = await notion.fetch_week(page.id)
        text = await analyzer.weekly_review(week)
        await send_to_owner(bot, f"📝 Weekly Review — {week.label}\n\n{text}")
    # 2. Clone the reviewed page into next week's page. Isolated from the review.
    #    Needs a source page — skip if this week's page wasn't found.
    if config.AUTOCREATE_ENABLED and page is not None:
        try:
            new_id = await notion.create_next_week(now.date(), source_page_id=page.id)
            if new_id:
                await send_to_owner(bot, "🆕 Next week's to-do page is ready.")
            # new_id None → already existed (idempotency); stay quiet.
        except Exception:
            logger.exception("weekly: create_next_week failed")
            await send_to_owner(bot, "⚠️ Couldn't create next week's page.")
```

Registered in `main.py`'s `jobs` list, gated on `WEEKLY_ENABLED`:
```python
*(
    (t, "weekly_review", weekly_review_job)
    for t in (parse_times(config.WEEKLY_REVIEW_TIME) if config.WEEKLY_ENABLED else [])
),
```
Empty `WEEKLY_REVIEW_TIME` also disables the schedule (via `parse_times`) even when
credentials are set.

> Alternative considered — extend `Job` with a weekday field. Rejected: touches the
> scheduler core and all existing jobs for a single caller. The self-guard is local.

### 4. `bot.py` — `/weekly` and `/newweek` commands

On-demand triggers so each half is testable without waiting for Sunday.

- **`/weekly`** — runs fetch + analyze inline (no weekday guard), replies in-chat via
  `_reply_analysis`. If `not config.WEEKLY_ENABLED`, reply "Weekly review isn't
  configured." Add to `ANALYSIS_COMMANDS` (paid Gemini call → rate-limited).
- **`/newweek`** — calls `notion.create_next_week(today)`; replies with the outcome
  (created / already exists / failed). If `not config.AUTOCREATE_ENABLED`, reply
  "Auto-create isn't configured (set NOTION_TEMPLATE_PAGE_ID)." No Gemini call, so
  **not** in `ANALYSIS_COMMANDS`, but it does write to Notion — keep it owner-only
  (already enforced by `OwnerOnlyMiddleware`).
- Add both to `BOT_COMMANDS`, `QUICK_KEYBOARD`, and the `/start` help text.

## Configuration (new)

| Var | Required | Default | Description |
|---|---|---|---|
| `NOTION_API_KEY` | No | `""` | Notion internal integration token (secret); empty disables the weekly feature |
| `NOTION_TODO_PARENT_ID` | No | `""` | Parent page ID holding the weekly to-do pages (`3a435e09628b81758610e824be221ded`); empty disables |
| `WEEKLY_REVIEW_TIME` | No | `19:00` | Sunday push time, `Asia/Ho_Chi_Minh`; empty disables the schedule |
| `WEEKLY_AUTOCREATE` | No | `true` | `false` disables cloning next week's page (review still runs) |
| `NOTION_TEMPLATE_PAGE_ID` | No | `""` | Optional: clone this fixed page instead of the current week. Empty → clone the current-week page |

**Optional, not required — disable-when-empty.** Read via `os.environ.get(..., "")`,
not `os.environ["..."]`. This matches the codebase's optional-feature pattern
(`CHANNELS`, `ALERT_KEYWORDS`, `HN_DIGEST_TIMES` in `config.py`) and is deliberately
**unlike** the required `OWNER_ID`/`DATABASE_URL`: the weekly review is one add-on,
so a deployed bot missing these must keep booting (HN, press, alerts unaffected). A
single derived flag gates both entry points:
```python
WEEKLY_ENABLED     = bool(NOTION_API_KEY and NOTION_TODO_PARENT_ID)
AUTOCREATE_ENABLED = bool(WEEKLY_ENABLED and WEEKLY_AUTOCREATE)   # WEEKLY_AUTOCREATE parsed as bool, default True
```
- `WEEKLY_ENABLED` false → the scheduled job is **not registered** and `/weekly`
  replies "Weekly review isn't configured." (logged once at startup).
- `AUTOCREATE_ENABLED` false → the Sunday job skips the clone step and `/newweek`
  replies "Auto-create is off." Review still runs when `WEEKLY_ENABLED`. Auto-create
  needs no extra credential — it clones the current-week page found under the parent.

Added to `config.py`, `.env.example`, and the CLAUDE.md config table + a "Weekly
review" architecture paragraph.

## One-time setup (documented for the user)

The parent page `📅 Weekly To-do Lists` (`3a435e09628b81758610e824be221ded`) and the
move of the July 20-26 page under it are **already done**. Remaining, one-time:

1. Create a Notion **internal integration** at notion.so/my-integrations → copy the
   token → `NOTION_API_KEY`.
2. Open `📅 Weekly To-do Lists` → `•••` → *Connections* → add the integration. Every
   weekly page under it (current + future clones) inherits access.
3. Set `NOTION_TODO_PARENT_ID=3a435e09628b81758610e824be221ded`.
4. Restart the bot (`docker compose up -d --build`). Auto-create is on by default; set
   `WEEKLY_AUTOCREATE=false` to keep only the review.

## Testing

`tests/test_notion.py` (pure functions, fixtures — no network):
- `parse_title_range`: in-range title selected; emoji prefix + double space tolerated;
  cross-month (`July 27 - Aug 2`); cross-year roll (`Dec 29 - Jan 4` → end in next
  year); template/no-range title → `None` (skipped).
- `find_current_week_page` selection: candidate containing `today` wins; when none
  contains today, newest by `created_time` is chosen (document-order fixture proves
  it's not just "last in list").
- `parse_week`: `column_list → column → to_do` fixture yields correct `Day`/`Task`
  with `checked` states; custom-emoji item (`:programming:`) parses as bare text;
  goals extracted from the header.
- `to_create_blocks` (pure): read-only fields (`id`, `created_time`, `has_children`,
  `parent`) stripped; every `to_do.checked` forced `false`; colored `annotations`
  preserved; a custom-emoji mention degrades to a `text` element from `plain_text`;
  unsupported block type skipped + logged.
- Next-week title/date computation: from a Sunday date → correct Mon–Sun range and
  title, reusing the source page's prefix; cross-month (`July 27 - August 2`) and
  cross-year (`Dec 28 - Jan 3`) formatted correctly.
- `create_next_week` idempotency: when `find_current_week_page(next_monday)` already
  returns a page → returns `None` and issues **no** `POST` (mock asserts not called).
- Nesting/array precondition: a 2-level source builds a single-request payload; a
  synthetic 3-level or >100-array tree routes overflow to append calls (or is flagged),
  never silently truncated.
- Soft-fail: network error → `find_current_week_page` returns `None`; `fetch_week` /
  `create_next_week` raise and the caller catches — no crash. In the Sunday job, a
  `create_next_week` exception still leaves the review `send_to_owner` call made.
  Pagination (`next_cursor`) followed.

`tests/test_analyzer.py`:
- `weekly_review` scoreboard math: overall and per-category `done/total` correct for a
  fixed `Week` fixture — including that `🔥 Chest`/`🔥 Back`/`🔥 Leg` collapse into a
  single `Gym` bucket and no-emoji items land in `Other`. Empty week returns the fixed
  reply. Gemini call mocked.

## Resolved / open

- **Parent — resolved.** `📅 Weekly To-do Lists` (`3a435e09628b81758610e824be221ded`)
  created and the July 20-26 page moved under it; verified it's a **page** whose child
  is a `child_page`. `find_current_week_page` (parent children → `child_page`) works.
- **Template — resolved.** No dedicated template; the bot clones the **current-week**
  page (checkboxes reset). Optional `NOTION_TEMPLATE_PAGE_ID` override kept for later.
- **Sunday 19:00 undercounts Sunday itself** (open, accepted) — its tasks are likely
  still unchecked at 7pm. Revisit to 22:00 if the recap reads too harsh.
- **Custom-emoji fidelity** (open, accepted) — `:programming:` (workspace custom emoji)
  can't be recreated via the API and degrades to plain text in the clone. To keep it,
  swap that item to a standard unicode emoji in the source page.

## Out of scope (YAGNI)

- Reading the `📅 Weekly Progress Tracker` DSA database.
- Writing the *review text* back into Notion (the bot creates next week's page but
  does not annotate the reviewed week).
- Multi-week trends / history storage.
- Cloning arbitrary >2-level page layouts beyond the documented append fallback.
- The trailing "2026 Core Targets" long-term list (carried by the clone as-is, not
  analyzed).

## Security notes

- `NOTION_API_KEY` is a secret: `.env` only, never logged (per repo logging rule).
  Errors log status codes / page IDs, never the token.
- Task text is user-authored and low-risk, but still wrapped under
  `UNTRUSTED_DATA_NOTICE` so template/task text can't steer the model.
- Notion client is pinned to `api.notion.com`; page IDs are drawn only from the
  configured parent's children.
- **Write scope:** `create_next_week` only ever creates under `NOTION_TODO_PARENT_ID`
  from the configured template — it never edits or deletes existing pages, and the
  integration's Notion permissions bound the blast radius. The idempotency guard
  prevents duplicate pages on a double-fire.
