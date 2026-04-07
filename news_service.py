"""
Aboud Trading Bot - News Service v3.1
========================================
- Arabic translations for common forex events
- Today's news only
"""
import aiohttp
import logging
from datetime import datetime
from config import BOT_TIMEZONE

logger = logging.getLogger(__name__)

FOREXFACTORY_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Arabic translations for common forex news events
TRANSLATIONS = {
    # Interest Rates & Central Banks
    "Official Cash Rate": "سعر الفائدة الرسمي",
    "Federal Funds Rate": "سعر الفائدة الفيدرالي",
    "Interest Rate Decision": "قرار سعر الفائدة",
    "Monetary Policy Statement": "بيان السياسة النقدية",
    "FOMC Meeting Minutes": "محضر اجتماع الفيدرالي",
    "FOMC Statement": "بيان الفيدرالي",
    "FOMC Press Conference": "مؤتمر الفيدرالي الصحفي",
    "RBNZ Rate Statement": "بيان بنك نيوزلندا",
    "RBNZ Press Conference": "مؤتمر بنك نيوزلندا",
    "BOE Rate Statement": "بيان بنك إنجلترا",
    "BOJ Rate Statement": "بيان بنك اليابان",
    "ECB Rate Statement": "بيان البنك المركزي الأوروبي",
    "ECB Press Conference": "مؤتمر المركزي الأوروبي",
    "BOC Rate Statement": "بيان بنك كندا",
    "RBA Rate Statement": "بيان بنك أستراليا",
    "SNB Rate Statement": "بيان بنك سويسرا",

    # GDP
    "Final GDP q/q": "الناتج المحلي الإجمالي النهائي",
    "Prelim GDP q/q": "الناتج المحلي الأولي",
    "GDP q/q": "الناتج المحلي الإجمالي",
    "Final GDP Price Index q/q": "مؤشر أسعار الناتج المحلي",

    # Employment
    "Non-Farm Employment Change": "الوظائف غير الزراعية",
    "Employment Change": "تغير التوظيف",
    "Unemployment Rate": "معدل البطالة",
    "Unemployment Claims": "طلبات إعانة البطالة",
    "Average Hourly Earnings m/m": "متوسط الأجور بالساعة",
    "ADP Non-Farm Employment Change": "وظائف ADP غير الزراعية",
    "Job Openings": "فرص العمل المتاحة",
    "Claimant Count Change": "تغير طلبات البطالة",

    # Inflation / CPI / PPI
    "CPI m/m": "مؤشر أسعار المستهلك الشهري",
    "CPI y/y": "مؤشر أسعار المستهلك السنوي",
    "Core CPI m/m": "مؤشر أسعار المستهلك الأساسي",
    "Core CPI y/y": "مؤشر أسعار المستهلك الأساسي السنوي",
    "PPI m/m": "مؤشر أسعار المنتجين الشهري",
    "PPI y/y": "مؤشر أسعار المنتجين السنوي",
    "Core PPI m/m": "مؤشر أسعار المنتجين الأساسي",
    "Core PCE Price Index m/m": "مؤشر نفقات الاستهلاك الأساسي",
    "PCE Price Index m/m": "مؤشر نفقات الاستهلاك",

    # PMI
    "Manufacturing PMI": "مؤشر مديري المشتريات الصناعي",
    "Services PMI": "مؤشر مديري المشتريات الخدمي",
    "Flash Manufacturing PMI": "مؤشر PMI الصناعي الأولي",
    "Flash Services PMI": "مؤشر PMI الخدمي الأولي",
    "ISM Manufacturing PMI": "مؤشر ISM الصناعي",
    "ISM Services PMI": "مؤشر ISM الخدمي",
    "Ivey PMI": "مؤشر آيفي لمديري المشتريات",

    # Retail & Consumer
    "Retail Sales m/m": "مبيعات التجزئة الشهرية",
    "Core Retail Sales m/m": "مبيعات التجزئة الأساسية",
    "Consumer Confidence": "ثقة المستهلك",
    "CB Consumer Confidence": "ثقة المستهلك CB",
    "Prelim UoM Consumer Sentiment": "ثقة المستهلك (ميشيغان) أولي",
    "Revised UoM Consumer Sentiment": "ثقة المستهلك (ميشيغان) معدل",

    # Trade & Orders
    "Trade Balance": "الميزان التجاري",
    "Current Account": "الحساب الجاري",
    "Durable Goods Orders m/m": "طلبيات السلع المعمرة",
    "Core Durable Goods Orders m/m": "طلبيات السلع المعمرة الأساسية",
    "Factory Orders m/m": "طلبيات المصانع",

    # Housing
    "Building Permits": "تصاريح البناء",
    "Existing Home Sales": "مبيعات المنازل القائمة",
    "New Home Sales": "مبيعات المنازل الجديدة",
    "Housing Starts": "بدايات الإسكان",
    "Pending Home Sales m/m": "مبيعات المنازل المعلقة",

    # Other
    "Crude Oil Inventories": "مخزونات النفط الخام",
    "Natural Gas Storage": "مخزونات الغاز الطبيعي",
    "Industrial Production m/m": "الإنتاج الصناعي",
    "Empire State Manufacturing Index": "مؤشر إمباير ستيت الصناعي",
    "Philly Fed Manufacturing Index": "مؤشر فيلادلفيا الصناعي",
    "BOE Gov Bailey Speaks": "خطاب محافظ بنك إنجلترا",
    "Fed Chair Powell Speaks": "خطاب رئيس الفيدرالي باول",
    "ECB President Lagarde Speaks": "خطاب رئيسة المركزي الأوروبي",
    "OPEC Meetings": "اجتماعات أوبك",
    "G7 Meetings": "اجتماعات مجموعة السبع",
    "G20 Meetings": "اجتماعات مجموعة العشرين",
    "Bank Holiday": "عطلة رسمية",
}


def _translate(title):
    """Get Arabic translation. Try exact match first, then partial."""
    # Exact match
    if title in TRANSLATIONS:
        return TRANSLATIONS[title]

    # Partial match
    for en, ar in TRANSLATIONS.items():
        if en.lower() in title.lower():
            return ar

    return ""


async def fetch_upcoming_news(limit=20):
    """Fetch TODAY's high/medium impact news from ForexFactory."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(FOREXFACTORY_CALENDAR_URL) as resp:
                if resp.status != 200:
                    logger.error(f"ForexFactory API returned {resp.status}")
                    return []
                data = await resp.json()

        now = datetime.now(BOT_TIMEZONE)
        today_str = now.strftime("%Y-%m-%d")
        upcoming = []

        for event in data:
            title = event.get("title", "")
            country = event.get("country", "")
            date_str = event.get("date", "")
            impact = event.get("impact", "").lower()
            forecast = event.get("forecast", "")
            previous = event.get("previous", "")

            if impact not in ["high", "medium"]:
                continue

            try:
                event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                event_local = event_dt.astimezone(BOT_TIMEZONE)

                # TODAY ONLY
                if event_local.strftime("%Y-%m-%d") != today_str:
                    continue

            except Exception:
                continue

            impact_emoji = "🔴" if impact == "high" else "🟡"
            time_str = event_local.strftime("%H:%M")
            arabic = _translate(title)

            upcoming.append({
                "title": title,
                "arabic": arabic,
                "country": country,
                "time": time_str,
                "impact": impact,
                "impact_emoji": impact_emoji,
                "forecast": forecast,
                "previous": previous,
            })

            if len(upcoming) >= limit:
                break

        return upcoming

    except Exception as e:
        logger.error(f"Failed to fetch news: {e}", exc_info=True)
        return []


def format_news_message(news_list):
    """Format news list into Telegram message with Arabic translations."""
    now = datetime.now(BOT_TIMEZONE)
    date_str = now.strftime("%Y-%m-%d")

    if not news_list:
        return (
            f"<b>📰 أخبار اليوم</b>\n"
            f"<b>📅 {date_str}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"لا توجد أخبار مهمة اليوم ✅\n"
        )

    msg = (
        f"<b>📰 أخبار اليوم</b>\n"
        f"<b>📅 {date_str}</b>\n"
        f"<i>المصدر: ForexFactory</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for n in news_list:
        title_line = f"<b>{n['country']}</b> | {n['title']}"
        if n['arabic']:
            title_line += f"\n   📝 {n['arabic']}"

        msg += (
            f"{n['impact_emoji']} {title_line}\n"
            f"   🕐 {n['time']}\n"
        )
        if n['forecast']:
            msg += f"   📊 Forecast: {n['forecast']}"
            if n['previous']:
                msg += f" | Previous: {n['previous']}"
            msg += "\n"
        msg += "\n"

    msg += "<i>🔴 تأثير عالي | 🟡 تأثير متوسط</i>\n"
    return msg
