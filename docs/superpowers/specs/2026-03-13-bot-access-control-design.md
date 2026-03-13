# Bot Access Control Design

**Date:** 2026-03-13
**Status:** Approved

## Problem

The bot currently has no access control — any Telegram user who discovers it can run all commands (`/summary`, `/factcheck`, `/threat`, `/channels`). This is a personal-use bot and should only respond to its owner.

## Requirements

- Only the owner's Telegram account can trigger any bot command.
- Unauthorized users receive no response (silent drop).
- The owner ID is configurable via environment variable, not hardcoded in source.

## Design

### Configuration

Add `OWNER_ID` to the environment variable set:

- `config.py`: `OWNER_ID = int(os.environ["OWNER_ID"])`
- `.env.example`: `OWNER_ID=<your_telegram_user_id>`
- `.env`: set to the owner's actual numeric Telegram user ID (not committed)

### Middleware

Add `OwnerOnlyMiddleware(BaseMiddleware)` in `bot.py`. It is registered on the router inside `build_dispatcher()` and runs before every message handler.

Logic:
1. Read `message.from_user.id`.
2. If it equals `config.OWNER_ID`, call the next handler.
3. Otherwise, return without calling the handler — no reply is sent.

This ensures all current and future commands are automatically protected without modifying individual handlers.

### Files Changed

| File | Change |
|---|---|
| `config.py` | Add `OWNER_ID = int(os.environ["OWNER_ID"])` |
| `.env.example` | Add `OWNER_ID=<your_telegram_user_id>` |
| `bot.py` | Add `OwnerOnlyMiddleware` class + register on router |
| `.env` | Add owner's actual numeric Telegram user ID |

## Trade-offs Considered

| Approach | Verdict |
|---|---|
| Hardcode ID in source | Rejected — exposes personal data in git history |
| Decorator per handler | Rejected — requires updating every new command manually |
| Env-var + middleware | **Selected** — single enforcement point, ID stays out of source |
