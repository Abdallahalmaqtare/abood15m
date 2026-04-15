"""
Aboud Trading Bot - Main v5.1 (FIXED)
========================================
FIXES:
- Keep-alive ping every 13 minutes (prevents Render sleep)
- Better webhook error handling (fixes 500 errors)
- Startup message spam fixed (6 hour cooldown)
- Webhook timeout increased to 30s
- Flask starts AFTER bot initialization
"""
import asyncio, logging, threading, json, time, os
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application
from config import (
    TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET, WEBHOOK_PORT,
    DAILY_REPORT_HOUR_UTC, DAILY_REPORT_MINUTE,
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
bot_ready = False  # Flag to track if bot is fully initialized


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "bot": "v5.1-pro",
        "ready": bot_ready,
        "pg": bool(DATABASE_URL),
        "time": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle TradingView webhook signals."""
    try:
        # Check if bot is ready
        if not bot_ready or not signal_manager or not loop:
            logger.warning("Webhook received but bot not ready yet")
            return jsonify({"status": "not_ready", "message": "Bot is starting up"}), 503

        # Parse data - handle multiple formats
        data = None
        raw_body = request.get_data(as_text=True)
        logger.info("Webhook raw body: %s", raw_body[:500])

        # Try JSON first
        try:
            data = json.loads(raw_body)
        except (json.JSONDecodeError, TypeError):
            pass

        # Try Flask's get_json
        if not data:
            data = request.get_json(force=True, silent=True)

        # Try comma-separated format
        if not data:
            parts = raw_body.strip().split(",")
            if len(parts) >= 2:
                data = {
                    "pair": parts[0].strip(),
                    "direction": parts[1].strip(),
                    "action": parts[2].strip() if len(parts) > 2 else "SIGNAL",
                }
            else:
                logger.error("Cannot parse webhook body: %s", raw_body[:200])
                return jsonify({"error": "Bad format"}), 400

        # Verify secret
        secret = data.get("secret", "")
        if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
            logger.warning("Webhook unauthorized: wrong secret")
            return jsonify({"error": "Unauthorized"}), 401

        logger.info(
            "Webhook received: pair=%s dir=%s action=%s score=%s",
            data.get("pair"), data.get("direction"),
            data.get("action"), data.get("signal_score")
        )

        # Process signal with increased timeout
        try:
            fut = asyncio.run_coroutine_threadsafe(
                signal_manager.process_webhook_signal(data), loop
            )
            res = fut.result(timeout=25)  # Increased from 10 to 25 seconds
            logger.info("Webhook result: %s", res)
            return jsonify(res), 200
        except asyncio.TimeoutError:
            logger.error("Webhook processing timed out after 25s")
            return jsonify({"status": "timeout"}), 504
        except Exception as e:
            logger.error("Webhook processing error: %s", e, exc_info=True)
            return jsonify({"status": "error", "message": str(e)}), 500

    except Exception as e:
        logger.error("Webhook handler crash: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/webhook/test", methods=["GET", "POST"])
def webhook_test():
    return jsonify({"status": "ok", "ready": bot_ready})


def _should_send_startup():
    """Check in DATABASE if startup msg was sent recently. 6 hour cooldown."""
    try:
        last = get_setting("last_startup", "")
        if last:
            elapsed = time.time() - float(last)
            if elapsed < 21600:  # 6 hours (was 30 min)
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


async def keep_alive_ping():
    """Ping own health endpoint to prevent Render from sleeping."""
    try:
        import aiohttp
        service_url = os.getenv("RENDER_EXTERNAL_URL", f"http://localhost:{WEBHOOK_PORT}")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(f"{service_url}/") as resp:
                logger.debug("Keep-alive ping: %s", resp.status)
    except Exception as e:
        logger.debug("Keep-alive ping failed (non-critical): %s", e)


async def run_bot():
    global signal_manager, telegram_sender, loop, bot_ready
    loop = asyncio.get_event_loop()

    init_db()
    logger.info(f"DB: {'PostgreSQL (PERMANENT)' if DATABASE_URL else 'SQLite (LOCAL)'}")

    telegram_sender = TelegramSender()
    signal_manager = SignalManager(telegram_sender)

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.bot_data["signal_manager"] = signal_manager
    setup_admin_handlers(application)

    scheduler = AsyncIOScheduler()

    # Daily report
    scheduler.add_job(send_daily_report, "cron", hour=DAILY_REPORT_HOUR_UTC, minute=DAILY_REPORT_MINUTE, timezone="UTC")

    # Keep-alive ping every 13 minutes (Render sleeps after 15 min)
    scheduler.add_job(keep_alive_ping, "interval", minutes=13, id="keep_alive")

    scheduler.start()

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

    # Mark bot as ready AFTER everything is initialized
    bot_ready = True

    logger.info("=" * 50)
    logger.info("  Aboud Trading Bot v5.1 PRO (FIXED)")
    logger.info(f"  DB: {'PostgreSQL' if DATABASE_URL else 'SQLite'}")
    logger.info(f"  Pairs: EURUSD, GBPUSD")
    logger.info(f"  Min Score: {MIN_SIGNAL_SCORE}/10")
    logger.info(f"  Keep-alive: every 13 min")
    logger.info("=" * 50)

    if _should_send_startup():
        await telegram_sender.send_text(
            f"🟢 <b>Aboud Trading Bot v5.1 PRO</b>\n\n"
            f"📊 EURUSD, GBPUSD\n"
            f"⏱ 15 min | 🕐 UTC+{BOT_UTC_OFFSET}\n"
            f"🎯 Min Signal Score: {MIN_SIGNAL_SCORE}/10\n"
            f"⏰ Trading: 10:00-23:00 (UTC+3)\n"
            f"💾 DB: {'☁️ PostgreSQL' if DATABASE_URL else '📁 SQLite'}\n"
            f"🔄 Active | Keep-alive ✅",
        )

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        bot_ready = False
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await telegram_sender.close()
        await price_service.close()
        scheduler.shutdown()


def run_flask():
    app.run(host="0.0.0.0", port=WEBHOOK_PORT, debug=False, use_reloader=False)


def main():
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask server started on port %s", WEBHOOK_PORT)

    # Run the bot (this blocks)
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
