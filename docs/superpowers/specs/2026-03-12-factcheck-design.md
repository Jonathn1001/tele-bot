# Design: Remove /trends & /entities, Add /factcheck + PostgreSQL Archive

**Date:** 2026-03-12
**Status:** Approved

## Overview

Two changes bundled together:

1. Remove `/trends` and `/entities` commands. Add `/factcheck <claim>` — users submit a specific claim and Gemini validates it by cross-referencing both buffered channel messages and live Google Search results (via Gemini's built-in grounding feature).
2. Add PostgreSQL persistence (Aiven) as an archive. Every incoming live message is written to the DB. The in-memory buffer is unchanged and still the sole source for analysis commands. A background pruner task deletes rows older than a configurable retention period.

## Scope

Eight files are modified. One new file is created.

| File | Change |
|---|---|
| `analyzer.py` | Remove `analyze_trends()` and `extract_entities()`. Add `fact_check(claim, messages)`. |
| `bot.py` | Remove `/trends` and `/entities` handlers. Add `/factcheck` handler. Update `/start` help text. Change `from aiogram.filters import Command` to `from aiogram.filters import Command, CommandObject`. |
| `config.py` | Add `DATABASE_URL`, `RETENTION_DAYS`, `PRUNE_INTERVAL_HOURS`. |
| `crawler.py` | Accept `pool` in `__init__`. Fire-and-forget `db.insert_message` on each live message. |
| `main.py` | Init DB pool at startup. Pass pool to crawler. Add pruner task to `asyncio.gather()`. |
| `CLAUDE.md` | Update Bot Commands and Configuration tables. |
| `db.py` *(new)* | `init_pool`, `insert_message`, `prune_old_messages`. |
| `requirements.txt` | Add `asyncpg`. |
| `.env.example` | Add three new env var lines. |

## analyzer.py

Remove:
- `analyze_trends(messages)` — no longer needed
- `extract_entities(messages)` — no longer needed

Add:

```python
async def fact_check(claim: str, messages: list[Message]) -> str:
    context = _format_messages(messages)
    prompt = (
        f"You are an intelligence analyst. A user has submitted this claim for fact-checking:\n\n"
        f'"{claim}"\n\n'
        "Cross-reference this claim using BOTH the Telegram channel messages below AND "
        "your Google Search grounding to find current, authoritative information.\n\n"
        "Start your response with one of: SUPPORTED / CONTRADICTED / INSUFFICIENT EVIDENCE. "
        "Then provide a 2-3 sentence explanation citing both channel evidence (channel + timestamp) "
        "and external sources where relevant.\n\n"
        f"Channel messages:\n\n{context}"
    )
    try:
        response = await asyncio.to_thread(
            _client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        return response.text
    except Exception as exc:
        return f"Analysis failed: {exc}"
```

Notes:
- `fact_check` does **not** use `_ask` — `_ask` does not support tools. `fact_check` calls `_client` directly, following the same pattern as `_ask` internally.
- `thinking_budget=0` is omitted for `fact_check` — grounding + thinking is incompatible with `thinking_budget=0` in the Gemini API. The grounding tool requires the default thinking config.
- `_format_messages` is reused from the same module — no duplication.
- `types.Tool` and `types.GoogleSearch` are already available via the existing `from google.genai import types` import. No new imports needed.

## bot.py

Remove:
- `cmd_trends` handler (`/trends`)
- `cmd_entities` handler (`/entities`)

Add:

Place `MAX_CLAIM_LENGTH` at the top of the module, after the `_buffer` global variable declaration.

```python
MAX_CLAIM_LENGTH = 500

@router.message(Command("factcheck"))
async def cmd_factcheck(message: TgMessage, command: CommandObject) -> None:
    claim = (command.args or "").strip()
    if not claim:
        await message.answer("Usage: /factcheck <your claim>")
        return
    if len(claim) > MAX_CLAIM_LENGTH:
        await message.answer(f"Claim too long. Please keep it under {MAX_CLAIM_LENGTH} characters.")
        return
    if _buffer is None or _buffer.is_empty():
        await message.answer("No messages collected yet. Please wait a moment.")
        return
    await message.answer("Analyzing...")
    msgs = _buffer.get_all(limit=config.MAX_CONTEXT_MESSAGES)
    result = await analyzer.fact_check(claim, msgs)
    await _reply_analysis(message, result)
```

Notes:
- `CommandObject` is used for argument extraction. Change the existing `from aiogram.filters import Command` import to `from aiogram.filters import Command, CommandObject`. This correctly handles group-chat suffixes like `/factcheck@BotUsername <claim>` which plain string splitting would not.
- The in-progress message is `"Analyzing..."` — consistent with all other command handlers.
- Claims longer than 500 characters are rejected before a Gemini call is made. `MAX_CLAIM_LENGTH = 500` is intentionally hardcoded as a module-level constant in `bot.py` (not in `config.py`) — it is a validation guard specific to the bot layer, not a tunable runtime parameter like buffer sizes.
- **Prompt injection:** The user-supplied claim is embedded directly into the Gemini prompt. This is an accepted risk for a personal bot with no sensitive data exposure. No sanitization is implemented.

Update `/start` help text — replace the `/trends` and `/entities` lines with:
```
/factcheck <claim> — Verify a claim against channel messages + web sources
```
The existing `parse_mode=ParseMode.MARKDOWN` kwarg on the `/start` `message.answer()` call must be preserved.

## Post-deployment

After deploying, update the bot's command list via BotFather (`/setcommands`) to remove `/trends` and `/entities` and add `/factcheck`. Until this is done, Telegram clients will still suggest the removed commands in the autocomplete UI.

## Output Format

Gemini responds with one of three verdicts on the first line:
- `SUPPORTED`
- `CONTRADICTED`
- `INSUFFICIENT EVIDENCE`

Followed by a 2-3 sentence explanation and, where relevant, quoted evidence (channel + timestamp).

## Error Handling

| Condition | Response |
|---|---|
| No claim provided | Usage hint; no Gemini call |
| Claim > 500 chars | Length error message; no Gemini call |
| Empty buffer | Standard "no messages" message; no Gemini call |
| Gemini failure | Existing `_ask()` error handling returns `"Analysis failed: <exc>"` |

## Key Constraints (fact-check)

- Fact-checking cross-references **both** buffered channel messages and live Google Search results via Gemini's built-in grounding
- Google Search grounding is enabled via `types.Tool(google_search=types.GoogleSearch())` — no extra API key or dependency required
- `thinking_budget=0` is **not** set for `fact_check` — grounding is incompatible with disabled thinking in the Gemini API
- `CommandObject` is already part of aiogram — no new dependency for this feature

---

## PostgreSQL Archive

### Purpose

Archive-only: every live incoming message is written to PostgreSQL. The in-memory buffer is unchanged. Analysis commands (`/summary`, `/threat`, `/factcheck`) continue to read exclusively from the buffer. The DB is not queried by any bot command.

### New file: `db.py`

```python
import asyncpg
from buffer import Message

async def init_pool(dsn: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn, ssl="require")
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         SERIAL PRIMARY KEY,
                channel    TEXT        NOT NULL,
                sender     TEXT,
                text       TEXT        NOT NULL,
                date       TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    return pool

async def insert_message(pool: asyncpg.Pool, msg: Message) -> None:
    from datetime import timezone
    date = msg.date.replace(tzinfo=timezone.utc) if msg.date.tzinfo is None else msg.date
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages (channel, sender, text, date) VALUES ($1, $2, $3, $4)",
            msg.channel, msg.sender, msg.text, date,
        )

async def prune_old_messages(pool: asyncpg.Pool, retention_days: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM messages WHERE created_at < NOW() - make_interval(days => $1)",
            retention_days,
        )
```

Note: `INTERVAL '$1 days'` is not valid parameterized SQL in asyncpg. Use `make_interval(days => $1)` instead.

### Timezone handling

`crawler.py` strips timezone info from message dates (`event.message.date.replace(tzinfo=None)`). asyncpg's binary protocol rejects naive datetimes for `TIMESTAMPTZ` columns with a `ValueError`. To handle this, `insert_message` in `db.py` re-attaches UTC before inserting (`msg.date.replace(tzinfo=timezone.utc)`). `crawler.py` is not changed — the buffer continues to store naive datetimes as before.

### `config.py` additions

```python
DATABASE_URL = os.environ["DATABASE_URL"]
RETENTION_DAYS = max(1, int(os.environ.get("RETENTION_DAYS", "30")))        # minimum 1 day
PRUNE_INTERVAL_HOURS = max(1, int(os.environ.get("PRUNE_INTERVAL_HOURS", "24")))  # minimum 1 hour
```

`DATABASE_URL` is required (no default) — the bot will fail at startup if missing, consistent with how other required vars are handled.

### `crawler.py` changes

`TelegramCrawler.__init__` gains `pool` as a second positional parameter stored as `self._pool`. Use a string annotation to avoid importing asyncpg in crawler.py: `pool: "asyncpg.Pool"`. Import both `asyncio` and `db` at the top of `crawler.py`.

In the live message handler only (not `_backfill`), after `self._buffer.add()`:
```python
asyncio.create_task(db.insert_message(self._pool, msg)).add_done_callback(
    lambda t: t.exception() if not t.cancelled() else None
)
```

The `add_done_callback` retrieves and discards the exception, silencing CPython's `Task exception was never retrieved` stderr warning. DB insert failures remain best-effort with no retry.

`_backfill` does **not** write to the DB — backfill replays historical messages on every restart, which would produce duplicate rows. Only new live messages are archived.

### `main.py` changes

```python
import db

async def main() -> None:
    pool = await db.init_pool(config.DATABASE_URL)
    buffer = MessageBuffer(maxsize=config.BUFFER_SIZE)
    crawler = TelegramCrawler(buffer, pool)
    ...

    async def pruner() -> None:
        while True:
            await asyncio.sleep(config.PRUNE_INTERVAL_HOURS * 3600)
            try:
                await db.prune_old_messages(pool, config.RETENTION_DAYS)
            except Exception as exc:
                print(f"Pruner: error during prune: {exc}")

    await asyncio.gather(
        crawler.start(config.CHANNELS),
        dp.start_polling(bot),
        pruner(),
    )
```

The pruner sleeps first, then prunes — so no deletion happens on the first startup cycle.

### `.env.example` additions

Append to the existing file:

```
DATABASE_URL=postgresql://user:pass@host:port/dbname?sslmode=require
RETENTION_DAYS=30
PRUNE_INTERVAL_HOURS=24
```

### `requirements.txt`

Add `asyncpg` on its own line.

### Error handling

| Condition | Behavior |
|---|---|
| `DATABASE_URL` missing | Bot fails at startup with `KeyError` (same as other required vars) |
| `init_pool` fails (bad DSN, Aiven unreachable) | Exception propagates out of `main()` before `asyncio.gather()` is reached; bot never starts. No retry — fix config and restart. |
| DB insert fails | Best-effort: exception is discarded via `done_callback`; no retry; message is still added to buffer normally |
| DB prune fails | Caught inside `pruner()` loop with `try/except`; error is printed; loop continues; crawler and bot are unaffected |
| Aiven SSL required | `ssl="require"` is hardcoded in `init_pool` — Aiven always requires SSL |
