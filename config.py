"""
Aboud Trading Bot - Configuration v2
===================================
"""

import os
from datetime import timezone, timedelta

# ============================================
# TELEGRAM SETTINGS
# ============================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ADMIN_USER_IDS = [int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()]

# ============================================
# TRADING SETTINGS
# ============================================
TRADING_PAIRS = ["EURUSD", "USDJPY", "USDCHF"]
TRADE_DURATION_MINUTES = 15
SIGNAL_CONFIRM_DELAY_SECONDS = 120  # 2 minutes

# ============================================
# INDICATOR SETTINGS
# ============================================
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
RSI_CALL_MIN = 52
RSI_PUT_MAX = 48
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3
ADX_PERIOD = 14
ADX_MIN_THRESHOLD = 20

# ============================================
# TRADING HOURS (UTC) - 24/7
# ============================================
TRADING_START_HOUR_UTC = 0
TRADING_END_HOUR_UTC = 24

# ============================================
# TIMEZONE - UTC+3
# ============================================
BOT_UTC_OFFSET = int(os.getenv("BOT_UTC_OFFSET", "3"))
BOT_TIMEZONE = timezone(timedelta(hours=BOT_UTC_OFFSET))

# ============================================
# DATABASE
# ============================================
DATABASE_PATH = os.getenv("DATABASE_PATH", "aboud_trading.db")

# ============================================
# WEBHOOK
# ============================================
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "aboud_trading_secret_2024")
WEBHOOK_PORT = int(os.getenv("PORT", "10000"))

# ============================================
# DAILY REPORT
# ============================================
DAILY_REPORT_HOUR_UTC = int(os.getenv("DAILY_REPORT_HOUR", "18"))  # 18 UTC = 21:00 UTC+3
DAILY_REPORT_MINUTE = 0

# ============================================
# APP SETTINGS
# ============================================
SIGNALS_ENABLED = os.getenv("SIGNALS_ENABLED", "true").lower() == "true"
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
