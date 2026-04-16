"""
Signal Manager - Aboud Trading Bot v5.0 PRO
Handles signal reception, validation, confirmation, and trade monitoring.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from config import (
    TRADING_PAIRS,
    TRADE_DURATION_MINUTES,
    SIGNAL_CONFIRM_MIN_SECONDS,
    SIGNAL_CONFIRM_MAX_SECONDS,
    WEBHOOK_SECRET,
    BOT_UTC_OFFSET,
    MIN_SIGNAL_SCORE,
    TRADING_HOUR_START,
    TRADING_HOUR_END,
    COOLDOWN_MINUTES,
)
from database import (
    create_pending_signal,
    update_pending_signal,
    delete_pending_signal,
    create_trade,
    update_trade,
    update_statistics,
)
from price_service import PriceService
from telegram_sender import TelegramSender

logger = logging.getLogger(__name__)


class SignalManager:
    """Manages the lifecycle of trading signals from reception to result."""

    def __init__(self, telegram_sender: TelegramSender, price_service: PriceService):
        self.telegram_sender = telegram_sender
        self.price_service = price_service
        self.active_signals = {}  # pair -> last_signal_time (for cooldown)
        self._processing_lock = asyncio.Lock()

    # ─────────────────────────────────────────────
    #  WEBHOOK ENTRY POINT
    # ─────────────────────────────────────────────

    async def handle_webhook(self, data: dict) -> dict:
        """
        Handle incoming webhook from TradingView.
        Returns a status dict for the HTTP response.
        """
        # ── Validate secret ──
        secret = data.get("secret", "")
        if secret != WEBHOOK_SECRET:
            logger.warning("🚫 Invalid webhook secret received")
            return {"status": "error", "message": "Invalid secret"}

        action = data.get("action", "").upper()

        # ── Handle CANCEL signals ──
        if action == "CANCEL":
            pair = data.get("ticker", "")
            logger.info("🚫 CANCEL signal received for %s — ignored (immediate mode)", pair)
            return {"status": "ignored", "message": "Cancel signals ignored in immediate mode"}

        # ── Process trading signal ──
        return await self.process_signal(data)

    # ─────────────────────────────────────────────
    #  SIGNAL PROCESSING
    # ─────────────────────────────────────────────

    async def process_signal(self, signal_data: dict) -> dict:
        """Validate, persist and dispatch a new trading signal."""
        pair = signal_data.get("ticker", "").upper().replace("/", "")
        direction = signal_data.get("direction", "").upper()
        signal_time = signal_data.get("signal_time", "")
        entry_time = signal_data.get("target_entry_time", "")
        signal_score = 0

        # Safely parse signal_score from webhook payload
        try:
            signal_score = int(signal_data.get("signal_score", 0) or 0)
        except (ValueError, TypeError):
            signal_score = 0

        logger.info(
            "📨 Signal received: %s %s | score=%s/10 | signal_time=%s | entry_time=%s",
            pair, direction, signal_score, signal_time, entry_time,
        )

        # ── Validate pair ──
        if pair not in TRADING_PAIRS:
            logger.warning("⛔ Pair %s not in allowed list %s", pair, TRADING_PAIRS)
            return {"status": "rejected", "message": f"Pair {pair} not allowed"}

        # ── Validate direction ──
        if direction not in ("CALL", "PUT"):
            logger.warning("⛔ Invalid direction: %s", direction)
            return {"status": "rejected", "message": f"Invalid direction: {direction}"}

        # ── Validate minimum score ──
        if signal_score < MIN_SIGNAL_SCORE:
            logger.info(
                "⛔ Signal score %s < minimum %s — rejected", signal_score, MIN_SIGNAL_SCORE
            )
            return {
                "status": "rejected",
                "message": f"Score {signal_score} below minimum {MIN_SIGNAL_SCORE}",
            }

        # ── Check trading hours ──
        if not self._is_trading_hours():
            logger.info("⛔ Outside trading hours (%02d:00-%02d:00 UTC)", TRADING_HOUR_START, TRADING_HOUR_END)
            return {"status": "rejected", "message": "Outside trading hours"}

        # ── Check weekend ──
        now_utc = datetime.now(timezone.utc)
        if now_utc.weekday() >= 5:  # Saturday=5, Sunday=6
            logger.info("⛔ Weekend — no trading")
            return {"status": "rejected", "message": "Weekend — market closed"}

        # ── Cooldown check ──
        if not self._check_cooldown(pair):
            logger.info("⛔ Cooldown active for %s", pair)
            return {"status": "rejected", "message": f"Cooldown active for {pair}"}

        # ── Validate entry timing ──
        timing_ok, minutes_until = self._validate_entry_timing(entry_time)
        if not timing_ok:
            logger.info("⛔ Bad entry timing: %.1f min until entry", minutes_until)
            return {
                "status": "rejected",
                "message": f"Entry timing invalid ({minutes_until:.1f} min)",
            }

        logger.info("✅ Signal ACCEPTED: %s %s | score=%s | entry in %.1f min",
                     pair, direction, signal_score, minutes_until)

        # ── Persist pending signal ──
        try:
            pending_id = create_pending_signal(
                pair=pair,
                direction=direction,
                signal_time=signal_time,
                entry_time=entry_time,
                status="ACCEPTED",
                signal_score=signal_score,
            )
        except Exception as e:
            logger.exception("❌ DB error saving pending signal: %s", e)
            return {"status": "error", "message": f"Database error: {e}"}

        # ── Update cooldown ──
        self.active_signals[pair] = datetime.now(timezone.utc)

        # ── Send Telegram alert ──
        try:
            await self.telegram_sender.send_signal(
                pair=pair,
                direction=direction,
                entry_time=entry_time,
                signal_score=signal_score,
            )
            logger.info("📤 Telegram signal sent for %s %s", pair, direction)
        except Exception as e:
            logger.exception("❌ Telegram send failed: %s", e)

        # ── Launch trade monitor in background ──
        asyncio.create_task(
            self._monitor_trade(
                pending_id=pending_id,
                pair=pair,
                direction=direction,
                entry_time=entry_time,
                signal_score=signal_score,
            )
        )

        return {
            "status": "accepted",
            "message": f"Signal accepted: {pair} {direction} (score {signal_score}/10)",
            "pending_id": pending_id,
        }

    # ─────────────────────────────────────────────
    #  TRADE MONITORING
    # ─────────────────────────────────────────────

    async def _monitor_trade(self, pending_id, pair, direction, entry_time, signal_score=0):
        """
        Wait until entry candle, record open price, wait for expiry,
        fetch result candle, determine WIN/LOSS, update DB & Telegram.
        """
        try:
            # ── Parse entry time ──
            entry_dt = self._parse_entry_time(entry_time)
            if not entry_dt:
                logger.error("❌ Cannot parse entry_time: %s", entry_time)
                delete_pending_signal(pending_id)
                return

            now = datetime.now(timezone.utc)
            wait_seconds = (entry_dt - now).total_seconds()

            if wait_seconds > 0:
                logger.info("⏳ Waiting %.0f sec until entry for %s %s", wait_seconds, pair, direction)
                await asyncio.sleep(wait_seconds)

            # ── Small buffer to let candle form ──
            await asyncio.sleep(5)

            # ── Get entry (open) price ──
            entry_price = await self.price_service.get_candle_open(pair)
            if entry_price is None:
                logger.warning("⚠️ Could not get entry price for %s, trying spot", pair)
                entry_price = await self.price_service.get_price(pair)

            logger.info("📍 Entry price for %s: %s", pair, entry_price)

            # ── Calculate expiry ──
            expiry_dt = entry_dt + timedelta(minutes=TRADE_DURATION_MINUTES)
            expiry_time = expiry_dt.strftime("%Y-%m-%d %H:%M:%S")

            # ── Create trade record ──
            try:
                trade_id = create_trade(
                    pair=pair,
                    direction=direction,
                    entry_time=entry_time,
                    expiry_time=expiry_time,
                    status="ACTIVE",
                    signal_score=signal_score,
                )
            except Exception as e:
                logger.exception("❌ DB error creating trade: %s", e)
                delete_pending_signal(pending_id)
                return

            # Update with entry price
            if entry_price is not None:
                update_trade(trade_id, entry_price=entry_price)

            # ── Mark pending signal as active ──
            update_pending_signal(pending_id, "ACTIVE")

            # ── Wait for trade to expire ──
            now = datetime.now(timezone.utc)
            remaining = (expiry_dt - now).total_seconds()
            if remaining > 0:
                logger.info("⏳ Trade %s active, waiting %.0f sec for expiry", trade_id, remaining)
                await asyncio.sleep(remaining)

            # ── Small buffer for candle close ──
            await asyncio.sleep(10)

            # ── Get exit price ──
            exit_price = await self.price_service.get_trade_candle(pair, entry_time)
            if exit_price is None:
                exit_price = await self.price_service.get_price(pair)

            logger.info("🏁 Exit price for %s: %s", pair, exit_price)

            # ── Determine result ──
            if entry_price is not None and exit_price is not None:
                if direction == "CALL":
                    result = "WIN" if exit_price > entry_price else ("LOSS" if exit_price < entry_price else "DRAW")
                else:  # PUT
                    result = "WIN" if exit_price < entry_price else ("LOSS" if exit_price > entry_price else "DRAW")
            else:
                result = "DRAW"
                logger.warning("⚠️ Missing prices, marking as DRAW")

            logger.info("📊 Trade result: %s %s → %s (entry=%.5f, exit=%.5f)",
                        pair, direction, result,
                        entry_price or 0, exit_price or 0)

            # ── Update trade record ──
            update_trade(
                trade_id,
                exit_price=exit_price,
                status="COMPLETED",
                result=result,
            )

            # ── Update statistics ──
            update_statistics(pair, result)

            # ── Mark pending signal done ──
            update_pending_signal(pending_id, "COMPLETED")

            # ── Send result to Telegram ──
            try:
                await self.telegram_sender.send_result(
                    pair=pair,
                    direction=direction,
                    result=result,
                    entry_price=entry_price,
                    exit_price=exit_price,
                )
            except Exception as e:
                logger.exception("❌ Telegram result send failed: %s", e)

        except asyncio.CancelledError:
            logger.info("🚫 Trade monitor cancelled for %s", pair)
        except Exception as e:
            logger.exception("❌ Trade monitor error for %s: %s", pair, e)

    # ─────────────────────────────────────────────
    #  VALIDATION HELPERS
    # ─────────────────────────────────────────────

    def _is_trading_hours(self) -> bool:
        """Check if current UTC hour is within allowed trading window."""
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        return TRADING_HOUR_START <= hour < TRADING_HOUR_END

    def _check_cooldown(self, pair: str) -> bool:
        """Check if enough time has passed since last signal for this pair."""
        last_time = self.active_signals.get(pair)
        if last_time is None:
            return True
        elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
        return elapsed >= (COOLDOWN_MINUTES * 60)

    def _validate_entry_timing(self, entry_time_str: str):
        """
        Validate that entry time is between 0.5 and 16 minutes from now.
        Returns (is_valid, minutes_until_entry).
        """
        entry_dt = self._parse_entry_time(entry_time_str)
        if not entry_dt:
            return False, -1

        now = datetime.now(timezone.utc)
        diff = (entry_dt - now).total_seconds()
        minutes_until = diff / 60.0

        # Accept signals 30 sec to 16 min before entry
        is_valid = (SIGNAL_CONFIRM_MIN_SECONDS <= diff <= SIGNAL_CONFIRM_MAX_SECONDS + 360)
        return is_valid, minutes_until

    def _parse_entry_time(self, entry_time_str: str):
        """Parse entry time string into a timezone-aware datetime."""
        if not entry_time_str:
            return None

        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M",
        ]

        # Handle Unix timestamp (milliseconds)
        try:
            ts = int(entry_time_str)
            if ts > 1e12:
                ts = ts / 1000  # Convert ms to seconds
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass

        # Try string formats
        for fmt in formats:
            try:
                dt = datetime.strptime(entry_time_str, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        logger.warning("⚠️ Could not parse entry time: %s", entry_time_str)
        return None
