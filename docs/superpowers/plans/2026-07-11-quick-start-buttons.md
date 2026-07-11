# Quick-Start Buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-tap access to all bot commands via a persistent reply keyboard, with a prompt-flow conversation for the two argument-taking commands (`/factcheck`, `/thread`).

**Architecture:** A `ReplyKeyboardMarkup` whose button text is the literal command, attached to the `/start` reply — taps send normal command messages so all existing handlers and middlewares apply unchanged. `/factcheck` and `/thread` without arguments enter an aiogram FSM state (`MemoryStorage`, in-memory) and treat the next plain message as the argument. Commands always win over a pending prompt.

**Tech Stack:** Python 3, aiogram 3.29.1 (FSM: `StatesGroup`/`FSMContext`/state-as-filter), pytest with direct handler calls + `AsyncMock`.

**Spec:** `docs/superpowers/specs/2026-07-11-quick-start-buttons-design.md`

## Global Constraints

- aiogram is pinned at `3.29.1` — no new dependencies.
- All new handlers go in `bot.py`; registration order matters: prompt-state handlers MUST be registered (appear in the file) after every `Command` handler, so commands match first.
- Middleware execution order MUST be: `OwnerOnlyMiddleware` → `ClearPromptOnCommandMiddleware` → `RateLimitMiddleware`.
- Tests call handlers directly with mocks (no dispatcher integration harness) — follow existing conventions in `tests/test_commands.py` / `tests/test_middleware.py`.
- Every test file sets the dummy env vars at the top before importing project modules (already true for existing files; only new test code is added to existing files).
- Run tests with: `source .venv/bin/activate && python3 -m pytest tests/ -q` (use `python3`, plain `python` does not exist on this machine).
- User-facing reply text: English for factcheck prompts, Vietnamese for thread prompts (matches each command's reply language).
- Commit after every task; never `git add -A`; never commit `docker-compose.yml`.

---

### Task 1: Persistent keyboard on /start

**Files:**
- Modify: `bot.py` (imports; add `QUICK_KEYBOARD`; attach in `cmd_start`)
- Test: `tests/test_commands.py`

**Interfaces:**
- Produces: `bot.QUICK_KEYBOARD: ReplyKeyboardMarkup` — module-level constant, referenced by tests.

- [ ] **Step 1: Write the failing tests** — append to the `/start` section of `tests/test_commands.py`:

```python
async def test_start_attaches_quick_keyboard():
    msg = _mock_msg()
    await bot.cmd_start(msg)
    kb = msg.answer.call_args[1]["reply_markup"]
    assert kb is bot.QUICK_KEYBOARD


def test_quick_keyboard_layout():
    kb = bot.QUICK_KEYBOARD
    assert kb.is_persistent is True
    assert kb.resize_keyboard is True
    texts = [b.text for row in kb.keyboard for b in row]
    assert texts == [
        "/summary", "/threat",
        "/hn", "/paper",
        "/factcheck", "/thread",
        "/channels",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_commands.py -q -k "quick_keyboard or attaches_quick"`
Expected: FAIL — `AttributeError: module 'bot' has no attribute 'QUICK_KEYBOARD'`

- [ ] **Step 3: Implement** — in `bot.py`:

Extend the existing `aiogram.types` import block:

```python
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.types import Message as TgMessage
from aiogram.types import TelegramObject
```

Add below `MAX_CLAIM_LENGTH = 500`:

```python
# Button text is the literal command: a tap sends a normal command message,
# so existing handlers, owner-check and rate-limit apply unchanged.
QUICK_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/summary"), KeyboardButton(text="/threat")],
        [KeyboardButton(text="/hn"), KeyboardButton(text="/paper")],
        [KeyboardButton(text="/factcheck"), KeyboardButton(text="/thread")],
        [KeyboardButton(text="/channels")],
    ],
    is_persistent=True,
    resize_keyboard=True,
)
```

In `cmd_start`, add the keyboard to the existing `message.answer(...)` call:

```python
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=QUICK_KEYBOARD,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_commands.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_commands.py
git commit -m "feat(ux): persistent quick-start keyboard on /start"
```

---

### Task 2: Native command menu (set_my_commands)

**Files:**
- Modify: `bot.py` (add `BOT_COMMANDS`, `setup_bot_commands`)
- Modify: `main.py` (call it before polling)
- Test: `tests/test_commands.py`

**Interfaces:**
- Produces: `bot.setup_bot_commands(bot: Bot) -> None` (async) — called from `main.main()`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_commands.py`:

```python
async def test_setup_bot_commands_registers_menu():
    tg_bot = AsyncMock()
    await bot.setup_bot_commands(tg_bot)
    tg_bot.set_my_commands.assert_called_once()
    commands = tg_bot.set_my_commands.call_args[0][0]
    names = [c.command for c in commands]
    assert names == [
        "summary", "threat", "factcheck", "hn",
        "paper", "thread", "channels", "cancel",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_commands.py::test_setup_bot_commands_registers_menu -q`
Expected: FAIL — `AttributeError: module 'bot' has no attribute 'setup_bot_commands'`

- [ ] **Step 3: Implement** — in `bot.py`:

Extend the types import:

```python
from aiogram.types import BotCommand, KeyboardButton, ReplyKeyboardMarkup
```

Add below `QUICK_KEYBOARD`:

```python
BOT_COMMANDS = [
    BotCommand(command="summary", description="Top 5 significant events"),
    BotCommand(command="threat", description="Conflict risk assessment (1–5)"),
    BotCommand(command="factcheck", description="Fact-check a claim"),
    BotCommand(command="hn", description="HN security stories"),
    BotCommand(command="paper", description="Điểm báo from voz"),
    BotCommand(command="thread", description="Summarize a voz thread"),
    BotCommand(command="channels", description="Monitored channels"),
    BotCommand(command="cancel", description="Cancel the current prompt"),
]


async def setup_bot_commands(bot: Bot) -> None:
    """Register the native '/' menu. Cosmetic — callers should fail soft."""
    await bot.set_my_commands(BOT_COMMANDS)
```

In `main.py`, import and call it right before `logger.info("Starting Telegram Intel Bot...")`:

```python
from bot import build_dispatcher, send_to_owner, setup_bot_commands
```

```python
    try:
        await setup_bot_commands(bot)
    except Exception:
        logger.exception("set_my_commands failed; '/' menu may be stale")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py main.py tests/test_commands.py
git commit -m "feat(ux): register native command menu at startup"
```

---

### Task 3: PromptFlow FSM — /factcheck prompt flow

**Files:**
- Modify: `bot.py` (FSM states; extract `_run_factcheck`; rework `cmd_factcheck`; add `prompt_claim` handler at the END of the file)
- Test: `tests/test_commands.py` (rewrite `test_factcheck_no_claim_returns_usage`; add state helper + new tests; add `state` arg to existing factcheck tests)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `bot.PromptFlow` (`StatesGroup`) with `awaiting_claim = State()` and `awaiting_thread_url = State()` (thread state used by Task 4).
  - `bot._run_factcheck(message: TgMessage, claim: str) -> None` (async).
  - `bot.cmd_factcheck(message, command, state: FSMContext)` — signature gains `state`.
  - `bot.prompt_claim(message: TgMessage, state: FSMContext)` (async).
  - Test helper `_mock_state()` in `tests/test_commands.py`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_commands.py`, add next to `_mock_msg`:

```python
def _mock_state(current: str | None = None) -> AsyncMock:
    st = AsyncMock()
    st.get_state = AsyncMock(return_value=current)
    return st
```

Replace `test_factcheck_no_claim_returns_usage` with:

```python
async def test_factcheck_no_claim_starts_prompt():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = None
    state = _mock_state()
    await bot.cmd_factcheck(msg, cmd, state)
    state.set_state.assert_called_once_with(bot.PromptFlow.awaiting_claim)
    prompt_text = msg.answer.call_args[0][0]
    assert "claim" in prompt_text
    assert "/cancel" in prompt_text
```

Update the three other factcheck tests (`test_factcheck_claim_too_long_returns_error`, `test_factcheck_empty_buffer_returns_no_messages`, `test_factcheck_calls_analyzer_and_replies`) — each gets a state arg and must not enter the prompt:

```python
    state = _mock_state()
    ...
        await bot.cmd_factcheck(msg, cmd, state)
    state.set_state.assert_not_called()
```

(keep each test's existing assertions unchanged.)

Add a new section at the end of the file:

```python
# ---------------------------------------------------------------------------
# Prompt flow — /factcheck via button
# ---------------------------------------------------------------------------

async def test_prompt_claim_runs_factcheck_and_clears_state():
    msg = _mock_msg()
    msg.text = "Russia closed the border"
    state = _mock_state(bot.PromptFlow.awaiting_claim.state)
    buf = _make_buffer("test message")
    mock_fn = AsyncMock(return_value="SUPPORTED\nEvidence.")
    with patch.object(bot, "_buffer", buf), \
         patch("analyzer.fact_check", new=mock_fn):
        await bot.prompt_claim(msg, state)
    state.clear.assert_called_once()
    mock_fn.assert_called_once()
    assert mock_fn.call_args[0][0] == "Russia closed the border"


async def test_prompt_claim_too_long_reprompts_and_keeps_state():
    msg = _mock_msg()
    msg.text = "x" * 501
    state = _mock_state(bot.PromptFlow.awaiting_claim.state)
    await bot.prompt_claim(msg, state)
    state.clear.assert_not_called()
    assert str(bot.MAX_CLAIM_LENGTH) in msg.answer.call_args[0][0]


async def test_prompt_claim_slash_text_cancels_prompt():
    # An unknown command mid-prompt: state was already cleared by the
    # ClearPromptOnCommandMiddleware; the handler must not treat it as a claim.
    msg = _mock_msg()
    msg.text = "/unknowncmd"
    state = _mock_state(None)
    mock_fn = AsyncMock()
    with patch("analyzer.fact_check", new=mock_fn):
        await bot.prompt_claim(msg, state)
    mock_fn.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_commands.py -q -k "factcheck or prompt_claim"`
Expected: FAIL — `AttributeError: module 'bot' has no attribute 'PromptFlow'` and signature errors.

- [ ] **Step 3: Implement** — in `bot.py`:

Add imports:

```python
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
```

Add below `BOT_COMMANDS`:

```python
class PromptFlow(StatesGroup):
    """Button taps on /factcheck and /thread start a short conversation:
    the next plain message is treated as the missing argument."""

    awaiting_claim = State()
    awaiting_thread_url = State()
```

Rework `cmd_factcheck` — the with-args path moves into `_run_factcheck`:

```python
async def _run_factcheck(message: TgMessage, claim: str) -> None:
    if len(claim) > MAX_CLAIM_LENGTH:
        await message.answer(f"Claim too long. Please keep it under {MAX_CLAIM_LENGTH} characters.")
        return
    if _buffer is None or _buffer.is_empty():
        await message.answer(EMPTY_BUFFER_REPLY)
        return
    msgs = _buffer.get_all(limit=config.MAX_CONTEXT_MESSAGES)
    await message.answer(f"🔎 Fact-checking against {len(msgs)} channel messages + web sources… (~20s)")
    result = await analyzer.fact_check(claim, msgs)
    await _reply_analysis(message, result)


@router.message(Command("factcheck"))
async def cmd_factcheck(message: TgMessage, command: CommandObject, state: FSMContext) -> None:
    claim = (command.args or "").strip()
    if not claim:
        await state.set_state(PromptFlow.awaiting_claim)
        await message.answer("Send the claim to check (or /cancel).")
        return
    await _run_factcheck(message, claim)
```

Add at the very END of `bot.py` (after every `Command` handler, so commands match first):

```python
# Prompt-flow answer handlers — MUST stay registered after all Command
# handlers so a command sent mid-prompt matches its own handler first.
@router.message(PromptFlow.awaiting_claim)
async def prompt_claim(message: TgMessage, state: FSMContext) -> None:
    claim = (message.text or "").strip()
    if claim.startswith("/"):
        # Unknown command mid-prompt; middleware already dropped the state.
        await message.answer("Prompt cancelled.")
        return
    if not claim or len(claim) > MAX_CLAIM_LENGTH:
        await message.answer(f"Send a text claim under {MAX_CLAIM_LENGTH} characters, or /cancel.")
        return
    await state.clear()
    await _run_factcheck(message, claim)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_commands.py
git commit -m "feat(ux): prompt flow for /factcheck button tap"
```

---

### Task 4: /thread prompt flow

**Files:**
- Modify: `bot.py` (extract `_run_thread`; rework `cmd_thread`; add `prompt_thread_url` handler at the END of the file)
- Test: `tests/test_commands.py`

**Interfaces:**
- Consumes: `PromptFlow.awaiting_thread_url` from Task 3.
- Produces:
  - `bot._run_thread(message: TgMessage, url: str) -> None` (async).
  - `bot.cmd_thread(message, command, state: FSMContext)` — signature gains `state`.
  - `bot.prompt_thread_url(message: TgMessage, state: FSMContext)` (async).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_commands.py`:

```python
# ---------------------------------------------------------------------------
# Prompt flow — /thread via button
# ---------------------------------------------------------------------------

async def test_thread_no_url_starts_prompt():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = None
    state = _mock_state()
    await bot.cmd_thread(msg, cmd, state)
    state.set_state.assert_called_once_with(bot.PromptFlow.awaiting_thread_url)
    assert "/cancel" in msg.answer.call_args[0][0]


async def test_thread_with_url_does_not_enter_prompt():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = "https://voz.vn/t/abc.123456/"
    state = _mock_state()
    thread = __import__("voz").Thread(title="T", url=cmd.args, posts=[])
    with patch("voz.fetch_thread", new=AsyncMock(return_value=thread)), \
         patch("analyzer.thread_summary", new=AsyncMock(return_value="tóm tắt")):
        await bot.cmd_thread(msg, cmd, state)
    state.set_state.assert_not_called()


async def test_prompt_thread_url_invalid_reprompts_and_keeps_state():
    msg = _mock_msg()
    msg.text = "https://evil.com/t/x.1/"
    state = _mock_state(bot.PromptFlow.awaiting_thread_url.state)
    await bot.prompt_thread_url(msg, state)
    state.clear.assert_not_called()
    assert "voz" in msg.answer.call_args[0][0]


async def test_prompt_thread_url_valid_runs_summary_and_clears_state():
    msg = _mock_msg()
    msg.text = "https://voz.vn/t/abc.123456/"
    state = _mock_state(bot.PromptFlow.awaiting_thread_url.state)
    thread = __import__("voz").Thread(title="T", url=msg.text, posts=[])
    mock_fn = AsyncMock(return_value="tóm tắt")
    with patch("voz.fetch_thread", new=AsyncMock(return_value=thread)), \
         patch("analyzer.thread_summary", new=mock_fn):
        await bot.prompt_thread_url(msg, state)
    state.clear.assert_called_once()
    mock_fn.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_commands.py -q -k "thread_no_url or thread_with_url or prompt_thread"`
Expected: FAIL — `cmd_thread` missing `state` param / `prompt_thread_url` undefined.

- [ ] **Step 3: Implement** — in `bot.py`:

Rework `cmd_thread`:

```python
async def _run_thread(message: TgMessage, url: str) -> None:
    await message.answer("🧵 Đang đọc bình luận mới nhất trên thread voz… (~30s)")
    thread = await voz.fetch_thread(url)
    if thread is None:
        await message.answer(analyzer.ANALYSIS_FAILED_REPLY)
        return
    result = await analyzer.thread_summary(thread)
    await _reply_analysis(message, result)


@router.message(Command("thread"))
async def cmd_thread(message: TgMessage, command: CommandObject, state: FSMContext) -> None:
    url = (command.args or "").strip()
    if not url:
        await state.set_state(PromptFlow.awaiting_thread_url)
        await message.answer("Gửi link thread voz (dạng voz.vn/t/…/) — hoặc /cancel.")
        return
    if voz.normalize_thread_url(url) is None:
        await message.answer("Đó không phải link thread voz hợp lệ (cần dạng voz.vn/t/…/).")
        return
    await _run_thread(message, url)
```

Append at the END of `bot.py` (below `prompt_claim`):

```python
@router.message(PromptFlow.awaiting_thread_url)
async def prompt_thread_url(message: TgMessage, state: FSMContext) -> None:
    url = (message.text or "").strip()
    if url.startswith("/"):
        await message.answer("Prompt cancelled.")
        return
    if voz.normalize_thread_url(url) is None:
        await message.answer("Đó không phải link thread voz hợp lệ — gửi lại link (hoặc /cancel).")
        return
    await state.clear()
    await _run_thread(message, url)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_commands.py
git commit -m "feat(ux): prompt flow for /thread button tap"
```

---

### Task 5: /cancel + commands always win (ClearPromptOnCommandMiddleware)

**Files:**
- Modify: `bot.py` (add `cmd_cancel` with the other Command handlers — BEFORE the prompt handlers; add `ClearPromptOnCommandMiddleware`; register it between owner and rate-limit middleware)
- Test: `tests/test_commands.py`, `tests/test_middleware.py`

**Interfaces:**
- Consumes: `PromptFlow` from Task 3.
- Produces:
  - `bot.cmd_cancel(message: TgMessage, state: FSMContext)` (async).
  - `bot.ClearPromptOnCommandMiddleware` (class, no ctor args).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commands.py`:

```python
# ---------------------------------------------------------------------------
# /cancel
# ---------------------------------------------------------------------------

async def test_cancel_clears_active_prompt():
    msg = _mock_msg()
    state = _mock_state(bot.PromptFlow.awaiting_claim.state)
    await bot.cmd_cancel(msg, state)
    state.clear.assert_called_once()
    assert "cancel" in msg.answer.call_args[0][0].lower()


async def test_cancel_without_prompt_says_nothing_to_cancel():
    msg = _mock_msg()
    state = _mock_state(None)
    await bot.cmd_cancel(msg, state)
    state.clear.assert_not_called()
    assert "nothing" in msg.answer.call_args[0][0].lower()
```

Append to `tests/test_middleware.py`:

```python
# ---------------------------------------------------------------------------
# ClearPromptOnCommandMiddleware — commands always win over a pending prompt
# ---------------------------------------------------------------------------

def _make_text_message(text: str) -> MagicMock:
    msg = _make_message(config.OWNER_ID)
    msg.text = text
    return msg


def _make_state(current: str | None) -> AsyncMock:
    st = AsyncMock()
    st.get_state = AsyncMock(return_value=current)
    return st


async def test_command_clears_active_prompt_state():
    mw = bot.ClearPromptOnCommandMiddleware()
    handler = AsyncMock()
    state = _make_state(bot.PromptFlow.awaiting_claim.state)
    msg = _make_text_message("/summary")
    await mw(handler, msg, {"state": state})
    state.clear.assert_called_once()
    handler.assert_called_once()


async def test_cancel_command_keeps_state_for_its_handler():
    """cmd_cancel reads the state itself to reply accurately — don't pre-clear."""
    mw = bot.ClearPromptOnCommandMiddleware()
    handler = AsyncMock()
    state = _make_state(bot.PromptFlow.awaiting_claim.state)
    msg = _make_text_message("/cancel")
    await mw(handler, msg, {"state": state})
    state.clear.assert_not_called()
    handler.assert_called_once()


async def test_plain_text_does_not_touch_state():
    mw = bot.ClearPromptOnCommandMiddleware()
    handler = AsyncMock()
    state = _make_state(bot.PromptFlow.awaiting_claim.state)
    msg = _make_text_message("just a claim")
    await mw(handler, msg, {"state": state})
    state.clear.assert_not_called()
    handler.assert_called_once()


async def test_command_without_active_state_is_untouched():
    mw = bot.ClearPromptOnCommandMiddleware()
    handler = AsyncMock()
    state = _make_state(None)
    msg = _make_text_message("/summary")
    await mw(handler, msg, {"state": state})
    state.clear.assert_not_called()
    handler.assert_called_once()


def test_clear_prompt_middleware_registered_between_owner_and_ratelimit():
    kinds = [type(m).__name__ for m in bot.router.message.middleware]
    owner = kinds.index("OwnerOnlyMiddleware")
    clear = kinds.index("ClearPromptOnCommandMiddleware")
    rate = kinds.index("RateLimitMiddleware")
    assert owner < clear < rate
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_commands.py tests/test_middleware.py -q -k "cancel or clear_prompt or clears_active or plain_text_does_not or without_active"`
Expected: FAIL — `cmd_cancel` / `ClearPromptOnCommandMiddleware` undefined.

- [ ] **Step 3: Implement** — in `bot.py`:

Add the middleware class below `RateLimitMiddleware`:

```python
class ClearPromptOnCommandMiddleware(BaseMiddleware):
    """A command always wins over a pending prompt: drop the prompt state so
    the user can never get trapped mid-conversation. /cancel is exempt — its
    handler reads the state itself to reply accurately."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        text = getattr(event, "text", None) or ""
        state: FSMContext | None = data.get("state")
        if (
            text.startswith("/")
            and not text.startswith("/cancel")
            and state is not None
            and await state.get_state() is not None
        ):
            await state.clear()
        return await handler(event, data)
```

Update the middleware registration block (order is load-bearing):

```python
router.message.middleware(OwnerOnlyMiddleware())
router.message.middleware(ClearPromptOnCommandMiddleware())
router.message.middleware(RateLimitMiddleware(config.RATE_LIMIT_SECONDS))
```

Add `cmd_cancel` next to the other Command handlers (anywhere BEFORE the prompt handlers; put it right after `cmd_start`):

```python
@router.message(Command("cancel"))
async def cmd_cancel(message: TgMessage, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Nothing to cancel.")
        return
    await state.clear()
    await message.answer("Cancelled.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_commands.py tests/test_middleware.py
git commit -m "feat(ux): /cancel and commands-win-over-prompt middleware"
```

---

### Task 6: Rate-limit the prompt answers, exempt the bare prompt commands

**Files:**
- Modify: `bot.py` (`RateLimitMiddleware.__call__`, `PROMPT_ONLY` constant, `PROMPT_STATES` constant)
- Test: `tests/test_middleware.py`

**Interfaces:**
- Consumes: `PromptFlow` from Task 3.
- Produces: `bot.PROMPT_ONLY: tuple[str, ...]`, `bot.PROMPT_STATES: frozenset[str]`.

**Why:** the prompt answer ("Russia closed the border") is a plain message — the prefix check misses it, so each answer would be an unthrottled Gemini call. Conversely a bare `/factcheck` tap makes NO Gemini call but would start the cooldown, which then blocks the user's own answer seconds later.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_middleware.py`:

```python
# ---------------------------------------------------------------------------
# RateLimitMiddleware × prompt flow
# ---------------------------------------------------------------------------

async def test_prompt_answer_is_rate_limited():
    mw = bot.RateLimitMiddleware(cooldown_seconds=60)
    handler = AsyncMock()
    state = _make_state(bot.PromptFlow.awaiting_claim.state)
    first = _make_text_message("/summary")
    await mw(handler, first, {"state": _make_state(None)})   # starts the cooldown
    answer = _make_text_message("some claim to check")
    answer.answer = AsyncMock()
    await mw(handler, answer, {"state": state})
    assert handler.call_count == 1          # second call blocked
    assert "wait" in answer.answer.call_args[0][0].lower()


async def test_bare_prompt_command_does_not_start_cooldown():
    mw = bot.RateLimitMiddleware(cooldown_seconds=60)
    handler = AsyncMock()
    tap = _make_text_message("/factcheck")
    await mw(handler, tap, {"state": _make_state(None)})
    answer = _make_text_message("some claim to check")
    state = _make_state(bot.PromptFlow.awaiting_claim.state)
    await mw(handler, answer, {"state": state})
    assert handler.call_count == 2          # both passed through


async def test_plain_text_without_state_is_not_limited():
    mw = bot.RateLimitMiddleware(cooldown_seconds=60)
    handler = AsyncMock()
    msg = _make_text_message("hello")
    await mw(handler, msg, {"state": _make_state(None)})
    handler.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_middleware.py -q -k "prompt_answer or bare_prompt or without_state"`
Expected: `test_prompt_answer_is_rate_limited` and `test_bare_prompt_command_does_not_start_cooldown` FAIL (current middleware ignores state and rate-limits the bare tap); `test_plain_text_without_state_is_not_limited` may pass — keep it as a regression guard.

- [ ] **Step 3: Implement** — in `bot.py`:

Below `ANALYSIS_COMMANDS`, add:

```python
# Bare /factcheck or /thread only starts a prompt — no Gemini call, so no
# cooldown; charging one would block the user's own answer seconds later.
PROMPT_ONLY = ("/factcheck", "/thread")
```

Below the `PromptFlow` class (it must be defined after it), add:

```python
# The prompt ANSWER is a plain message that triggers a Gemini call — the
# prefix check can't see it, so the rate limiter checks these states too.
PROMPT_STATES = frozenset(
    {PromptFlow.awaiting_claim.state, PromptFlow.awaiting_thread_url.state}
)
```

Rework the guard at the top of `RateLimitMiddleware.__call__` (replace the current two-line check):

```python
        text = getattr(event, "text", None) or ""
        is_analysis = text.startswith(ANALYSIS_COMMANDS) and text.strip() not in PROMPT_ONLY
        if not is_analysis:
            state = data.get("state")
            if state is not None and await state.get_state() in PROMPT_STATES:
                is_analysis = True
        if self._cooldown <= 0 or not is_analysis:
            return await handler(event, data)
```

(the rest of the method — the cooldown bookkeeping — is unchanged.)

Note: `PromptFlow`/`PROMPT_STATES` are defined later in the file than the middleware class — that's fine, `__call__` only resolves the name at call time. Keep `PROMPT_STATES` next to `PromptFlow` for readability.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_middleware.py
git commit -m "fix(ratelimit): throttle prompt answers, exempt bare prompt taps"
```

---

### Task 7: Docs + full verification

**Files:**
- Modify: `bot.py` (`cmd_start` help text)
- Modify: `CLAUDE.md` (Bot Commands table + architecture note)

- [ ] **Step 1: Update /start help text** — in `cmd_start`:

After the `/channels` line, add:

```python
        "/cancel — Cancel the current prompt\n\n"
```

Keep the existing language line ("Analysis replies are in English; /paper and /thread reply in Tiếng Việt.") and append one NEW line after it (inside the same string, before the closing paren):

```python
        "Analysis replies are in English; /paper and /thread reply in Tiếng Việt.\n"
        "Tap a button below or use the '/' menu — no typing needed.",
```

- [ ] **Step 2: Update CLAUDE.md**

Add to the Bot Commands table:

```markdown
| `/cancel` | Cancel a pending /factcheck or /thread prompt |
```

Add to the Architecture section:

```markdown
**Quick-start buttons:** `/start` attaches a persistent `ReplyKeyboardMarkup` whose button text is the literal command, so taps go through the normal command pipeline (owner check, rate limit). `/factcheck` and `/thread` without args enter an aiogram FSM prompt state (`PromptFlow`, in-memory `MemoryStorage`) and treat the next plain message as the argument; `ClearPromptOnCommandMiddleware` makes any command cancel a pending prompt, and `RateLimitMiddleware` throttles prompt answers (which call Gemini) while exempting the bare button taps (which don't).
```

- [ ] **Step 3: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add bot.py CLAUDE.md
git commit -m "docs: quick-start buttons in help text and CLAUDE.md"
```
