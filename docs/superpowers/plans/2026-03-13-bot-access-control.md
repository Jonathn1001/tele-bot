# Bot Access Control Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict all bot commands to the owner's Telegram account via `OWNER_ID` env var and aiogram middleware, silently dropping all other users.

**Architecture:** A single `OwnerOnlyMiddleware` class registered at module level on `router` (after the class definition, not inside `build_dispatcher()`) intercepts every incoming message before any handler runs. The owner's numeric Telegram user ID is read from the `OWNER_ID` environment variable at startup.

**Tech Stack:** Python 3.12, aiogram 3.x (`BaseMiddleware`), python-dotenv, pytest with `asyncio_mode = auto` (already configured in `pytest.ini` — no per-test `@pytest.mark.asyncio` decorator needed)

---

## Chunk 1: Config + test setup

### Task 1: Add OWNER_ID to config.py

**Files:**
- Modify: `config.py`
- Modify: `tests/test_commands.py`
- Modify: `tests/test_main_startup.py`

- [ ] **Step 1: Add OWNER_ID to env setup in both test files**

In `tests/test_commands.py`, add to the env setup block at the very top (after the existing `os.environ.setdefault` lines, before any project imports):

```python
os.environ.setdefault("OWNER_ID", "5730878656")
```

In `tests/test_main_startup.py`, add the same line in the same position (after the existing `os.environ.setdefault` lines at the top). Reason: `test_main_startup.py` does not import `config` at module scope, so it won't fail today — but once `config.py` gains a new required var, running this file in isolation would break unless it has `OWNER_ID` in its env setup block. Add it now to keep the file self-sufficient.

- [ ] **Step 2: Add a failing test for OWNER_ID in config**

Add this test at the bottom of `tests/test_commands.py`:

```python
# ---------------------------------------------------------------------------
# config.OWNER_ID
# ---------------------------------------------------------------------------

def test_config_owner_id_is_integer():
    import config
    assert isinstance(config.OWNER_ID, int)
    assert config.OWNER_ID == int(os.environ["OWNER_ID"])
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd /home/elgnas/Projects/Personal/telegram-intel-bot
source .venv/bin/activate
pytest tests/test_commands.py::test_config_owner_id_is_integer -v
```

Expected: `FAILED tests/test_commands.py::test_config_owner_id_is_integer — AttributeError: module 'config' has no attribute 'OWNER_ID'`

Note: The env setup in Step 1 means `config` imports successfully (no `KeyError`), but the attribute does not exist yet — so the test fails at assertion time. This is the correct red state.

- [ ] **Step 4: Add OWNER_ID to config.py**

In `config.py`, add after `GEMINI_API_KEY`:

```python
OWNER_ID = int(os.environ["OWNER_ID"])
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/test_commands.py::test_config_owner_id_is_integer -v
```

Expected: PASS

- [ ] **Step 6: Run all existing tests to confirm nothing is broken**

```bash
pytest tests/ -v
```

Expected: all previously passing tests still PASS

- [ ] **Step 7: Commit**

```bash
git add config.py tests/test_commands.py tests/test_main_startup.py
git commit -m "feat: add OWNER_ID required config var"
```

---

## Chunk 2: OwnerOnlyMiddleware

### Task 2: Implement and test the middleware

**Files:**
- Create: `tests/test_middleware.py`
- Modify: `bot.py`

- [ ] **Step 1: Create tests/test_middleware.py with failing tests**

```python
import os

os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "dummy_hash")
os.environ.setdefault("BOT_TOKEN", "0:AADummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy_key")
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("OWNER_ID", "5730878656")

from unittest.mock import AsyncMock, MagicMock

import config
import bot


def _make_message(user_id: int | None) -> MagicMock:
    """Build a mock aiogram Message with the given from_user.id (or None)."""
    msg = MagicMock()
    if user_id is None:
        msg.from_user = None
    else:
        msg.from_user = MagicMock()
        msg.from_user.id = user_id
    return msg


async def test_owner_message_passes_through():
    """Owner's messages reach the handler."""
    middleware = bot.OwnerOnlyMiddleware()
    handler = AsyncMock()
    msg = _make_message(config.OWNER_ID)
    await middleware(handler, msg, {})
    handler.assert_called_once_with(msg, {})


async def test_stranger_message_is_dropped():
    """Messages from unknown users are silently dropped."""
    middleware = bot.OwnerOnlyMiddleware()
    handler = AsyncMock()
    msg = _make_message(config.OWNER_ID + 1)  # any ID that isn't the owner's
    await middleware(handler, msg, {})
    handler.assert_not_called()


async def test_anonymous_message_is_dropped():
    """Messages with from_user=None (e.g. anonymous channel posts) are silently dropped."""
    middleware = bot.OwnerOnlyMiddleware()
    handler = AsyncMock()
    msg = _make_message(None)
    await middleware(handler, msg, {})
    handler.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_middleware.py -v
```

Expected: FAIL — `AttributeError: module 'bot' has no attribute 'OwnerOnlyMiddleware'`

- [ ] **Step 3: Add OwnerOnlyMiddleware to bot.py**

Add these imports at the top of `bot.py` (alongside the existing aiogram imports):

```python
from collections.abc import Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Any
```

Add the class after the imports, **before** `router = Router()`:

```python
class OwnerOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user is None or event.from_user.id != config.OWNER_ID:
            return
        return await handler(event, data)
```

Then, **after** `router = Router()`, register the middleware at module level:

```python
router.message.middleware(OwnerOnlyMiddleware())
```

Do NOT place this registration inside `build_dispatcher()`. Since `router` is a module-level object, registering inside `build_dispatcher()` would add a duplicate middleware instance every time `build_dispatcher()` is called (e.g., in test setup). Module-level registration runs exactly once.

- [ ] **Step 4: Run middleware tests to verify they pass**

```bash
pytest tests/test_middleware.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add bot.py tests/test_middleware.py
git commit -m "feat: add OwnerOnlyMiddleware to restrict bot to owner"
```

---

## Chunk 3: Docs and env files

### Task 3: Create .env.example and update CLAUDE.md

**Files:**
- Create: `.env.example`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Create .env.example**

Create `.env.example` in the project root:

```bash
# Telegram MTProto credentials (from https://my.telegram.org)
TELEGRAM_API_ID=
TELEGRAM_API_HASH=

# Telegram Bot token (from @BotFather)
BOT_TOKEN=

# Google Gemini API key (from https://aistudio.google.com)
GEMINI_API_KEY=

# Owner's numeric Telegram user ID (find via @userinfobot) — required
OWNER_ID=

# Comma-separated Telegram channel usernames to monitor (e.g. @channel1,@channel2)
CHANNELS=

# Aiven PostgreSQL connection string
DATABASE_URL=

# Optional: Telethon session string (alternative to session.session file)
SESSION_STRING=

# Optional tuning (defaults shown)
BUFFER_SIZE=100
MAX_CONTEXT_MESSAGES=50
RETENTION_DAYS=30
PRUNE_INTERVAL_HOURS=24
```

- [ ] **Step 2: Verify .env.example is not gitignored**

```bash
git check-ignore -v .env.example
```

Expected: no output (the file is not ignored). `.env` is ignored; `.env.example` should not be. If it IS ignored, open `.gitignore` and add a negation line: `!.env.example`.

- [ ] **Step 3: Update CLAUDE.md Configuration table**

In `CLAUDE.md`, find the `## Configuration` section and its table. Add two rows:

After `BOT_TOKEN`, add:
```markdown
| `OWNER_ID` | Yes | — | Numeric Telegram user ID of the bot owner (find via @userinfobot) |
```

After `SESSION_STRING` (it is already in `config.py` but missing from the table), add:
```markdown
| `SESSION_STRING` | No | `""` | Telethon session string (alternative to `session.session` file) |
```

- [ ] **Step 4: Add OWNER_ID to your .env file**

Open `.env` and add:

```
OWNER_ID=5730878656
```

`.env` is in `.gitignore` — do not commit it.

- [ ] **Step 5: Smoke test the full bot locally**

Note: this step requires an existing `session.session` file from a prior Telethon login. If none exists, the bot will prompt for your Telegram phone number and OTP interactively.

```bash
python main.py
```

Expected: bot starts without errors. From an account that is NOT the owner, send any command — the bot should not reply. From the owner account, send `/channels` — it should reply normally.

- [ ] **Step 6: Commit docs changes**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: add .env.example and document OWNER_ID and SESSION_STRING in CLAUDE.md"
```
