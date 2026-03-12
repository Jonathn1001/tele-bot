# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python bot that passively monitors configured Telegram channels for news and provides on-demand AI-powered intelligence analysis via bot commands. No web server, no database — everything runs in memory.

## Running the Bot

**Local development:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

On first run, Telethon will prompt for your Telegram phone number and OTP to create `session.session`.

**Docker (production):**
```bash
docker compose up -d          # Build and start
docker compose logs -f bot    # Follow logs
docker compose down           # Stop
```

The `session.session` file is mounted as a volume so the authenticated Telethon session persists across restarts.

## Architecture

Two concurrent async tasks run via `asyncio.gather()` in `main.py`:

1. **`crawler.py` (TelegramCrawler)** — Telethon MTProto user-account client that subscribes to channels and feeds incoming messages into the buffer.
2. **`bot.py` (aiogram Dispatcher)** — Bot API connection that handles slash commands from users chatting with the bot.

Both tasks share the same `MessageBuffer` instance directly via reference (no queue, no IPC).

**`buffer.py` (MessageBuffer):** In-memory `dict[channel_username, deque[Message]]`, capped at `BUFFER_SIZE` per channel. All messages are lost on process restart.

**`analyzer.py`:** All four analysis commands call a private `_ask()` helper that formats buffered messages into a timestamped block and sends it with a command-specific system prompt to Gemini 1.5 Pro. Gemini calls run in `asyncio.to_thread()` since `google-generativeai` is synchronous.

**Dual Telegram identity:** The system uses two separate Telegram connections simultaneously — Telethon (MTProto, user account) to read channels, and aiogram (Bot API) to respond to users.

## Configuration

All config is read from environment variables (via `.env` + `python-dotenv`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_API_ID` | Yes | — | From my.telegram.org |
| `TELEGRAM_API_HASH` | Yes | — |From my.telegram.org |
| `BOT_TOKEN` | Yes | — | From @BotFather |
| `GEMINI_API_KEY` | Yes | — | From Google AI Studio |
| `CHANNELS` | Yes | `""` | Comma-separated channel usernames to monitor |
| `BUFFER_SIZE` | No | `100` | Max messages stored per channel |
| `MAX_CONTEXT_MESSAGES` | No | `50` | Max messages sent to LLM per analysis |

Copy `.env.example` to `.env` and fill in values before running.

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Help text |
| `/channels` | Monitored channels and message counts |
| `/summary` | Top 5 significant events |
| `/trends` | Recurring themes and escalating situations |
| `/entities` | Named entities grouped by type |
| `/threat` | Conflict risk assessment (1–5 scale) |

## Key Constraints

- **No persistence:** Buffer is in-memory only; messages are lost on restart.
- **No access control:** Any user who finds the bot can query it.
- **Response chunking:** `bot.py` splits LLM responses into 4096-char chunks (Telegram's message limit).
- **No test suite** exists in this project.
