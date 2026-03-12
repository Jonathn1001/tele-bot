# Factcheck + PostgreSQL Archive Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `/trends` and `/entities`, add `/factcheck <claim>` with Gemini Google Search grounding, and archive every live message to Aiven PostgreSQL.

**Architecture:** Two independent changes — (1) bot command refactor in `analyzer.py` and `bot.py`, (2) a new `db.py` module wired into `crawler.py` and `main.py` for background archival. The in-memory buffer is unchanged and remains the sole source for all analysis commands.

**Tech Stack:** Python 3.12, aiogram 3.x, google-genai SDK, asyncpg, Aiven PostgreSQL (SSL required)

**Note:** A test suite exists at `tests/` using pytest + pytest-asyncio (auto mode). Tests must pass after each task. Run with: `python -m pytest` from the project root (requires `pip install -r requirements-dev.txt` first).

---

## Chunk 1: /factcheck Command

### Task 1: Update `analyzer.py` and `tests/test_analyzer.py`

**Files:**
- Modify: `analyzer.py`
- Modify: `tests/test_analyzer.py`

- [ ] **Step 1: Remove `analyze_trends` and `extract_entities` from `analyzer.py`**

Delete lines 47–61 of `analyzer.py` (both functions). The file should end after `assess_threat`.

- [ ] **Step 2: Add `fact_check` function to `analyzer.py`**

Append to `analyzer.py` after `assess_threat`:

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

**Why not `_ask`:** `_ask` uses `thinking_budget=0` which is incompatible with grounding tools. `fact_check` calls `_client` directly — same pattern as `_ask` internally. No new imports needed (`asyncio`, `_client`, `types`, `_format_messages` are all already in scope).

- [ ] **Step 3: Update `tests/test_analyzer.py`**

Remove these test functions (they test the deleted functions):
- `test_analyze_trends_returns_model_text`
- `test_extract_entities_returns_model_text`
- `test_analyze_trends_failure_returns_error_string`
- `test_extract_entities_failure_returns_error_string`

Add these new tests after `test_assess_threat_failure_returns_error_string`:

```python
async def test_fact_check_returns_model_text():
    msgs = _make_msgs("Event A", "Event B")
    with patch.object(analyzer, "_client", _mock_client("SUPPORTED\nEvidence found.")):
        result = await analyzer.fact_check("Russia attacked Ukraine", msgs)
    assert result == "SUPPORTED\nEvidence found."


async def test_fact_check_failure_returns_error_string():
    msgs = _make_msgs("msg")
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API error")
    with patch.object(analyzer, "_client", mock_client):
        result = await analyzer.fact_check("some claim", msgs)
    assert result.startswith("Analysis failed:")


async def test_fact_check_calls_generate_content_with_search_tool():
    msgs = _make_msgs("msg")
    mock_client = _mock_client("SUPPORTED\nok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.fact_check("some claim", msgs)
    call_kwargs = mock_client.models.generate_content.call_args[1]
    tools = call_kwargs["config"].tools
    assert len(tools) == 1
    assert tools[0].google_search is not None
```

- [ ] **Step 4: Run tests to verify**

```bash
python -m pytest tests/test_analyzer.py -v
```

Expected: all tests pass. The three new `fact_check` tests should pass; the old `trends`/`entities` tests are gone.

- [ ] **Step 5: Commit**

```bash
git add analyzer.py tests/test_analyzer.py
git commit -m "feat: replace trends/entities with fact_check using Gemini Search grounding"
```

---

### Task 2: Update `bot.py`

**Files:**
- Modify: `bot.py`

- [ ] **Step 1: Update the aiogram.filters import**

Change line 3 from:
```python
from aiogram.filters import Command
```
to:
```python
from aiogram.filters import Command, CommandObject
```

- [ ] **Step 2: Add `MAX_CLAIM_LENGTH` constant**

After line 11 (`_buffer: MessageBuffer | None = None`), add:
```python
MAX_CLAIM_LENGTH = 500
```

- [ ] **Step 3: Update `/start` help text**

In `cmd_start`, replace the `/trends` and `/entities` lines in the help string with:
```
/factcheck <claim> — Verify a claim against channel messages + web sources\n
```

The full updated answer string should be:
```python
        "*Telegram Intel Bot*\n\n"
        "I monitor political and military news channels and provide AI-powered analysis.\n\n"
        "Commands:\n"
        "/summary — Key events from recent messages\n"
        "/factcheck <claim> — Verify a claim against channel messages + web sources\n"
        "/threat — Conflict risk assessment\n"
        "/channels — Monitored channels status",
        parse_mode=ParseMode.MARKDOWN,
```

- [ ] **Step 4: Remove `cmd_trends` handler**

Delete the entire `cmd_trends` function. Identify it by the `@router.message(Command("trends"))` decorator — currently at lines 70–78 in the original file.

- [ ] **Step 5: Remove `cmd_entities` handler**

Delete the entire `cmd_entities` function. Identify it by the `@router.message(Command("entities"))` decorator — currently at lines 81–89 in the original file. After Step 4's deletion the line numbers will have shifted; use the decorator to locate it, not line numbers.

- [ ] **Step 6: Add `cmd_factcheck` handler**

Append after `cmd_threat`:

```python
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

- [ ] **Step 7: Verify `bot.py` looks correct**

Confirm:
- `from aiogram.filters import Command, CommandObject` on line 3
- `MAX_CLAIM_LENGTH = 500` present after `_buffer` declaration
- `/start` text has `/factcheck` but no `/trends` or `/entities`
- `cmd_trends` and `cmd_entities` are gone
- `cmd_factcheck` is present and uses `command: CommandObject`

- [ ] **Step 8: Update `tests/test_commands.py`**

The existing test file has `cmd_trends` and `cmd_entities` in two `@pytest.mark.parametrize` lists — remove them. Add new `cmd_factcheck` tests.

**Remove** `bot.cmd_trends` and `bot.cmd_entities` from the parametrize decorators (lines 72–77 and 89–94). After removal, the two parametrize lists should only have `bot.cmd_summary` and `bot.cmd_threat`.

**Add** these tests after the existing parametrize tests:

```python
# ---------------------------------------------------------------------------
# /factcheck
# ---------------------------------------------------------------------------

async def test_factcheck_no_claim_returns_usage():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = None
    buf = _make_buffer("some message")
    with patch.object(bot, "_buffer", buf):
        await bot.cmd_factcheck(msg, cmd)
    msg.answer.assert_called_once_with("Usage: /factcheck <your claim>")


async def test_factcheck_claim_too_long_returns_error():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = "x" * 501
    buf = _make_buffer("some message")
    with patch.object(bot, "_buffer", buf):
        await bot.cmd_factcheck(msg, cmd)
    text = msg.answer.call_args[0][0]
    assert "too long" in text.lower()


async def test_factcheck_empty_buffer_returns_no_messages():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = "Russia attacked Ukraine"
    with patch.object(bot, "_buffer", None):
        await bot.cmd_factcheck(msg, cmd)
    msg.answer.assert_called_once_with("No messages collected yet. Please wait a moment.")


async def test_factcheck_calls_analyzer_and_replies():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = "Russia attacked Ukraine"
    buf = _make_buffer("test message")
    mock_fn = AsyncMock(return_value="SUPPORTED\nEvidence.")
    with patch.object(bot, "_buffer", buf), \
         patch("analyzer.fact_check", new=mock_fn):
        await bot.cmd_factcheck(msg, cmd)
    mock_fn.assert_called_once()
    all_texts = [c[0][0] for c in msg.answer.call_args_list]
    assert any("SUPPORTED" in t for t in all_texts)
```

- [ ] **Step 9: Run tests to verify**

```bash
python -m pytest tests/test_commands.py -v
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add bot.py tests/test_commands.py
git commit -m "feat: add /factcheck handler, remove /trends and /entities"
```

---

### Task 3: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update Bot Commands table**

In the Bot Commands table, remove the `/trends` and `/entities` rows and add `/factcheck`:

```markdown
| `/factcheck <claim>` | Cross-check a claim against channel messages + Google Search |
```

Final table should have these rows: `/start`, `/channels`, `/summary`, `/factcheck`, `/threat`.

- [ ] **Step 2: Update Architecture section**

In the Architecture section, find the sentence:
```
**`analyzer.py`:** All four analysis commands call a private `_ask()` helper...
```
Replace with:
```
**`analyzer.py`:** Analysis commands call a private `_ask()` helper that formats buffered messages into a timestamped block and sends it with a command-specific system prompt to Gemini 2.5 Flash. The `/factcheck` command calls `_client` directly to enable Google Search grounding, which is incompatible with `_ask`'s `thinking_budget=0` config.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md — remove /trends /entities, add /factcheck"
```

---

## Chunk 2: PostgreSQL Archive

### Task 4: Create `db.py`

**Files:**
- Create: `db.py`

- [ ] **Step 1: Create `db.py`**

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

**Key notes:**
- `ssl="require"` is hardcoded — Aiven always requires SSL
- `insert_message` re-attaches UTC tzinfo before insert because asyncpg rejects naive datetimes for `TIMESTAMPTZ` columns
- `make_interval(days => $1)` is required — `INTERVAL '$1 days'` is not valid parameterized SQL in asyncpg

- [ ] **Step 2: Commit**

```bash
git add db.py
git commit -m "feat: add db.py with asyncpg pool init, insert, and prune"
```

---

### Task 5: Update `config.py`

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add DB config vars to `config.py`**

Append to `config.py` after `MAX_CONTEXT_MESSAGES`:

```python

DATABASE_URL = os.environ["DATABASE_URL"]
RETENTION_DAYS = max(1, int(os.environ.get("RETENTION_DAYS", "30")))        # minimum 1 day
PRUNE_INTERVAL_HOURS = max(1, int(os.environ.get("PRUNE_INTERVAL_HOURS", "24")))  # minimum 1 hour
```

`DATABASE_URL` uses `os.environ["DATABASE_URL"]` (no default) — bot fails at startup with `KeyError` if missing, same as other required vars.

- [ ] **Step 2: Add `DATABASE_URL` to test env setup**

`test_analyzer.py` and `test_commands.py` both import modules that transitively import `config.py`. Adding `DATABASE_URL` as a required env var will cause those imports to raise `KeyError` unless the tests also set it.

In `tests/test_analyzer.py`, add this line to the env setup block at the top (after the other `setdefault` calls):
```python
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
```

In `tests/test_commands.py`, add the same line to its env setup block.

- [ ] **Step 3: Run all tests to verify**

```bash
python -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add config.py tests/test_analyzer.py tests/test_commands.py
git commit -m "feat: add DATABASE_URL, RETENTION_DAYS, PRUNE_INTERVAL_HOURS to config"
```

---

### Task 6: Update `crawler.py`

**Files:**
- Modify: `crawler.py`

- [ ] **Step 1: Add imports**

Add at the top of `crawler.py` (after existing imports):
```python
import asyncio
import db
```

- [ ] **Step 2: Update `__init__` signature**

Change `__init__` from:
```python
    def __init__(self, buffer: MessageBuffer) -> None:
        self._buffer = buffer
```
to:
```python
    def __init__(self, buffer: MessageBuffer, pool: "asyncpg.Pool") -> None:
        self._buffer = buffer
        self._pool = pool
```

The string annotation `"asyncpg.Pool"` avoids importing asyncpg directly in `crawler.py`.

- [ ] **Step 3: Add fire-and-forget DB insert in live handler**

In the `handler` coroutine inside `start()`, after `self._buffer.add(channel_name, msg)`:

```python
            asyncio.create_task(db.insert_message(self._pool, msg)).add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )
```

**Important:** Add this only in the live `handler`, NOT in `_backfill`. Backfill replays old messages on every restart and would create duplicate rows.

The `add_done_callback` retrieves and discards any exception, preventing CPython's `Task exception was never retrieved` stderr noise. DB inserts are best-effort — failures are silently discarded.

- [ ] **Step 4: Verify `crawler.py`**

Confirm:
- `import asyncio` and `import db` are at the top
- `__init__` accepts `pool` as second positional arg, stored as `self._pool`
- `asyncio.create_task(...)` is in the live handler only, not in `_backfill`

- [ ] **Step 5: Commit**

```bash
git add crawler.py
git commit -m "feat: archive live messages to PostgreSQL via fire-and-forget task"
```

---

### Task 7: Update `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add `import db`**

Add `import db` after the existing imports in `main.py`.

- [ ] **Step 2: Init pool and pass to crawler**

At the start of `async def main()`, before `buffer = MessageBuffer(...)`:
```python
    pool = await db.init_pool(config.DATABASE_URL)
```

Change:
```python
    crawler = TelegramCrawler(buffer)
```
to:
```python
    crawler = TelegramCrawler(buffer, pool)
```

- [ ] **Step 3: Add pruner task**

Define the pruner coroutine and add it to `asyncio.gather`. Replace:
```python
    await asyncio.gather(
        crawler.start(config.CHANNELS),
        dp.start_polling(bot),
    )
```
with:
```python
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

The pruner sleeps first, so no deletion occurs on the first startup cycle.

- [ ] **Step 4: Verify `main.py`**

The full `main()` function should:
1. `pool = await db.init_pool(config.DATABASE_URL)` — first line
2. Create buffer, crawler (with pool), bot, dispatcher
3. Define and gather `pruner()` alongside the crawler and bot tasks

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: init DB pool at startup, wire pruner task into asyncio.gather"
```

---

### Task 8: Update `requirements.txt` and `.env.example`

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example` (already exists — update it)

- [ ] **Step 1: Add asyncpg to `requirements.txt`**

Append to `requirements.txt`:
```
asyncpg>=0.29
```

- [ ] **Step 2: Update `.env.example`**

Add the three new DB env vars to the existing `.env.example`. Append at the end:

```
# Aiven PostgreSQL connection string
DATABASE_URL=postgresql://user:pass@host:port/dbname?sslmode=require

# Optional: archive retention
RETENTION_DAYS=30
PRUNE_INTERVAL_HOURS=24
```

- [ ] **Step 3: Update CLAUDE.md Configuration table**

Add the three new env var rows to the Configuration table in `CLAUDE.md`:

```markdown
| `DATABASE_URL` | Yes | — | Aiven PostgreSQL connection string |
| `RETENTION_DAYS` | No | `30` | Days to keep archived messages (min 1) |
| `PRUNE_INTERVAL_HOURS` | No | `24` | How often to run pruner in hours (min 1) |
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt .env.example CLAUDE.md
git commit -m "chore: add asyncpg dependency, create .env.example, update CLAUDE.md config table"
```

---

## Post-implementation Checklist

- [ ] Install new dependency: `pip install asyncpg` (or `pip install -r requirements.txt`)
- [ ] Set `DATABASE_URL` in `.env` with your Aiven connection string
- [ ] Run `python main.py` and confirm startup without errors (DB table created on first run)
- [ ] Test `/factcheck Russia launched missiles at Kyiv` — should return SUPPORTED/CONTRADICTED/INSUFFICIENT EVIDENCE with external sources cited
- [ ] Update BotFather command list via `/setcommands` — remove `/trends` and `/entities`, add `/factcheck`
