"""
Aboud Trading Bot - Configuration v4.0 (UPGRADED)
===================================================
Changes:
- Removed USDJPY + USDCHF
- Added GBPUSD as second pair
- Faster signal confirmation (30-180 seconds)
- Stricter indicator parameters
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
# TRADING - UPDATED PAIRS
# ============================================
TRADING_PAIRS = ["EURUSD", "GBPUSD"]
TRADE_DURATION_MINUTES = 15

# Signal confirmation: FASTER (30s - 180s)
# The bot checks every 15s if conditions still hold
SIGNAL_CONFIRM_MIN_SECONDS = 30    # minimum 30 seconds (was 120)
SIGNAL_CONFIRM_MAX_SECONDS = 180   # maximum 3 minutes (was 600)
SIGNAL_CONFIRM_CHECK_INTERVAL = 15 # re-check every 15 seconds (was 30)

# Legacy (kept for compatibility)
SIGNAL_CONFIRM_DELAY_SECONDS = SIGNAL_CONFIRM_MIN_SECONDS

# ============================================
# INDICATORS - STRICTER PARAMETERS
# ============================================
EMA_FAST = 9
EMA_MID = 21
EMA_SLOW = 50
EMA_TREND = 200
RSI_PERIOD = 14
RSI_CALL_MIN = 55
RSI_PUT_MAX = 45
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 2.0
ADX_PERIOD = 14
ADX_MIN_THRESHOLD = 25
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ============================================
# SIGNAL SCORING THRESHOLDS
# ============================================
MIN_SIGNAL_SCORE = 7           # Minimum score out of 10 to fire signal
STRONG_SIGNAL_SCORE = 8        # Score for "strong" signal label

# ============================================
# TRADING HOURS - London/NY Overlap (best liquidity)
# ============================================
TRADING_START_HOUR_UTC = 7     # 07:00 UTC = 10:00 UTC+3
TRADING_END_HOUR_UTC = 20      # 20:00 UTC = 23:00 UTC+3

# ============================================
# SIGNAL COOLDOWN
# ============================================
SIGNAL_COOLDOWN_MINUTES = 30   # Min time between signals on same pair

# ============================================
# TIMEZONE UTC+3
# ============================================
BOT_UTC_OFFSET = int(os.getenv("BOT_UTC_OFFSET", "3"))
BOT_TIMEZONE = timezone(timedelta(hours=BOT_UTC_OFFSET))

# ============================================
# DATABASE
# ============================================
DATABASE_PATH = os.getenv("DATABASE_PATH", "aboud_trading.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)


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
