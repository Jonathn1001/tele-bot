# Telegram Intel Bot

A Python bot that passively monitors configured Telegram channels for news and provides on-demand AI-powered intelligence analysis via bot commands. No web server, no database — everything runs in-memory.

## Features

- **Passive Monitoring**: Uses Telethon (MTProto) to subscribe to and monitor multiple Telegram channels concurrently.
- **AI Intelligence Analysis**: Integrates with Google's Gemini 1.5 Pro to provide summaries, extract entities, evaluate threats, and identify emerging trends from the buffered messages.
- **In-Memory Buffer**: Messages are kept in memory and automatically capped at a configured size, ensuring efficient resource usage without the need for external databases.
- **Dual Telegram Identity**: Uses two simultaneous Telegram connections — a user account (MTProto) to read channels, and a Bot API account (aiogram) to interact with users.

## Bot Commands

| Command     | Description                                                       |
| ----------- | ----------------------------------------------------------------- |
| `/start`    | Help text and bot introduction                                    |
| `/channels` | List monitored channels and current message counts in the buffer  |
| `/summary`  | Top 5 significant events summarized from recent messages          |
| `/trends`   | Recurring themes, patterns, and escalating situations             |
| `/entities` | Named entities (people, organizations, locations) grouped by type |
| `/threat`   | Conflict risk assessment and threat level calculation (1–5 scale) |

## Configuration

The bot uses environment variables for configuration. Create a `.env` file in the root directory (you can copy `.env.example` if available) with the following variables:

```ini
# From my.telegram.org
TELEGRAM_API_ID="your_api_id"
TELEGRAM_API_HASH="your_api_hash"

# From @BotFather
BOT_TOKEN="your_bot_token"

# From Google AI Studio
GEMINI_API_KEY="your_gemini_api_key"

# Comma-separated channel usernames to monitor (e.g., "bbc_news,cnn_breaking")
CHANNELS="channel1,channel2"

# Optional Configuration
BUFFER_SIZE=100           # Max messages stored per channel currently in memory
MAX_CONTEXT_MESSAGES=50   # Max messages sent to the LLM per analysis request
```

## Running the Bot

### Local Development

1. Create a virtual environment and activate it:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the bot:
   ```bash
   python main.py
   ```
   _Note: On the first run, Telethon will prompt for your Telegram phone number and OTP to authenticate the user account and create the `session.session` file._

### Docker (Production)

The easiest way to run the bot stably is via Docker Compose:

1. Build and start the container in detached mode:
   ```bash
   docker compose up -d
   ```
2. Follow the logs:
   ```bash
   docker compose logs -f bot
   ```
3. Stop the bot:
   ```bash
   docker compose down
   ```

_The `session.session` file is mounted as a volume so the authenticated Telethon session persists across container restarts._

## Deploying to Render

The bot runs as a **Background Worker** on Render (no web server or health-check port required). Authentication uses a `StringSession` string stored as an environment variable so no persistent disk is needed.

### Step 1 — Generate a StringSession (one-time, run locally)

With your virtual environment active, run this script once to authenticate and print the session string:

```python
from telethon.sessions import StringSession
from telethon.sync import TelegramClient
import os

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print(client.session.save())
```

Copy the printed string — you'll need it as `SESSION_STRING` in the next step.

### Step 2 — Create the Render service

1. Push the repo to GitHub.
2. In the Render dashboard, click **New → Background Worker** and connect your repository. Render will detect `render.yaml` automatically.
3. Under **Environment**, add the following secrets manually:

| Variable            | Value                                                   |
| ------------------- | ------------------------------------------------------- |
| `TELEGRAM_API_ID`   | from my.telegram.org                                    |
| `TELEGRAM_API_HASH` | from my.telegram.org                                    |
| `BOT_TOKEN`         | from @BotFather                                         |
| `GEMINI_API_KEY`    | from Google AI Studio                                   |
| `CHANNELS`          | comma-separated usernames, e.g. `bbc_news,cnn_breaking` |
| `SESSION_STRING`    | string generated in Step 1                              |

4. Deploy. The bot will connect and begin monitoring immediately. Follow logs in the Render dashboard to confirm.

> **Local development** is unaffected — when `SESSION_STRING` is not set, the bot falls back to the `session.session` file as before.

## Limitations & Constraints

- **No Persistence:** The message buffer is entirely in-memory. All collected messages are lost when the process restarts.
- **No Access Control:** Any user who discovers the bot can query it and trigger AI analysis.
- **Response Chunking:** Telegram limits messages to 4096 characters, so the bot automatically splits lengthy LLM responses into multiple messages.
