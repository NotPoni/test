import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID") or 0) or None
BRAND = os.getenv("BRAND", "GTA 5RP")
STATUS = os.getenv("STATUS", "GTA 5RP • /помощь")
LOGO_URL = os.getenv("LOGO_URL") or None
BANNER_URL = os.getenv("BANNER_URL") or None
WHITELIST = {int(x) for x in os.getenv("WHITELIST", "").split(",") if x.strip()}

# Палитра: тёмный премиум-стиль с фиолетовым акцентом
COLOR_MAIN = 0x8B5CF6
COLOR_OK = 0x2ECC71
COLOR_ERR = 0xED4245
COLOR_WARN = 0xF1C40F
COLOR_INFO = 0x3498DB
