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

**`analyzer.py`:** Analysis commands call a private `_ask()` helper that formats buffered messages into a timestamped block and sends it with a command-specific system prompt to Gemini 2.5 Flash. The `/factcheck` command calls `_client` directly to enable Google Search grounding, which is incompatible with `_ask`'s `thinking_budget=0` config.

**Dual Telegram identity:** The system uses two separate Telegram connections simultaneously — Telethon (MTProto, user account) to read channels, and aiogram (Bot API) to respond to users.

**Scheduled digests:** `scheduler.py` runs as a fourth `asyncio.gather()` task and fires jobs at fixed `Asia/Ho_Chi_Minh` times: `hn.py` (Algolia HN API, keyword-filtered security stories) at `HN_DIGEST_TIMES`, and `voz.py` (voz.vn `f/diem-bao.33` subforum RSS — one thread per curated news article) at `PRESS_DIGEST_TIMES`. Digests are Gemini-composed in `analyzer.py` (`hn_digest`, `press_digest`) and pushed to `OWNER_ID` via `bot.send_to_owner`. Links are appended deterministically by code — the LLM references stories by number and never writes URLs. voz.vn sits behind Cloudflare, which fingerprints client TLS stacks — `voz.py` fetches through `curl_cffi` impersonating Chrome (sync, wrapped in `asyncio.to_thread`); cloudscraper was tried first and gets 403 from the VM's datacenter IP. If Cloudflare hardens further, the fetch fails soft (empty digest + logged exception) rather than crashing the bot. /paper additionally crawls the forum's pinned news megathreads (sticky block on the forum page; meta stickies like "Nội quy"/"Report" filtered by an anchored title regex) and appends a Vietnamese `megathread_update` section per thread (max 2) via `bot.build_press_report`.

**Weekly review + auto-create:** `notion.py` is a Notion REST client (httpx, read +
create) for a personal "Weekly To-do List" page — a page per week under the parent
`📅 Weekly To-do Lists`, each a 7-column Mon→Sun layout of `to_do` checkboxes. A
`weekly_review` job in `scheduler.py` (registered in `main.py`, self-guards to Sunday
via `weekday() == 6`) fires at `WEEKLY_REVIEW_TIME`: it finds the current week's page
(`find_current_week_page` — parses the date range in each `child_page` title), computes
a completion scoreboard in code (`analyzer._weekly_scoreboard` — LLMs miscount, so
Gemini only narrates), and pushes a recap/insights/next-week/one-liner review to the
owner. Then, isolated from the review, it clones that page into next week's page
(`create_next_week` — checkboxes reset, date-ranged title, idempotency-guarded). All
Notion vars are optional (disable-when-empty; `WEEKLY_ENABLED`/`AUTOCREATE_ENABLED`
gates) so a deployment without them still boots. `/weekly` and `/newweek` run each half
on demand. Custom Notion emoji (`:programming:`) degrade to plain text in clones.

**Thread comment summary:** `/thread <voz url>` → `voz.fetch_thread` reads the latest ~60 posts (last 3 pages of 20; XenForo thread pages are `.../page-N`) and `analyzer.thread_summary` returns a Vietnamese-only discussion + sentiment briefing. Post extraction uses BeautifulSoup: author from `.message-name .username`, body from `.message-body .bbWrapper` with `<blockquote>` quotes stripped so each poster's own words are summarized. `voz.THREAD_URL_RE` restricts fetching to `voz.vn/t/<slug>.<id>/` URLs — an SSRF guard against pointing the fetcher at arbitrary hosts.

**Proactive keyword alerts:** `alerts.py` (`AlertMatcher`) compiles `ALERT_KEYWORDS` into a word-boundary, case-insensitive regex. The crawler's *live* message handler (never backfill) matches each message and fires `on_alert` in `main.py`, which pushes `🚨 Alert [keywords] in @channel` to the owner via `send_to_owner`. Empty `ALERT_KEYWORDS` disables it.

**Quick-start buttons:** `/start` attaches a persistent `ReplyKeyboardMarkup` whose button text is the literal command, so taps go through the normal command pipeline (owner check, rate limit). `/factcheck` and `/thread` without args enter an aiogram FSM prompt state (`PromptFlow`, in-memory `MemoryStorage`) and treat the next plain message as the argument; `ClearPromptOnCommandMiddleware` makes any command cancel a pending prompt, and `RateLimitMiddleware` throttles prompt answers (which call Gemini) while exempting the bare button taps (which don't).

**Liveness watchdog:** `health.py` runs a daemon OS thread (survives an asyncio event-loop stall) that `os._exit(1)`s if the heartbeat file goes stale (>180s), so Docker's `restart: unless-stopped` recovers a wedged bot — the failure mode plain restart policies miss. An asyncio `heartbeat()` task in `main.py` refreshes the file every 30s; a `HEALTHCHECK` in the Dockerfile surfaces the same staleness in `docker ps`.

## Configuration

All config is read from environment variables (via `.env` + `python-dotenv`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_API_ID` | Yes | — | From my.telegram.org |
| `TELEGRAM_API_HASH` | Yes | — |From my.telegram.org |
| `BOT_TOKEN` | Yes | — | From @BotFather |
| `GEMINI_API_KEY` | Yes | — | From Google AI Studio |
| `OWNER_ID` | Yes | — | Numeric Telegram user ID of the bot owner (find via @userinfobot) |
| `CHANNELS` | Yes | `""` | Comma-separated channel usernames to monitor |
| `SESSION_STRING` | No | `""` | Telethon session string (alternative to `session.session` file) |
| `BUFFER_SIZE` | No | `100` | Max messages stored per channel |
| `RATE_LIMIT_SECONDS` | No | `15` | Cooldown between analysis commands (`0` disables) |
| `MAX_CONTEXT_MESSAGES` | No | `50` | Max messages sent to LLM per analysis |
| `DATABASE_URL` | Yes | — | Aiven PostgreSQL connection string |
| `DATABASE_CA_CERT` | No | `""` | Path to Aiven CA cert (`ca.pem`); enables full TLS verification, else falls back to unverified `require` |
| `DATABASE_SSL` | No | `require` | Set `disable` for a local/sidecar Postgres with no TLS endpoint |
| `RETENTION_DAYS` | No | `30` | Days to keep archived messages (min 1) |
| `PRUNE_INTERVAL_HOURS` | No | `24` | How often to run pruner in hours (min 1) |
| `HN_DIGEST_TIMES` | No | `12:30` | HN security digest push times, Asia/Ho_Chi_Minh (empty disables) |
| `PRESS_DIGEST_TIMES` | No | `12:30` | Vietnamese press digest push times, Asia/Ho_Chi_Minh (empty disables) |
| `ALERT_KEYWORDS` | No | conflict/security list | Keywords that trigger a proactive owner alert on live messages (empty disables) |
| `HEARTBEAT_PATH` | No | `/tmp/heartbeat` | Liveness file path for the watchdog + Docker healthcheck |
| `NOTION_API_KEY` | No | `""` | Notion internal integration token; empty disables the weekly review |
| `NOTION_TODO_PARENT_ID` | No | `""` | Parent page holding the weekly to-do pages; empty disables |
| `WEEKLY_REVIEW_TIME` | No | `19:00` | Sunday review push time, Asia/Ho_Chi_Minh; empty disables the schedule |
| `WEEKLY_AUTOCREATE` | No | `true` | `false` skips cloning next week's page (review still runs) |
| `NOTION_TEMPLATE_PAGE_ID` | No | `""` | Optional clone-source override; empty → clone the current-week page |

Copy `.env.example` to `.env` and fill in values before running.

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Help text |
| `/channels` | Monitored channels and message counts |
| `/summary` | Top 5 significant events |
| `/factcheck <claim>` | Cross-check a claim against channel messages + Google Search |
| `/threat` | Conflict risk assessment (1–5 scale) |
| `/hn` | Current security stories from Hacker News |
| `/paper` | Điểm báo — press review from voz.vn f/Điểm báo |
| `/thread <voz url>` | Summarize the recent comments (discussion + sentiment) of a voz thread |
| `/weekly` | Review this week's Notion to-do list (recap · insights · next week · one-liner) |
| `/newweek` | Create next week's to-do page by cloning this week's (checkboxes reset) |
| `/cancel` | Cancel a pending /factcheck or /thread prompt |

## Key Constraints

- **In-memory analysis buffer:** Buffer is in-memory only and is the sole source for all analysis commands. Lost on restart.
- **PostgreSQL archive:** Live messages (not backfill) are asynchronously archived to Aiven PostgreSQL via `db.py`. Fire-and-forget — DB failures are silently discarded.
- **Owner-only access:** `OwnerOnlyMiddleware` in `bot.py` silently drops messages from any user whose ID is not `OWNER_ID`.
- **Response chunking:** `bot.py` splits LLM responses into 4096-char chunks (Telegram's message limit).
