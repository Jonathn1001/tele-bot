import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

CHANNELS = [ch.strip() for ch in os.environ.get("CHANNELS", "").split(",") if ch.strip()]
BUFFER_SIZE = int(os.environ.get("BUFFER_SIZE", "100"))
MAX_CONTEXT_MESSAGES = int(os.environ.get("MAX_CONTEXT_MESSAGES", "50"))
