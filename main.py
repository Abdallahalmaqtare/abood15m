"""
Aboud Trading Bot - Main v3
==============================
FIX: No repeated startup messages.
     Bot sends startup msg only ONCE, tracked in DB.
     Stable all day.
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
    TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET, WEBHOOK_PORT,
    DAILY_REPORT_HOUR_UTC, DAILY_REPORT_MINUTE,
    TRADING_START_HOUR_UTC, TRADING_END_HOUR_UTC,
    SIGNAL_CONFIRM_MIN_SECONDS, SIGNAL_CONFIRM_MAX_SECONDS,
    BOT_UTC_OFFSET, DEBUG,
)
from database import init_db, get_daily_stats, get_today_trades, is_signals_enabled, get_setting, set_setting
from signal_manager import SignalManager
from telegram_sender import TelegramSender
from price_service import price_service
from admin_bot import setup_admin_handlers

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("AboudTrading")

app = Flask(__name__)

signal_manager = None
telegram_sender = None
loop = None


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "bot": "Aboud Trading Bot v3.0",
        "signals_enabled": is_signals_enabled(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            raw = request.get_data(as_text=True)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                parts = raw.strip().split(",")
                if len(parts) >= 2:
                    data = {
                        "pair": parts[0].strip(),
                        "direction": parts[1].strip(),
                        "action": parts[2].strip() if len(parts) > 2 else "SIGNAL",
                    }
                else:
                    return jsonify({"error": "Invalid format"}), 400

        secret = data.get("secret", "")
        if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
            return jsonify({"error": "Unauthorized"}), 401

        logger.info(f"Webhook: {json.dumps(data, default=str)}")

        if signal_manager and loop:
            future = asyncio.run_coroutine_threadsafe(
                signal_manager.process_webhook_signal(data), loop
            )
            result = future.result(timeout=10)
            return jsonify(result), 200
        else:
            return jsonify({"error": "Not initialized"}), 503

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/webhook/test", methods=["GET", "POST"])
def webhook_test():
    return jsonify({"status": "ok", "message": "Webhook active"})


async def send_daily_report():
    try:
        daily = get_daily_stats()
        today = get_today_trades()
        await telegram_sender.send_daily_report(daily, today)
        logger.info("Daily report sent")
    except Exception as e:
        logger.error(f"Daily report error: {e}", exc_info=True)


async def run_bot():
    global signal_manager, telegram_sender, loop

    loop = asyncio.get_event_loop()

    init_db()
    logger.info("Database initialized")

    telegram_sender = TelegramSender()
    signal_manager = SignalManager(telegram_sender)

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Store signal_manager in bot_data so admin_bot can access it
    application.bot_data["signal_manager"] = signal_manager

    setup_admin_handlers(application)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_daily_report, "cron",
        hour=DAILY_REPORT_HOUR_UTC, minute=DAILY_REPORT_MINUTE, timezone="UTC",
    )
    scheduler.start()

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

    logger.info("=" * 50)
    logger.info("  Aboud Trading Bot v3.0 - STARTED")
    logger.info(f"  Timezone: UTC+{BOT_UTC_OFFSET}")
    logger.info(f"  Confirm window: {SIGNAL_CONFIRM_MIN_SECONDS}-{SIGNAL_CONFIRM_MAX_SECONDS}s")
    logger.info("=" * 50)

    # FIX: Only send startup message ONCE per deploy, not on every restart/ping
    last_start = get_setting("last_startup_id", "")
    import os
    current_deploy = os.getenv("RENDER_GIT_COMMIT", "local")[:8]
    if last_start != current_deploy:
        set_setting("last_startup_id", current_deploy)
        await telegram_sender.send_text(
            f"🟢 <b>Aboud Trading Bot v3.0 Started!</b>\n\n"
            f"📊 Pairs: EURUSD, USDJPY, USDCHF\n"
            f"⏱ Timeframe: 15 minutes\n"
            f"🕐 Timezone: UTC+{BOT_UTC_OFFSET}\n"
            f"⏳ Signal confirm: {SIGNAL_CONFIRM_MIN_SECONDS//60}-{SIGNAL_CONFIRM_MAX_SECONDS//60} min\n"
            f"🔒 One trade at a time\n"
            f"🔄 Status: Active",
        )

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await telegram_sender.close()
        await price_service.close()
        scheduler.shutdown()


def run_flask():
    app.run(host="0.0.0.0", port=WEBHOOK_PORT, debug=False, use_reloader=False)


def main():
    logger.info("Starting Aboud Trading Bot v3.0...")
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    logger.info(f"Flask on port {WEBHOOK_PORT}")
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
