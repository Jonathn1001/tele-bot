# Design: Remove /trends & /entities, Add /factcheck

**Date:** 2026-03-12
**Status:** Approved

## Overview

Remove two underused analysis commands (`/trends`, `/entities`) and replace them with a `/factcheck <claim>` command that lets users submit a specific claim for validation against the buffered channel messages.

## Scope

Three files are modified. No new files are created.

| File | Change |
|---|---|
| `analyzer.py` | Remove `analyze_trends()` and `extract_entities()`. Add `fact_check(claim, messages)`. |
| `bot.py` | Remove `/trends` and `/entities` handlers. Add `/factcheck` handler. Update `/start` help text. Update import on line 3 to include `CommandObject`. |
| `CLAUDE.md` | Update Bot Commands table: remove `/trends` and `/entities` rows, add `/factcheck` row. |

## analyzer.py

Remove:
- `analyze_trends(messages)` — no longer needed
- `extract_entities(messages)` — no longer needed

Add:

```python
async def fact_check(claim: str, messages: list[Message]) -> str:
    return await _ask(
        f"You are an intelligence analyst. A user has submitted this claim for fact-checking:\n\n"
        f'"{claim}"\n\n'
        "Based ONLY on the Telegram messages provided, assess whether this claim is supported. "
        "Start your response with one of: SUPPORTED / CONTRADICTED / INSUFFICIENT EVIDENCE. "
        "Then provide a 2-3 sentence explanation. "
        "If relevant, quote specific messages (channel + timestamp) as evidence.",
        messages,
    )
```

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
- `CommandObject` is used for argument extraction. It must be added to the existing import on line 3 of `bot.py`: `from aiogram.filters import Command, CommandObject`. This correctly handles group-chat suffixes like `/factcheck@BotUsername <claim>` which plain string splitting would not.
- The in-progress message is `"Analyzing..."` — consistent with all other command handlers.
- Claims longer than 500 characters are rejected before a Gemini call is made. `MAX_CLAIM_LENGTH = 500` is intentionally hardcoded as a module-level constant in `bot.py` (not in `config.py`) — it is a validation guard specific to the bot layer, not a tunable runtime parameter like buffer sizes.
- **Prompt injection:** The user-supplied claim is embedded directly into the Gemini prompt. This is an accepted risk for a personal bot with no sensitive data exposure. No sanitization is implemented.

Update `/start` help text — replace the `/trends` and `/entities` lines with:
```
/factcheck <claim> — Verify a claim against monitored messages
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

## Key Constraints

- Fact-checking is performed **only against buffered messages** — no external search or internet access
- Gemini is prompted to be explicit about this limitation via "Based ONLY on the Telegram messages provided"
- No new dependencies introduced (`CommandObject` is already part of aiogram)
