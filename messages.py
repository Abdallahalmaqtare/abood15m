"""
Aboud Trading Bot - Messages v4.0 (UPGRADED)
==============================================
Updated for EURUSD + GBPUSD
Added signal score display
All display times in UTC+3
"""
from datetime import datetime
from config import BOT_TIMEZONE, BOT_UTC_OFFSET


def _now():
    return datetime.now(BOT_TIMEZONE)


def _score_label(score):
    """Return Arabic label for signal score."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "—"
    if s >= 9:
        return "🔥 قوية جداً"
    elif s >= 8:
        return "💪 قوية"
    elif s >= 7:
        return "✅ جيدة"
    else:
        return "⚠️ ضعيفة"


def format_signal_message(pair, direction, entry_time, stats, score=None):
    de = "🟢" if direction == "CALL" else "🔴"
    w = stats.get("total_wins", 0)
    l = stats.get("total_losses", 0)
    t = w + l
    r = round((w / t) * 100) if t > 0 else 0

    score_display = ""
    if score is not None:
        score_display = (
            f"📊 <b>قوة الإشارة: {score}/10</b> ({_score_label(score)})\n"
        )

    msg = (
        f"<b>Aboud Trading 15M POCKETOPTION BOT</b> 🔵\n"
        f"》 ABOUD PRO 15M 《\n\n"
        f"📊 <b>{pair}</b>\n"
        f"{de} <b>{direction}</b>\n"
        f"🕐 <b>{entry_time}</b>\n"
        f"⏳ <b>15 minutes</b>\n\n"
        f"{score_display}"
    )
    if t > 0:
        msg += f"Win: {w} | Loss: {l} ({r}%)\nPair {pair}: {w}x{l} ({r}%)\n"
    return msg


def format_result_message(pair, direction, entry_time, result):
    arrow = "⬆️" if direction == "CALL" else "⬇️"
    if result == "WIN":
        return (
            f"<b>Aboud Trading 15M POCKETOPTION BOT</b> 🔵\n\n"
            f"✅ → {pair} {entry_time} {arrow}\n\n"
            f"<b>🏆 WIN!</b>\n"
        )
    else:
        return (
            f"<b>Aboud Trading 15M POCKETOPTION BOT</b> 🔵\n\n"
            f"❌ → {pair} {entry_time} {arrow}\n\n"
            f"<b>💔 LOSS</b>\n"
        )


def format_stats_message(stats_list):
    tw = sum(s.get("total_wins", 0) for s in stats_list)
    tl = sum(s.get("total_losses", 0) for s in stats_list)
    t = tw + tl
    r = round((tw / t) * 100) if t > 0 else 0

    msg = (
        f"<b>📊 Aboud Trading - Statistics</b>\n"
        f"{'━' * 30}\n\n"
        f"✅ Wins: <b>{tw}</b> | ❌ Losses: <b>{tl}</b>\n"
        f"📊 Total: <b>{t}</b> | 🎯 Rate: <b>{r}%</b>\n\n"
    )
    for s in stats_list:
        p = s.get("pair", "?")
        w = s.get("total_wins", 0)
        l = s.get("total_losses", 0)
        st = w + l
        sr = round((w / st) * 100) if st > 0 else 0
        msg += f"  📊 <b>{p}</b>: ✅ {w} | ❌ {l} | 🎯 {sr}%\n"
    return msg


def format_overall_stats(stats_list):
    """All-time cumulative statistics."""
    tw = sum(s.get("total_wins", 0) for s in stats_list)
    tl = sum(s.get("total_losses", 0) for s in stats_list)
    t = tw + tl
    r = round((tw / t) * 100) if t > 0 else 0

    msg = (
        f"<b>📈 الإحصائيات التراكمية</b>\n"
        f"{'━' * 32}\n\n"
        f"✅ إجمالي الأرباح: <b>{tw}</b>\n"
        f"❌ إجمالي الخسائر: <b>{tl}</b>\n"
        f"📊 إجمالي الصفقات: <b>{t}</b>\n"
        f"🎯 نسبة النجاح: <b>{r}%</b>\n\n"
        f"{'━' * 32}\n"
        f"<b>تفصيل حسب الزوج:</b>\n\n"
    )
    for s in stats_list:
        p = s.get("pair", "?")
        w = s.get("total_wins", 0)
        l = s.get("total_losses", 0)
        st = w + l
        sr = round((w / st) * 100) if st > 0 else 0
        msg += f"  📊 <b>{p}</b>: ✅ {w} | ❌ {l} | 🎯 {sr}%\n"

    msg += f"\n<i>🤖 Aboud Trading Bot v4.0 PRO</i>\n"
    return msg


def format_daily_report(daily_stats, today_trades=None):
    now = _now()
    dw = sum(s.get("daily_wins", 0) for s in daily_stats)
    dl = sum(s.get("daily_losses", 0) for s in daily_stats)
    dt = dw + dl
    dr = round((dw / dt) * 100) if dt > 0 else 0

    tw = sum(s.get("total_wins", 0) for s in daily_stats)
    tl = sum(s.get("total_losses", 0) for s in daily_stats)
    ta = tw + tl
    tr = round((tw / ta) * 100) if ta > 0 else 0

    msg = (
        f"<b>📋 إحصائيات اليوم</b>\n"
        f"<b>📅 {now.strftime('%Y-%m-%d')}</b>\n"
        f"{'━' * 32}\n\n"
        f"✅ أرباح: <b>{dw}</b> | ❌ خسائر: <b>{dl}</b>\n"
        f"📊 المجموع: <b>{dt}</b> | 🎯 النسبة: <b>{dr}%</b>\n\n"
        f"{'━' * 32}\n"
        f"<b>📈 الإجمالي الكلي:</b>\n"
        f"✅ {tw} | ❌ {tl} | 🎯 {tr}%\n\n"
    )

    for s in daily_stats:
        p = s.get("pair", "?")
        w = s.get("daily_wins", 0)
        l = s.get("daily_losses", 0)
        st = w + l
        sr = round((w / st) * 100) if st > 0 else 0
        msg += f"  📊 <b>{p}</b>: ✅ {w} | ❌ {l} | 🎯 {sr}%\n"

    msg += f"\n<i>🤖 Aboud Trading Bot v4.0 PRO</i>\n"
    return msg


def format_recent_trades(trades):
    """Format last N trades."""
    if not trades:
        return "<b>📋 آخر الصفقات</b>\n\nلا توجد صفقات سابقة."

    msg = f"<b>📋 آخر {len(trades)} صفقات</b>\n{'━' * 32}\n\n"
    for t in trades:
        re = "✅" if t.get("result") == "WIN" else "❌"
        pair = t.get("pair", "?")
        dire = t.get("direction", "?")
        arrow = "⬆️" if dire == "CALL" else "⬇️"
        ep = t.get("entry_price")
        xp = t.get("exit_price")
        sc = t.get("signal_score")
        ep_str = f"{ep:.5f}" if ep else "N/A"
        xp_str = f"{xp:.5f}" if xp else "N/A"
        sc_str = f" | Score: {sc}" if sc else ""

        msg += (
            f"{re} <b>{pair}</b> {arrow} {dire}{sc_str}\n"
            f"   Entry: {ep_str} → Exit: {xp_str}\n\n"
        )
    return msg


def format_active_trade(trade):
    """Format current active trade info."""
    if not trade:
        return "<b>📊 الصفقة النشطة</b>\n\n⚪ لا توجد صفقة نشطة حالياً."

    pair = trade.get("pair", "?")
    dire = trade.get("direction", "?")
    arrow = "⬆️" if dire == "CALL" else "⬇️"
    ep = trade.get("entry_price")
    ep_str = f"{ep:.5f}" if ep else "قيد الانتظار"

    return (
        f"<b>📊 الصفقة النشطة</b>\n"
        f"{'━' * 32}\n\n"
        f"📊 <b>{pair}</b> {arrow} {dire}\n"
        f"💰 سعر الدخول: {ep_str}\n"
        f"⏳ المدة: 15 دقيقة\n"
        f"🔄 الحالة: <b>جارية...</b>\n\n"
        f"💡 استخدم /close لإغلاق يدوي"
    )


def format_signal_cancelled_message(pair, direction, reason="Signal reversed"):
    return (
        f"<b>Aboud Trading 15M</b>\n"
        f"⚠️ Signal Cancelled\n\n"
        f"📊 {pair} | {direction}\n"
        f"📝 Reason: {reason}\n"
    )


def format_admin_help():
    return (
        f"<b>🛠 Aboud Trading v4.0 PRO - لوحة التحكم</b>\n"
        f"{'━' * 32}\n\n"
        f"/start - تشغيل البوت\n"
        f"/stats - إحصائيات اليوم\n"
        f"/overall - الإحصائيات التراكمية\n"
        f"/recent - آخر 10 صفقات\n"
        f"/active - الصفقة النشطة\n"
        f"/close - إغلاق الصفقة يدوياً\n"
        f"/news - الأخبار القادمة\n"
        f"/enable - تشغيل الإشارات\n"
        f"/disable - إيقاف الإشارات\n"
        f"/reset - تصفير النتائج\n"
        f"/status - حالة البوت\n\n"
        f"<b>الأزواج:</b> EURUSD, GBPUSD\n"
        f"<b>الحد الأدنى للإشارة:</b> 7/10\n\n"
        f"<i>🔒 أوامر الأدمن فقط</i>\n"
    )


def format_status_message(signals_enabled, pending_count, today_count):
    se = "🟢" if signals_enabled else "🔴"
    st = "نشط" if signals_enabled else "متوقف"
    now = _now()
    return (
        f"<b>🤖 حالة البوت</b>\n"
        f"{'━' * 32}\n\n"
        f"الإشارات: {se} <b>{st}</b>\n"
        f"إشارات معلقة: <b>{pending_count}</b>\n"
        f"صفقات اليوم: <b>{today_count}</b>\n"
        f"الأزواج: EURUSD, GBPUSD\n"
        f"الفريم: 15 دقيقة\n"
        f"ساعات التداول: 10:00 - 23:00 (UTC+3)\n"
        f"التوقيت: UTC+{BOT_UTC_OFFSET}\n"
        f"الوقت: {now.strftime('%H:%M:%S')}\n\n"
        f"<i>🤖 Aboud Trading Bot v4.0 PRO</i>\n"
    )
