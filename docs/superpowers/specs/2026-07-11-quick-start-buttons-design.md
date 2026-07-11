# Quick-start buttons — design

**Date:** 2026-07-11
**Status:** approved

## Goal

One-tap access to bot commands instead of typing them. Owner-only bot, single
user, mobile-first usage.

## Decisions made during brainstorming

- **Persistent reply keyboard** (not inline buttons on /start): always visible
  under the text input, and because button text is the literal command
  (`/summary`), a tap sends a normal command message — existing `Command`
  handlers, `OwnerOnlyMiddleware`, and `RateLimitMiddleware` all apply
  unchanged. Inline buttons were rejected: callback events bypass both
  middlewares (new security surface) and scroll away with the /start message.
- **Prompt flow** for the two argument-taking commands (`/factcheck <claim>`,
  `/thread <voz url>`): tapping the button starts a short conversation instead
  of showing a usage hint.

## Design

### 1. Persistent keyboard

`ReplyKeyboardMarkup` with `is_persistent=True`, `resize_keyboard=True`,
attached to the `/start` reply.

Layout:

```
[ /summary   | /threat ]
[ /hn        | /paper  ]
[ /factcheck | /thread ]
[ /channels            ]
```

Also register the commands with `set_my_commands` at startup (in `main.py`
after bot init) so Telegram's native "/" menu button lists them with
descriptions.

### 2. Prompt flow (FSM)

aiogram FSM with the default `MemoryStorage` — in-memory state, lost on
restart, consistent with the project's no-database-for-runtime philosophy.

States (single `StatesGroup`):

- `PromptFlow.awaiting_claim` — set when `/factcheck` arrives **without**
  arguments. Bot replies "Send the claim to check (or /cancel)". The next
  plain-text message is treated as the claim and runs the existing factcheck
  path (including `MAX_CLAIM_LENGTH` validation), then clears state.
- `PromptFlow.awaiting_thread_url` — same for `/thread`. The reply is
  validated against `voz.THREAD_URL_RE`; an invalid URL gets "not a valid voz
  link, send again or /cancel" and **stays in state**.

Escape hatches:

- `/cancel` clears any active state.
- Any other command received while a state is active wins: the state is
  cleared and the command executes normally — the user can never get trapped.

`/factcheck <claim>` and `/thread <url>` **with** arguments behave exactly as
today (no state involved).

### 3. Rate-limit gap and fix

The prompt-flow answer ("Russia closed the border") does not start with a
command, so the current `RateLimitMiddleware` prefix check misses it — each
answer would be an un-throttled Gemini call. Fix: the middleware also applies
the cooldown when an FSM prompt state is active. `data["state"]`
(`FSMContext`) is available inside aiogram v3 message middleware; check
`await state.get_state()` against the `PromptFlow` states.

### 4. Tests

- `/start` reply carries the persistent keyboard with all 7 buttons.
- `/factcheck` without args → prompt text + `awaiting_claim` state set.
- Message while in `awaiting_claim` → factcheck runs with it, state cleared.
- `/thread` without args → prompt + `awaiting_thread_url`.
- Invalid voz URL while in state → re-prompt, state kept.
- Valid voz URL while in state → thread summary runs, state cleared.
- `/cancel` while in state → state cleared, confirmation reply.
- Another command while in state → state cleared, that command runs.
- Prompt-flow answer is subject to the analysis cooldown.
- `/factcheck <claim>` / `/thread <url>` with args → unchanged behavior, no
  state set.

## Out of scope

- Inline keyboards / callback queries.
- Persisting FSM state across restarts.
- Buttons for `/start` or `/cancel` themselves.
