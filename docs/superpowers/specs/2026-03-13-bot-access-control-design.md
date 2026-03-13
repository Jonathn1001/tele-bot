# Bot Access Control Design

**Date:** 2026-03-13
**Status:** Approved

## Problem

The bot currently has no access control — any Telegram user who discovers it can run all commands (`/summary`, `/factcheck`, `/threat`, `/channels`). This is a personal-use bot and should only respond to its owner.

## Requirements

- Only the owner's Telegram account can trigger any bot command.
- Unauthorized users receive no response (silent drop).
- The owner ID is configurable via environment variable, not hardcoded in source.
- `OWNER_ID` is **required** — the bot will fail to start at import time if it is not set.

## Design

### Configuration

Add `OWNER_ID` to the environment variable set:

- `config.py`: `OWNER_ID = int(os.environ["OWNER_ID"])` — required, no default, raises `KeyError` at startup if missing (consistent with other required vars like `DATABASE_URL`).
- `.env.example`: create this new file (does not currently exist) documenting all env vars including `OWNER_ID=<your_telegram_user_id>`.
- `.env`: add the owner's actual numeric Telegram user ID (not committed to git).

### Middleware

Add `OwnerOnlyMiddleware(BaseMiddleware)` in `bot.py`. The registration line `router.message.middleware(OwnerOnlyMiddleware())` is placed **inside the `build_dispatcher()` function body**, before `dp.include_router(router)`, keeping all setup co-located.

Logic:
1. Check `message.from_user`. If it is `None` (e.g., anonymous channel post), treat as unauthorized — silently drop.
2. If `message.from_user.id` equals `config.OWNER_ID`, call the next handler.
3. Otherwise, return without calling the handler — no reply is sent.

This ensures all current and future commands handled by the router are automatically protected without modifying individual handlers.

### Files Changed

| File | Change |
|---|---|
| `config.py` | Add `OWNER_ID = int(os.environ["OWNER_ID"])` (required) |
| `.env.example` | **Create** new file documenting all env vars including `OWNER_ID=<your_telegram_user_id>` |
| `bot.py` | Add `OwnerOnlyMiddleware` class + register via `router.message.middleware(OwnerOnlyMiddleware())` |
| `.env` | Add `OWNER_ID=<actual numeric ID>` (not committed) |
| `CLAUDE.md` | Add `OWNER_ID` row to the Configuration table |

## Trade-offs Considered

| Approach | Verdict |
|---|---|
| Hardcode ID in source | Rejected — exposes personal data in git history |
| Decorator per handler | Rejected — requires updating every new command manually |
| Env-var + middleware | **Selected** — single enforcement point, ID stays out of source |
