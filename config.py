"""
Aboud Trading Bot - Configuration v3.1
FIX: Persistent DB path on Render + startup flag file
"""
import os
from datetime import timezone, timedelta

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ADMIN_USER_IDS = [int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()]

TRADING_PAIRS = ["EURUSD", "USDJPY", "USDCHF"]
TRADE_DURATION_MINUTES = 15
SIGNAL_CONFIRM_MIN_SECONDS = 120
SIGNAL_CONFIRM_MAX_SECONDS = 600
SIGNAL_CONFIRM_CHECK_INTERVAL = 30
SIGNAL_CONFIRM_DELAY_SECONDS = SIGNAL_CONFIRM_MIN_SECONDS

EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
RSI_CALL_MIN = 52
RSI_PUT_MAX = 48
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3
ADX_PERIOD = 14
ADX_MIN_THRESHOLD = 20

TRADING_START_HOUR_UTC = 0
TRADING_END_HOUR_UTC = 24

BOT_UTC_OFFSET = int(os.getenv("BOT_UTC_OFFSET", "3"))
BOT_TIMEZONE = timezone(timedelta(hours=BOT_UTC_OFFSET))

# DATABASE - persistent path on Render
_render_src = "/opt/render/project/src"
if os.path.isdir(_render_src):
    DATABASE_PATH = os.getenv("DATABASE_PATH", f"{_render_src}/aboud_trading.db")
    STARTUP_FLAG_FILE = f"{_render_src}/.bot_started"
else:
    DATABASE_PATH = os.getenv("DATABASE_PATH", "aboud_trading.db")
    STARTUP_FLAG_FILE = ".bot_started"

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "aboud_trading_secret_2024")
WEBHOOK_PORT = int(os.getenv("PORT", "10000"))

DAILY_REPORT_HOUR_UTC = int(os.getenv("DAILY_REPORT_HOUR", "18"))
DAILY_REPORT_MINUTE = 0

SIGNALS_ENABLED = os.getenv("SIGNALS_ENABLED", "true").lower() == "true"
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
