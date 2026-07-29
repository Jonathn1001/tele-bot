import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
OWNER_ID = int(os.environ["OWNER_ID"])

CHANNELS = [ch.strip() for ch in os.environ.get("CHANNELS", "").split(",") if ch.strip()]
BUFFER_SIZE = int(os.environ.get("BUFFER_SIZE", "100"))
RATE_LIMIT_SECONDS = max(0, int(os.environ.get("RATE_LIMIT_SECONDS", "15")))  # cooldown between analysis commands; 0 disables
MAX_CONTEXT_MESSAGES = int(os.environ.get("MAX_CONTEXT_MESSAGES", "50"))
SESSION_STRING = os.environ.get("SESSION_STRING", "")

DATABASE_URL = os.environ["DATABASE_URL"]
DATABASE_CA_CERT = os.environ.get("DATABASE_CA_CERT", "")  # path to CA cert (e.g. Aiven ca.pem); enables full TLS verification
DATABASE_SSL = os.environ.get("DATABASE_SSL", "require")   # "require" (default) or "disable" for local/sidecar Postgres
RETENTION_DAYS = max(1, int(os.environ.get("RETENTION_DAYS", "30")))        # minimum 1 day
PRUNE_INTERVAL_HOURS = max(1, int(os.environ.get("PRUNE_INTERVAL_HOURS", "24")))  # minimum 1 hour

# Scheduled digest fire times, Asia/Ho_Chi_Minh ("HH:MM[,HH:MM...]"). Empty string disables.
HN_DIGEST_TIMES = os.environ.get("HN_DIGEST_TIMES", "12:30")
PRESS_DIGEST_TIMES = os.environ.get("PRESS_DIGEST_TIMES", "18:30")

# Where the scheduled press digest lands. Empty -> the owner's DM. Group ids are
# negative; a basic group that later upgrades to a supergroup gets a new -100... id,
# and the old one stops working (the digest job warns the owner when a send fails).
_PRESS_CHAT_ID_RAW = os.environ.get("PRESS_CHAT_ID", "").strip()
PRESS_CHAT_ID = int(_PRESS_CHAT_ID_RAW) if _PRESS_CHAT_ID_RAW else OWNER_ID

# --- Weekly review (Notion → Gemini → Telegram) ---
# All optional: disable-when-empty, so a deployment without Notion still boots
# (unlike the required OWNER_ID / DATABASE_URL). See docs spec 2026-07-21.
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")               # internal integration token (secret)
NOTION_TODO_PARENT_ID = os.environ.get("NOTION_TODO_PARENT_ID", "") # parent page holding the weekly to-do pages
NOTION_TEMPLATE_PAGE_ID = os.environ.get("NOTION_TEMPLATE_PAGE_ID", "")  # optional clone-source override; empty → clone current week
WEEKLY_REVIEW_TIME = os.environ.get("WEEKLY_REVIEW_TIME", "19:00")  # Sunday push time, Asia/Ho_Chi_Minh; empty disables schedule
_WEEKLY_AUTOCREATE_RAW = os.environ.get("WEEKLY_AUTOCREATE", "true").strip().lower()
WEEKLY_AUTOCREATE = _WEEKLY_AUTOCREATE_RAW not in ("0", "false", "no", "off", "")
_WEEKLY_WRITEBACK_RAW = os.environ.get("WEEKLY_WRITEBACK", "true").strip().lower()
WEEKLY_WRITEBACK = _WEEKLY_WRITEBACK_RAW not in ("0", "false", "no", "off", "")  # false → Telegram-only

WEEKLY_ENABLED = bool(NOTION_API_KEY and NOTION_TODO_PARENT_ID)
AUTOCREATE_ENABLED = bool(WEEKLY_ENABLED and WEEKLY_AUTOCREATE)
WRITEBACK_ENABLED = bool(WEEKLY_ENABLED and WEEKLY_WRITEBACK)  # append the review onto its week page

# Proactive alerts: push the owner when a live channel message contains any of
# these keywords/phrases. Comma-separated; empty string disables alerting.
_DEFAULT_ALERT_KEYWORDS = (
    "nuclear,mobilization,mobilisation,martial law,invasion,ceasefire,airstrike,"
    "chemical weapon,evacuation,state of emergency,breaking,escalation,nato"
)
ALERT_KEYWORDS = [
    k.strip() for k in os.environ.get("ALERT_KEYWORDS", _DEFAULT_ALERT_KEYWORDS).split(",") if k.strip()
]
