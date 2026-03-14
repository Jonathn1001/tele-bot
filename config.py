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
MAX_CONTEXT_MESSAGES = int(os.environ.get("MAX_CONTEXT_MESSAGES", "50"))
SESSION_STRING = os.environ.get("SESSION_STRING", "")

DATABASE_URL = os.environ["DATABASE_URL"]
RETENTION_DAYS = max(1, int(os.environ.get("RETENTION_DAYS", "30")))        # minimum 1 day
PRUNE_INTERVAL_HOURS = max(1, int(os.environ.get("PRUNE_INTERVAL_HOURS", "24")))  # minimum 1 hour
