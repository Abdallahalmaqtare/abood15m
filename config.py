"""
Aboud Trading Bot - Configuration v3.2
"""
import os
from datetime import timezone, timedelta

# ============================================
# TELEGRAM
# ============================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ADMIN_USER_IDS = [int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()]

# ============================================
# TRADING
# ============================================
TRADING_PAIRS = ["EURUSD", "USDJPY", "USDCHF"]
TRADE_DURATION_MINUTES = 15

# Signal confirmation: wait 2-10 minutes
# The bot checks every 30s if conditions still hold
SIGNAL_CONFIRM_MIN_SECONDS = 120   # minimum 2 minutes
SIGNAL_CONFIRM_MAX_SECONDS = 600   # maximum 10 minutes
SIGNAL_CONFIRM_CHECK_INTERVAL = 30 # re-check every 30 seconds

# Legacy (kept for compatibility)
SIGNAL_CONFIRM_DELAY_SECONDS = SIGNAL_CONFIRM_MIN_SECONDS

# ============================================
# INDICATORS
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
# TRADING HOURS (24/7)
# ============================================
TRADING_START_HOUR_UTC = 0
TRADING_END_HOUR_UTC = 24

# ============================================
# TIMEZONE UTC+3
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
DAILY_REPORT_HOUR_UTC = int(os.getenv("DAILY_REPORT_HOUR", "18"))
DAILY_REPORT_MINUTE = 0

# ============================================
# RESULT VERIFICATION
# ============================================
RESULT_CANDLE_LOOKBACK_DAYS = int(os.getenv("RESULT_CANDLE_LOOKBACK_DAYS", "5"))
RESULT_FETCH_RETRY_SECONDS = int(os.getenv("RESULT_FETCH_RETRY_SECONDS", "6"))
RESULT_MAX_WAIT_AFTER_EXPIRY_SECONDS = int(os.getenv("RESULT_MAX_WAIT_AFTER_EXPIRY_SECONDS", "90"))
RESULT_CANDLE_BUFFER_SECONDS = int(os.getenv("RESULT_CANDLE_BUFFER_SECONDS", "4"))

# ============================================
# APP
# ============================================
SIGNALS_ENABLED = os.getenv("SIGNALS_ENABLED", "true").lower() == "true"
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
