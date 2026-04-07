"""
Aboud Trading Bot - Admin Bot v3
==================================
All buttons from the image working:
/start, /stats, /overall, /recent, /active, /close, /news, /enable, /disable, /help
Removed: /price (not needed)
"""
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes
from config import ADMIN_USER_IDS, TRADING_PAIRS, BOT_UTC_OFFSET
from database import (
    get_statistics, get_daily_stats, get_today_trades,
    get_active_pending_signals, reset_all_statistics,
    set_setting, is_signals_enabled, get_recent_trades,
    get_active_trade, force_close_trade, get_pending_trades,
)
from messages import (
    format_stats_message, format_daily_report,
    format_admin_help, format_status_message,
    format_recent_trades, format_active_trade,
    format_overall_stats,
)
from news_service import fetch_upcoming_news, format_news_message

logger = logging.getLogger(__name__)

# Keyboard layout matching the image
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("/start"), KeyboardButton("/stats")],
        [KeyboardButton("/overall"), KeyboardButton("/recent")],
        [KeyboardButton("/active"), KeyboardButton("/close")],
        [KeyboardButton("/news"), KeyboardButton("/enable")],
        [KeyboardButton("/disable"), KeyboardButton("/help")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)


def is_admin(user_id):
    if not ADMIN_USER_IDS:
        return True
    return user_id in ADMIN_USER_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🤖 <b>Aboud Trading Bot v3.0</b>\n\n"
        "مرحباً! اختر أمر من القائمة:",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(format_admin_help(), parse_mode="HTML", reply_markup=MAIN_KEYBOARD)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Today's stats."""
    if not is_admin(update.effective_user.id):
        return
    daily = get_daily_stats()
    today = get_today_trades()
    text = format_daily_report(daily, today)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_overall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """All-time cumulative stats."""
    if not is_admin(update.effective_user.id):
        return
    stats = get_statistics()
    text = format_overall_stats(stats)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Last 10 trades."""
    if not is_admin(update.effective_user.id):
        return
    trades = get_recent_trades(10)
    text = format_recent_trades(trades)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current active trade."""
    if not is_admin(update.effective_user.id):
        return
    trade = get_active_trade()
    text = format_active_trade(trade)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually close active trade as LOSS."""
    if not is_admin(update.effective_user.id):
        return
    trade = get_active_trade()
    if not trade:
        await update.message.reply_text("❌ لا توجد صفقة نشطة حالياً.")
        return

    force_close_trade(trade["id"], "LOSS")

    # Also clear signal manager active trade if possible
    app_data = context.application.bot_data
    signal_mgr = app_data.get("signal_manager")
    if signal_mgr:
        import asyncio
        async with signal_mgr.active_trade_lock:
            signal_mgr.active_trade = None

    await update.message.reply_text(
        f"✅ تم إغلاق الصفقة #{trade['id']} يدوياً\n"
        f"📊 {trade['pair']} | {trade['direction']}\n"
        f"📝 النتيجة: LOSS (إغلاق يدوي)",
        parse_mode="HTML"
    )


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch upcoming news from ForexFactory."""
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("⏳ جاري جلب الأخبار...")
    news = await fetch_upcoming_news(15)
    text = format_news_message(news)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_enable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_setting("signals_enabled", "true")
    await update.message.reply_text("🟢 <b>Signals ENABLED!</b>", parse_mode="HTML")


async def cmd_disable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_setting("signals_enabled", "false")
    await update.message.reply_text(
        "🔴 <b>Signals DISABLED!</b>\n\nThe bot will NOT send trading signals until re-enabled.",
        parse_mode="HTML"
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    reset_all_statistics()
    await update.message.reply_text("🔄 <b>Statistics RESET!</b>\nAll counters set to zero.", parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    signals_on = is_signals_enabled()
    pending = get_active_pending_signals()
    today = get_today_trades()
    await update.message.reply_text(
        format_status_message(signals_on, len(pending), len(today)),
        parse_mode="HTML"
    )


async def cmd_pairs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    pairs_text = "\n".join([f"  📊 {p}" for p in TRADING_PAIRS])
    await update.message.reply_text(
        f"<b>📋 Active Trading Pairs:</b>\n\n{pairs_text}\n\n<i>Timeframe: 15 Minutes</i>",
        parse_mode="HTML"
    )


def setup_admin_handlers(application: Application):
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("overall", cmd_overall))
    application.add_handler(CommandHandler("recent", cmd_recent))
    application.add_handler(CommandHandler("active", cmd_active))
    application.add_handler(CommandHandler("close", cmd_close))
    application.add_handler(CommandHandler("news", cmd_news))
    application.add_handler(CommandHandler("enable", cmd_enable))
    application.add_handler(CommandHandler("disable", cmd_disable))
    application.add_handler(CommandHandler("reset", cmd_reset))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("pairs", cmd_pairs))
    logger.info("Admin command handlers registered")
