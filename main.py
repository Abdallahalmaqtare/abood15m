"""
Aboud Trading Bot - Main Application
=======================================
Entry point for the complete trading bot system.

Components:
1. Flask webhook server (receives TradingView alerts)
2. Telegram bot (admin control panel)
3. Signal manager (2-minute confirmation logic)
4. Result checker (automatic Win/Loss after 15 min)
5. Daily report scheduler
"""

import asyncio
import logging
import threading
import json
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

from config import (
    TELEGRAM_BOT_TOKEN,
    WEBHOOK_SECRET,
    WEBHOOK_PORT,
    DAILY_REPORT_HOUR_UTC,
    DAILY_REPORT_MINUTE,
    TRADING_START_HOUR_UTC,
    TRADING_END_HOUR_UTC,
    SIGNAL_CONFIRM_DELAY_SECONDS,
    DEBUG,
)
from database import init_db, get_daily_stats, get_today_trades, is_signals_enabled
from signal_manager import SignalManager
from telegram_sender import TelegramSender
from price_service import price_service
from admin_bot import setup_admin_handlers

# ============================================
# LOGGING SETUP
# ============================================
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("AboudTrading")

# ============================================
# FLASK APP (Webhook Receiver)
# ============================================
app = Flask(__name__)

# Global references (set during startup)
signal_manager = None
telegram_sender = None
loop = None


@app.route("/", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "bot": "Aboud Trading Bot v1.0",
        "signals_enabled": is_signals_enabled(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Receive TradingView webhook alerts.

    Expected JSON payload:
    {
        "secret": "your_webhook_secret",
        "pair": "EURUSD",
        "direction": "CALL",
        "action": "SIGNAL",
        "indicators": {
            "ema_fast": 1.0850,
            "ema_slow": 1.0830,
            "rsi": 55.2,
            "supertrend": "UP",
            "adx": 25.3
        }
    }
    """
    try:
        # Try to parse JSON
        data = request.get_json(force=True, silent=True)

        if not data:
            # Try plain text (TradingView sometimes sends as text)
            raw = request.get_data(as_text=True)
            logger.info(f"Raw webhook data: {raw}")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Try to parse simple format: "EURUSD,CALL,SIGNAL"
                parts = raw.strip().split(",")
                if len(parts) >= 2:
                    data = {
                        "pair": parts[0].strip(),
                        "direction": parts[1].strip(),
                        "action": parts[2].strip() if len(parts) > 2 else "SIGNAL",
                    }
                else:
                    return jsonify({"error": "Invalid data format"}), 400

        # Verify webhook secret (optional but recommended)
        secret = data.get("secret", "")
        if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
            logger.warning(f"Invalid webhook secret received")
            return jsonify({"error": "Unauthorized"}), 401

        logger.info(f"Webhook received: {json.dumps(data, default=str)}")

        # Process the signal asynchronously
        if signal_manager and loop:
            future = asyncio.run_coroutine_threadsafe(
                signal_manager.process_webhook_signal(data),
                loop
            )
            result = future.result(timeout=10)
            return jsonify(result), 200
        else:
            return jsonify({"error": "Bot not initialized"}), 503

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/webhook/test", methods=["GET", "POST"])
def webhook_test():
    """Test endpoint to verify webhook is working."""
    return jsonify({
        "status": "ok",
        "message": "Webhook endpoint is active",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


# ============================================
# DAILY REPORT SCHEDULER
# ============================================
async def send_daily_report():
    """Send the daily report at scheduled time."""
    try:
        logger.info("Generating daily report...")
        daily_stats = get_daily_stats()
        today_trades = get_today_trades()
        await telegram_sender.send_daily_report(daily_stats, today_trades)
        logger.info("Daily report sent successfully")
    except Exception as e:
        logger.error(f"Failed to send daily report: {e}", exc_info=True)


# ============================================
# MAIN STARTUP
# ============================================
async def run_bot():
    """Run the Telegram bot and scheduler."""
    global signal_manager, telegram_sender, loop

    loop = asyncio.get_event_loop()

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Initialize Telegram sender
    telegram_sender = TelegramSender()
    logger.info("Telegram sender initialized")

    # Initialize signal manager
    signal_manager = SignalManager(telegram_sender)
    logger.info("Signal manager initialized")

    # Initialize Telegram bot (admin commands)
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    setup_admin_handlers(application)

    # Initialize scheduler for daily reports
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_daily_report,
        "cron",
        hour=DAILY_REPORT_HOUR_UTC,
        minute=DAILY_REPORT_MINUTE,
        timezone="UTC",
    )
    scheduler.start()
    logger.info(f"Daily report scheduled at {DAILY_REPORT_HOUR_UTC:02d}:{DAILY_REPORT_MINUTE:02d} UTC")

    # Start the Telegram bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

    logger.info("=" * 50)
    logger.info("  Aboud Trading Bot v1.0 - STARTED")
    logger.info("=" * 50)
    logger.info(f"  Pairs: EURUSD, USDJPY, USDCHF")
    logger.info(f"  Timeframe: 15 minutes")
    logger.info(f"  Trading hours: {TRADING_START_HOUR_UTC}:00 - {TRADING_END_HOUR_UTC}:00 UTC")
    logger.info(f"  Signal confirm delay: {SIGNAL_CONFIRM_DELAY_SECONDS}s")
    logger.info(f"  Signals enabled: {is_signals_enabled()}")
    logger.info("=" * 50)

    # Send startup notification
    await telegram_sender.send_text(
        "🟢 <b>Aboud Trading Bot Started!</b>\n\n"
        "📊 Pairs: EURUSD, USDJPY, USDCHF\n"
        "⏱ Timeframe: 15 minutes\n"
        "🔄 Status: Active\n\n"
        "Use /help for control panel commands.",
        chat_id=None  # Sends to the channel
    )

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await telegram_sender.close()
        await price_service.close()
        scheduler.shutdown()


def run_flask():
    """Run Flask in a separate thread."""
    app.run(
        host="0.0.0.0",
        port=WEBHOOK_PORT,
        debug=False,
        use_reloader=False,
    )


def main():
    """Main entry point."""
    logger.info("Starting Aboud Trading Bot...")

    # Run Flask webhook server in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask webhook server started on port {WEBHOOK_PORT}")

    # Run the async bot
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
