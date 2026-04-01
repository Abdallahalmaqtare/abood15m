"""
Aboud Trading Bot - Message Formatter
=======================================
Formats all Telegram messages to match the design style.
Uses emojis and structured layout similar to the reference image.
"""

from datetime import datetime, timezone


def format_signal_message(pair, direction, entry_time, stats):
    """
    Format a trading signal message.

    Args:
        pair: e.g. "EURUSD"
        direction: "CALL" or "PUT"
        entry_time: e.g. "09:15"
        stats: dict with total_wins, total_losses
    """
    direction_emoji = "🟢" if direction == "CALL" else "🔴"
    direction_text = "CALL" if direction == "CALL" else "PUT"

    total = stats.get("total_wins", 0) + stats.get("total_losses", 0)
    wins = stats.get("total_wins", 0)
    losses = stats.get("total_losses", 0)
    win_rate = round((wins / total) * 100) if total > 0 else 0

    msg = (
        f"<b>Aboud Trading 15M POCKETOPTION BOT</b> 🔵\n"
        f"》 ABOUD 15 M 《\n"
        f"\n"
        f"📊 <b>{pair}</b>\n"
        f"{direction_emoji} <b>{direction_text}</b>\n"
        f"🕐 <b>{entry_time}</b>\n"
        f"⏳ <b>15 minutes</b>\n"
        f"\n"
    )

    if total > 0:
        msg += (
            f"Win: {wins} | Loss: {losses} ({win_rate}%)\n"
            f"Pair {pair}: {wins}x{losses} ({win_rate}%)\n"
        )

    return msg


def format_result_message(pair, direction, entry_time, result):
    """
    Format a trade result message.

    Args:
        pair: e.g. "EURUSD"
        direction: "CALL" or "PUT"
        entry_time: e.g. "09:15"
        result: "WIN" or "LOSS"
    """
    if result == "WIN":
        result_emoji = "✅"
        arrow = "⬆️" if direction == "CALL" else "⬇️"
        msg = (
            f"<b>Aboud Trading 15M POCKETOPTION BOT</b> 🔵\n"
            f"\n"
            f"{result_emoji} → {pair} {entry_time} {arrow}\n"
            f"\n"
            f"<b>🏆 WIN!</b>\n"
        )
    else:
        result_emoji = "❌"
        arrow = "⬆️" if direction == "CALL" else "⬇️"
        msg = (
            f"<b>Aboud Trading 15M POCKETOPTION BOT</b> 🔵\n"
            f"\n"
            f"{result_emoji} → {pair} {entry_time} {arrow}\n"
            f"\n"
            f"<b>💔 LOSS</b>\n"
        )

    return msg


def format_stats_message(stats_list):
    """
    Format statistics message.

    Args:
        stats_list: list of dicts with pair stats
    """
    total_wins = sum(s.get("total_wins", 0) for s in stats_list)
    total_losses = sum(s.get("total_losses", 0) for s in stats_list)
    total = total_wins + total_losses
    overall_rate = round((total_wins / total) * 100) if total > 0 else 0

    msg = (
        f"<b>📊 Aboud Trading - Statistics</b>\n"
        f"{'━' * 30}\n"
        f"\n"
        f"<b>📈 Overall Performance:</b>\n"
        f"✅ Total Wins: <b>{total_wins}</b>\n"
        f"❌ Total Losses: <b>{total_losses}</b>\n"
        f"📊 Total Trades: <b>{total}</b>\n"
        f"🎯 Win Rate: <b>{overall_rate}%</b>\n"
        f"\n"
        f"{'━' * 30}\n"
        f"<b>📋 Per Pair Breakdown:</b>\n"
        f"\n"
    )

    for s in stats_list:
        pair = s.get("pair", "?")
        w = s.get("total_wins", 0)
        l = s.get("total_losses", 0)
        t = w + l
        rate = round((w / t) * 100) if t > 0 else 0
        msg += (
            f"  📊 <b>{pair}</b>\n"
            f"     ✅ {w} | ❌ {l} | 🎯 {rate}%\n"
            f"\n"
        )

    return msg


def format_daily_report(daily_stats, today_trades=None):
    """
    Format daily report message.

    Args:
        daily_stats: list of dicts with daily pair stats
        today_trades: list of today's trades (optional)
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    total_d_wins = sum(s.get("daily_wins", 0) for s in daily_stats)
    total_d_losses = sum(s.get("daily_losses", 0) for s in daily_stats)
    total_d = total_d_wins + total_d_losses
    daily_rate = round((total_d_wins / total_d) * 100) if total_d > 0 else 0

    total_wins = sum(s.get("total_wins", 0) for s in daily_stats)
    total_losses = sum(s.get("total_losses", 0) for s in daily_stats)
    total_all = total_wins + total_losses
    overall_rate = round((total_wins / total_all) * 100) if total_all > 0 else 0

    msg = (
        f"<b>📋 Aboud Trading - Daily Report</b>\n"
        f"<b>📅 {date_str}</b>\n"
        f"{'━' * 32}\n"
        f"\n"
        f"<b>📊 Today's Results:</b>\n"
        f"✅ Wins: <b>{total_d_wins}</b>\n"
        f"❌ Losses: <b>{total_d_losses}</b>\n"
        f"📊 Total: <b>{total_d}</b>\n"
        f"🎯 Win Rate: <b>{daily_rate}%</b>\n"
        f"\n"
        f"{'━' * 32}\n"
        f"<b>📈 All-Time Performance:</b>\n"
        f"✅ Wins: <b>{total_wins}</b>\n"
        f"❌ Losses: <b>{total_losses}</b>\n"
        f"📊 Total: <b>{total_all}</b>\n"
        f"🎯 Win Rate: <b>{overall_rate}%</b>\n"
        f"\n"
        f"{'━' * 32}\n"
        f"<b>📋 Per Pair (Today):</b>\n"
        f"\n"
    )

    for s in daily_stats:
        pair = s.get("pair", "?")
        dw = s.get("daily_wins", 0)
        dl = s.get("daily_losses", 0)
        dt = dw + dl
        dr = round((dw / dt) * 100) if dt > 0 else 0
        msg += (
            f"  📊 <b>{pair}</b>: ✅ {dw} | ❌ {dl} | 🎯 {dr}%\n"
        )

    msg += (
        f"\n"
        f"{'━' * 32}\n"
        f"<i>🤖 Aboud Trading Bot v1.0</i>\n"
    )

    return msg


def format_signal_cancelled_message(pair, direction, reason="Signal reversed"):
    """Format message when a pending signal is cancelled."""
    msg = (
        f"<b>Aboud Trading 15M</b>\n"
        f"⚠️ Signal Cancelled\n"
        f"\n"
        f"📊 {pair} | {direction}\n"
        f"📝 Reason: {reason}\n"
    )
    return msg


def format_admin_help():
    """Format admin help message."""
    msg = (
        f"<b>🛠 Aboud Trading - Control Panel</b>\n"
        f"{'━' * 32}\n"
        f"\n"
        f"<b>Available Commands:</b>\n"
        f"\n"
        f"/start - Start the bot\n"
        f"/help - Show this help message\n"
        f"/stats - View current statistics\n"
        f"/daily - View today's report\n"
        f"/enable - Enable signal sending\n"
        f"/disable - Disable signal sending\n"
        f"/reset - Reset all statistics to zero\n"
        f"/status - Check bot status\n"
        f"/pairs - View active trading pairs\n"
        f"\n"
        f"<i>🔒 Admin commands only</i>\n"
    )
    return msg


def format_status_message(signals_enabled, pending_count, today_count):
    """Format bot status message."""
    status_emoji = "🟢" if signals_enabled else "🔴"
    status_text = "ACTIVE" if signals_enabled else "PAUSED"

    msg = (
        f"<b>🤖 Aboud Trading Bot Status</b>\n"
        f"{'━' * 32}\n"
        f"\n"
        f"Signal Status: {status_emoji} <b>{status_text}</b>\n"
        f"Pending Signals: <b>{pending_count}</b>\n"
        f"Today's Trades: <b>{today_count}</b>\n"
        f"Pairs: EURUSD, USDJPY, USDCHF\n"
        f"Timeframe: 15 Minutes\n"
        f"\n"
        f"<i>🤖 Aboud Trading Bot v1.0</i>\n"
    )
    return msg
