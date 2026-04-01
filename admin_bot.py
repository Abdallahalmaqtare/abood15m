"""
Aboud Trading Bot - Admin Bot (Control Panel)
================================================
Handles admin commands via private messages to the bot.
"""

import logging
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from config import ADMIN_USER_IDS, TELEGRAM_CHAT_ID
from database import (
    get_statistics,
    get_daily_stats,
    get_today_trades,
    get_active_pending_signals,
    reset_all_statistics,
    set_setting,
    is_signals_enabled,
)
from messages import (
    format_stats_message,
    format_daily_report,
    format_admin_help,
    format_status_message,
)

logger = logging.getLogger(__name__)


def is_admin(user_id):
    """Check if user is admin. If no admins set, allow anyone."""
    if not ADMIN_USER_IDS:
        return True
    return user_id in ADMIN_USER_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    await update.message.reply_text(
        "🤖 <b>Aboud Trading Bot v1.0</b>\n\n"
        "Welcome! Use /help to see available commands.",
        parse_mode="HTML"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(format_admin_help(), parse_mode="HTML")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command - show statistics."""
    if not is_admin(update.effective_user.id):
        return

    stats = get_statistics()
    text = format_stats_message(stats)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /daily command - show today's report."""
    if not is_admin(update.effective_user.id):
        return

    daily_stats = get_daily_stats()
    today_trades = get_today_trades()
    text = format_daily_report(daily_stats, today_trades)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_enable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /enable command - enable signals."""
    if not is_admin(update.effective_user.id):
        return

    set_setting("signals_enabled", "true")
    await update.message.reply_text(
        "🟢 <b>Signals ENABLED!</b>\n\nThe bot will now send trading signals.",
        parse_mode="HTML"
    )
    logger.info(f"Signals enabled by user {update.effective_user.id}")


async def cmd_disable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /disable command - disable signals."""
    if not is_admin(update.effective_user.id):
        return

    set_setting("signals_enabled", "false")
    await update.message.reply_text(
        "🔴 <b>Signals DISABLED!</b>\n\nThe bot will NOT send trading signals until re-enabled.",
        parse_mode="HTML"
    )
    logger.info(f"Signals disabled by user {update.effective_user.id}")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reset command - reset all statistics."""
    if not is_admin(update.effective_user.id):
        return

    reset_all_statistics()
    await update.message.reply_text(
        "🔄 <b>Statistics RESET!</b>\n\nAll counters have been set to zero.",
        parse_mode="HTML"
    )
    logger.info(f"Statistics reset by user {update.effective_user.id}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - check bot status."""
    if not is_admin(update.effective_user.id):
        return

    signals_on = is_signals_enabled()
    pending = get_active_pending_signals()
    today = get_today_trades()

    text = format_status_message(signals_on, len(pending), len(today))
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_pairs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pairs command - show active pairs."""
    if not is_admin(update.effective_user.id):
        return

    from config import TRADING_PAIRS
    pairs_text = "\n".join([f"  📊 {p}" for p in TRADING_PAIRS])
    await update.message.reply_text(
        f"<b>📋 Active Trading Pairs:</b>\n\n{pairs_text}\n\n"
        f"<i>Timeframe: 15 Minutes</i>",
        parse_mode="HTML"
    )


def setup_admin_handlers(application: Application):
    """Register all admin command handlers."""
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("daily", cmd_daily))
    application.add_handler(CommandHandler("enable", cmd_enable))
    application.add_handler(CommandHandler("disable", cmd_disable))
    application.add_handler(CommandHandler("reset", cmd_reset))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("pairs", cmd_pairs))

    logger.info("Admin command handlers registered")
