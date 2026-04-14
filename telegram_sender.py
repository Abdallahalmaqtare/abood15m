"""
Aboud Trading Bot - Telegram Sender v4.0
==========================================
Updated to pass signal score.
"""

import logging
import aiohttp
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from messages import (
    format_signal_message,
    format_result_message,
    format_stats_message,
    format_daily_report,
    format_signal_cancelled_message,
)

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


class TelegramSender:
    """Sends formatted messages to Telegram channel."""

    def __init__(self):
        self.session = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self.session

    async def _send_message(self, text, chat_id=None, parse_mode="HTML"):
        """Send a message to Telegram."""
        target = chat_id or TELEGRAM_CHAT_ID
        session = await self._get_session()

        payload = {
            "chat_id": target,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            async with session.post(f"{TELEGRAM_API}/sendMessage", json=payload) as resp:
                result = await resp.json()
                if result.get("ok"):
                    logger.info(f"Message sent to {target}")
                    return result
                else:
                    logger.error(f"Telegram API error: {result}")
                    return None
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return None

    async def send_signal(self, pair, direction, entry_time, stats, score=None):
        """Send a trading signal to the channel."""
        text = format_signal_message(pair, direction, entry_time, stats, score=score)
        return await self._send_message(text)

    async def send_result(self, pair, direction, entry_time, result):
        """Send a trade result to the channel."""
        text = format_result_message(pair, direction, entry_time, result)
        return await self._send_message(text)

    async def send_stats(self, stats_list, chat_id=None):
        """Send statistics."""
        text = format_stats_message(stats_list)
        return await self._send_message(text, chat_id=chat_id)

    async def send_daily_report(self, daily_stats, today_trades=None):
        """Send daily report to the channel."""
        text = format_daily_report(daily_stats, today_trades)
        return await self._send_message(text)

    async def send_cancelled(self, pair, direction, reason="Signal reversed"):
        """Send signal cancelled notification."""
        text = format_signal_cancelled_message(pair, direction, reason)
        return await self._send_message(text)

    async def send_text(self, text, chat_id=None):
        """Send raw text message."""
        return await self._send_message(text, chat_id=chat_id)

    async def close(self):
        """Close the HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()
