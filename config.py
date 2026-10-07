from os import getenv

from dotenv import load_dotenv

load_dotenv()

API_ID = int(getenv("API_ID"))
API_HASH = getenv("API_HASH", "")
BOT_TOKEN = getenv("BOT_TOKEN")
HEROKU_API_KEY = getenv("HEROKU_API_KEY", "")

# Space-separated Telegram user IDs allowed to control the bot (no default on purpose)
OWNER_ID = list(map(int, getenv("OWNER_ID", "").split()))

# Optional: chat ID (user / group / channel) that gets a message when the bot starts
try:
    LOGGER_ID = int(getenv("LOGGER_ID", "0"))
except ValueError:
    LOGGER_ID = 0

# Optional: needed only for the "Push to GitHub" button (token with write access to the target repo)
GITHUB_TOKEN = getenv("GITHUB_TOKEN", "")
GIT_USER_NAME = getenv("GIT_USER_NAME", "Heroku Bot")
GIT_USER_EMAIL = getenv("GIT_USER_EMAIL", "heroku-bot@users.noreply.github.com")
