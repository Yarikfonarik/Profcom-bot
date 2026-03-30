import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ADMIN_IDS = set(map(int, os.environ.get("ADMIN_IDS", "593577422").split(",")))
