"""
Aboud Trading Bot - Main v5.0 (UPGRADED)
==========================================
Updated pairs: EURUSD + GBPUSD
Signal scoring system integrated.
"""
import asyncio, logging, threading, json, time
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application
from config import (
    TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET, WEBHOOK_PORT,
    DAILY_REPORT_HOUR_UTC, DAILY_REPORT_MINUTE,
    SIGNAL_CONFIRM_MIN_SECONDS, SIGNAL_CONFIRM_MAX_SECONDS,
    BOT_UTC_OFFSET, DEBUG, DATABASE_URL,
    MIN_SIGNAL_SCORE,
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
    return jsonify({"status": "ok", "bot": "v5-pro", "pg": bool(DATABASE_URL)})


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
                    data = {"pair": parts[0].strip(), "direction": parts[1].strip(),
                            "action": parts[2].strip() if len(parts) > 2 else "SIGNAL"}
                else:
                    return jsonify({"error": "Bad format"}), 400

        secret = data.get("secret", "")
        if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
            return jsonify({"error": "Unauthorized"}), 401

        if signal_manager and loop:
            fut = asyncio.run_coroutine_threadsafe(signal_manager.process_webhook_signal(data), loop)
            res = fut.result(timeout=10)
            return jsonify(res), 200
        return jsonify({"error": "Not init"}), 503
    except Exception as e:
        logger.error(f"Webhook err: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/webhook/test", methods=["GET", "POST"])
def webhook_test():
    return jsonify({"status": "ok"})


def _should_send_startup():
    """Check in DATABASE if startup msg was sent recently. DB = permanent!"""
    try:
        last = get_setting("last_startup", "")
        if last:
            elapsed = time.time() - float(last)
            if elapsed < 1800:  # 30 min
                logger.info(f"Startup msg skipped ({elapsed:.0f}s ago)")
                return False
        set_setting("last_startup", str(time.time()))
        return True
    except Exception as e:
        logger.warning(f"Startup check err: {e}")
        return True


async def send_daily_report():
    try:
        await telegram_sender.send_daily_report(get_daily_stats(), get_today_trades())
    except Exception as e:
        logger.error(f"Daily report err: {e}", exc_info=True)


async def run_bot():
    global signal_manager, telegram_sender, loop
    loop = asyncio.get_event_loop()

    init_db()
    logger.info(f"DB: {'PostgreSQL (PERMANENT)' if DATABASE_URL else 'SQLite (LOCAL)'}")

    telegram_sender = TelegramSender()
    signal_manager = SignalManager(telegram_sender)

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.bot_data["signal_manager"] = signal_manager
    setup_admin_handlers(application)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_report, "cron", hour=DAILY_REPORT_HOUR_UTC, minute=DAILY_REPORT_MINUTE, timezone="UTC")
    scheduler.start()

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

    logger.info("=" * 50)
    logger.info("  Aboud Trading Bot v5.0 PRO")
    logger.info(f"  DB: {'PostgreSQL' if DATABASE_URL else 'SQLite'}")
    logger.info(f"  Pairs: EURUSD, GBPUSD")
    logger.info(f"  Min Score: {MIN_SIGNAL_SCORE}/10")
    logger.info("=" * 50)

    if _should_send_startup():
        await telegram_sender.send_text(
            f"🟢 <b>Aboud Trading Bot v5.0 PRO</b>\n\n",
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
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
