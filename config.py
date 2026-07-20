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
PRESS_DIGEST_TIMES = os.environ.get("PRESS_DIGEST_TIMES", "12:30")

# Proactive alerts: push the owner when a live channel message contains any of
# these keywords/phrases. Comma-separated; empty string disables alerting.
_DEFAULT_ALERT_KEYWORDS = (
    "nuclear,mobilization,mobilisation,martial law,invasion,ceasefire,airstrike,"
    "chemical weapon,evacuation,state of emergency,breaking,escalation,nato"
)
ALERT_KEYWORDS = [
    k.strip() for k in os.environ.get("ALERT_KEYWORDS", _DEFAULT_ALERT_KEYWORDS).split(",") if k.strip()
]
