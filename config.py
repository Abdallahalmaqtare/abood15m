"""
Aboud Trading Bot - Configuration (FIXED)
============================================
All configuration settings for the trading bot.

FIX: Default timezone changed to UTC+3
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
# Pairs to trade
TRADING_PAIRS = ["EURUSD", "USDJPY", "USDCHF"]

# Signal expiry in minutes (trade duration)
TRADE_DURATION_MINUTES = 15

# Time to wait before confirming a temporary signal (seconds)
SIGNAL_CONFIRM_DELAY_SECONDS = 120  # 2 minutes

# Minimum seconds before candle open to send signal
MIN_SECONDS_BEFORE_ENTRY = 30

# ============================================
# INDICATOR SETTINGS
# ============================================
# EMA
EMA_FAST = 20
EMA_SLOW = 50

# RSI
RSI_PERIOD = 14
RSI_CALL_MIN = 52
RSI_PUT_MAX = 48

# Supertrend
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3

# ADX
ADX_PERIOD = 14
ADX_MIN_THRESHOLD = 20

# ============================================
# TRADING HOURS (UTC)
# ============================================
TRADING_START_HOUR_UTC = 7   # 07:00 UTC
TRADING_END_HOUR_UTC = 18    # 18:00 UTC

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
# PRICE DATA SOURCE
# ============================================
# We use a free forex API for price checking
PRICE_API_URL = "https://open.er-api.com/v6/latest/"
# Alternative: using TradingView webhook data itself

# ============================================
# TIMEZONE
# ============================================
# ===== FIX 2: Default timezone is now UTC+3 =====
BOT_UTC_OFFSET = int(os.getenv("BOT_UTC_OFFSET", "3"))
BOT_TIMEZONE = timezone(timedelta(hours=BOT_UTC_OFFSET))

# ============================================
# DAILY REPORT
# ============================================
# NOTE: This hour is in UTC. For UTC+3, set to 18 to get 21:00 local time
DAILY_REPORT_HOUR_UTC = int(os.getenv("DAILY_REPORT_HOUR", "18"))  # 18 UTC = 21:00 UTC+3
DAILY_REPORT_MINUTE = 0

# ============================================
# APP SETTINGS
# ============================================
SIGNALS_ENABLED = os.getenv("SIGNALS_ENABLED", "true").lower() == "true"
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
