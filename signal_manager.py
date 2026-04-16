"""
Aboud Trading Bot - Signal Manager v5.3
======================================
Fixes:
- Auto-correction of entry time when old PineScript sends +15 min offset
- Wider acceptance window for entry timing (up to 35 min) with snap-down logic
- Better error logging for DB schema issues
- Restored compatibility with main.py / admin_bot.py
- Accepts both pair/ticker and entry_time/target_entry_time payload formats
- Uses current telegram_sender signatures correctly
- Uses price_service API correctly for candle open/result
- Supports signals_enabled setting and active trade state
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from config import (
    TRADING_PAIRS,
    TRADE_DURATION_MINUTES,
    SIGNAL_CONFIRM_MIN_SECONDS,
    SIGNAL_CONFIRM_MAX_SECONDS,
    MIN_SIGNAL_SCORE,
    TRADING_START_HOUR_UTC,
    TRADING_END_HOUR_UTC,
    SIGNAL_COOLDOWN_MINUTES,
    WEBHOOK_SECRET,
)
from database import (
    create_pending_signal,
    update_pending_signal,
    delete_pending_signal,
    create_trade,
    update_trade,
    update_statistics,
    get_statistics,
    is_signals_enabled,
)
from price_service import price_service as default_price_service

logger = logging.getLogger(__name__)


class SignalManager:
    """Receives, validates, sends, and tracks trading signals."""

    def __init__(self, telegram_sender, price_service=None):
        self.telegram_sender = telegram_sender
        self.price_service = price_service or default_price_service
        self.active_signals = {}           # pair -> last signal UTC datetime
        self.active_trade = None           # used by admin_bot manual close helper
        self.active_trade_lock = asyncio.Lock()
        self._processing_lock = asyncio.Lock()

    # Compatibility alias expected by main.py
    async def process_webhook_signal(self, data: dict) -> dict:
        return await self.handle_webhook(data)

    async def handle_webhook(self, data: dict) -> dict:
        secret = data.get("secret", "")
        if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
            logger.warning("🚫 Invalid webhook secret")
            return {"status": "error", "message": "Invalid secret"}

        action = str(data.get("action", "SIGNAL")).upper()
        if action == "CANCEL":
            pair = data.get("ticker") or data.get("pair") or ""
            logger.info("🚫 Cancel signal ignored in immediate mode for %s", pair)
            return {"status": "ignored", "message": "Cancel ignored in immediate mode"}

        return await self.process_signal(data)

    async def process_signal(self, signal_data: dict) -> dict:
        async with self._processing_lock:
            pair = (signal_data.get("ticker") or signal_data.get("pair") or "").upper().replace("/", "")
            direction = str(signal_data.get("direction", "")).upper()
            signal_time = signal_data.get("signal_time") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            entry_time = signal_data.get("target_entry_time") or signal_data.get("entry_time")

            try:
                signal_score = int(float(signal_data.get("signal_score", 0) or 0))
            except (ValueError, TypeError):
                signal_score = 0

            logger.info(
                "📨 Signal received: pair=%s direction=%s score=%s entry=%s",
                pair, direction, signal_score, entry_time,
            )

            if not is_signals_enabled():
                logger.info("⛔ Signals are disabled from admin setting")
                return {"status": "rejected", "message": "Signals disabled"}

            if pair not in TRADING_PAIRS:
                return {"status": "rejected", "message": f"Pair {pair} not allowed"}

            if direction not in ("CALL", "PUT"):
                return {"status": "rejected", "message": f"Invalid direction {direction}"}

            if signal_score < MIN_SIGNAL_SCORE:
                return {
                    "status": "rejected",
                    "message": f"Score {signal_score} below minimum {MIN_SIGNAL_SCORE}",
                }

            if not self._is_trading_hours():
                return {"status": "rejected", "message": "Outside trading hours"}

            now_utc = datetime.now(timezone.utc)
            if now_utc.weekday() >= 5:
                return {"status": "rejected", "message": "Weekend"}

            if not self._check_cooldown(pair):
                return {"status": "rejected", "message": f"Cooldown active for {pair}"}

            timing_ok, minutes_until, normalized_entry_time = self._validate_entry_timing(entry_time)
            if not timing_ok:
                return {
                    "status": "rejected",
                    "message": f"Invalid entry timing ({minutes_until:.1f} min)",
                }

            try:
                pending_id = create_pending_signal(
                    pair=pair,
                    direction=direction,
                    signal_time=signal_time,
                    entry_time=normalized_entry_time,
                    status="ACCEPTED",
                    signal_score=signal_score,
                )
            except Exception as e:
                logger.exception("❌ Failed to save pending signal: %s", e)
                return {"status": "error", "message": f"Database error: {e}"}

            self.active_signals[pair] = datetime.now(timezone.utc)

            # Build stats in the structure expected by messages.py/telegram_sender.py
            pair_stats = get_statistics(pair) or {}
            send_stats = {
                "total_wins": int(pair_stats.get("total_wins", 0)),
                "total_losses": int(pair_stats.get("total_losses", 0)),
            }

            try:
                await self.telegram_sender.send_signal(
                    pair,
                    direction,
                    normalized_entry_time,
                    send_stats,
                    score=signal_score,
                )
                logger.info("📤 Telegram signal sent: %s %s", pair, direction)
            except Exception as e:
                logger.exception("❌ Telegram send_signal failed: %s", e)

            asyncio.create_task(
                self._monitor_trade(
                    pending_id=pending_id,
                    pair=pair,
                    direction=direction,
                    entry_time=normalized_entry_time,
                    signal_score=signal_score,
                )
            )

            return {
                "status": "accepted",
                "message": f"Signal accepted: {pair} {direction} ({signal_score}/10)",
                "pending_id": pending_id,
            }

    async def _monitor_trade(self, pending_id, pair, direction, entry_time, signal_score=0):
        try:
            entry_dt = self._parse_entry_time(entry_time)
            if not entry_dt:
                logger.error("❌ Cannot parse entry time: %s", entry_time)
                delete_pending_signal(pending_id)
                return

            wait_seconds = (entry_dt - datetime.now(timezone.utc)).total_seconds()
            if wait_seconds > 0:
                logger.info("⏳ Waiting %.1f seconds for entry %s %s", wait_seconds, pair, direction)
                await asyncio.sleep(wait_seconds)

            # let the new candle form
            await asyncio.sleep(2)

            candle = await self.price_service.get_trade_candle(pair, entry_dt)
            if candle:
                entry_price = candle.get("entry_price")
            else:
                entry_price = await self.price_service.get_price(pair)

            expiry_dt = entry_dt + timedelta(minutes=TRADE_DURATION_MINUTES)
            expiry_time = expiry_dt.strftime("%Y-%m-%d %H:%M:%S")

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
                logger.exception("❌ Failed to create trade: %s", e)
                delete_pending_signal(pending_id)
                return

            if entry_price is not None:
                update_trade(trade_id, entry_price=entry_price)

            update_pending_signal(pending_id, "ACTIVE")

            async with self.active_trade_lock:
                self.active_trade = {
                    "id": trade_id,
                    "pair": pair,
                    "direction": direction,
                    "entry_time": entry_time,
                    "expiry_time": expiry_time,
                    "entry_price": entry_price,
                    "signal_score": signal_score,
                }

            remaining = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                logger.info("⏳ Trade active for %.1f seconds: #%s", remaining, trade_id)
                await asyncio.sleep(remaining)

            # wait a few seconds for candle source to finalize close price
            await asyncio.sleep(6)

            result_candle = await self.price_service.get_trade_candle(pair, entry_dt)
            exit_price = result_candle.get("exit_price") if result_candle else None
            if exit_price is None:
                exit_price = await self.price_service.get_price(pair)

            result = self._determine_result(direction, entry_price, exit_price)
            logger.info(
                "📊 Trade completed: %s %s result=%s entry=%s exit=%s",
                pair, direction, result, entry_price, exit_price,
            )

            update_trade(
                trade_id,
                exit_price=exit_price,
                status="COMPLETED",
                result=result,
            )
            update_statistics(pair, result)
            update_pending_signal(pending_id, "COMPLETED")

            try:
                await self.telegram_sender.send_result(pair, direction, entry_time, result)
            except Exception as e:
                logger.exception("❌ Telegram send_result failed: %s", e)

            async with self.active_trade_lock:
                self.active_trade = None

        except asyncio.CancelledError:
            logger.info("Trade monitor cancelled for %s", pair)
        except Exception as e:
            logger.exception("❌ Trade monitor error for %s: %s", pair, e)
            async with self.active_trade_lock:
                self.active_trade = None

    def _determine_result(self, direction, entry_price, exit_price):
        if entry_price is None or exit_price is None:
            return "DRAW"
        if direction == "CALL":
            if exit_price > entry_price:
                return "WIN"
            if exit_price < entry_price:
                return "LOSS"
            return "DRAW"
        if exit_price < entry_price:
            return "WIN"
        if exit_price > entry_price:
            return "LOSS"
        return "DRAW"

    def _is_trading_hours(self) -> bool:
        hour = datetime.now(timezone.utc).hour
        if TRADING_START_HOUR_UTC <= TRADING_END_HOUR_UTC:
            return TRADING_START_HOUR_UTC <= hour < TRADING_END_HOUR_UTC
        return hour >= TRADING_START_HOUR_UTC or hour < TRADING_END_HOUR_UTC

    def _check_cooldown(self, pair: str) -> bool:
        last_time = self.active_signals.get(pair)
        if not last_time:
            return True
        elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
        return elapsed >= (SIGNAL_COOLDOWN_MINUTES * 60)

    def _validate_entry_timing(self, entry_time_str: str):
        """Return (valid, minutes_until, normalized_entry_time_str).

        Auto-correction logic:
        1. If entry is within [-2 min, +16 min] -> accept as-is (new PineScript).
        2. If entry is between +16 and +40 min  -> subtract 15 min (old PineScript
           that still adds an extra 15-minute offset).
        3. Otherwise -> snap to the next 15-minute candle boundary if close,
           else reject.
        """
        entry_dt = self._parse_entry_time(entry_time_str)
        if not entry_dt:
            return False, -1, entry_time_str

        now = datetime.now(timezone.utc)
        diff = (entry_dt - now).total_seconds()
        minutes_until = diff / 60.0

        # In immediate mode config is 0/0, so accept from ~now up to 16 minutes.
        min_seconds = SIGNAL_CONFIRM_MIN_SECONDS if SIGNAL_CONFIRM_MIN_SECONDS > 0 else -120
        max_seconds = SIGNAL_CONFIRM_MAX_SECONDS if SIGNAL_CONFIRM_MAX_SECONDS > 0 else 960

        # Tier 1: in range
        if min_seconds <= diff <= max_seconds:
            normalized = entry_dt.strftime("%Y-%m-%d %H:%M:%S")
            return True, minutes_until, normalized

        # Tier 2: old PineScript adds +15 min -> correct it
        if 16 * 60 < diff <= 40 * 60:
            corrected = entry_dt - timedelta(minutes=15)
            corrected_diff = (corrected - now).total_seconds()
            if min_seconds <= corrected_diff <= max_seconds:
                logger.warning(
                    "⚠️ Entry time auto-corrected -15min (old PineScript): %s -> %s",
                    entry_dt.strftime("%H:%M:%S"),
                    corrected.strftime("%H:%M:%S"),
                )
                return True, corrected_diff / 60.0, corrected.strftime("%Y-%m-%d %H:%M:%S")

        # Tier 3: snap to the next 15-min boundary if within reasonable range
        if -2 * 60 <= diff <= 40 * 60:
            minute = (now.minute // 15 + 1) * 15
            if minute >= 60:
                snapped = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            else:
                snapped = now.replace(minute=minute, second=0, microsecond=0)
            snapped_diff = (snapped - now).total_seconds()
            if 0 < snapped_diff <= max_seconds:
                logger.warning(
                    "⚠️ Entry time snapped to next 15-min candle: %s -> %s",
                    entry_dt.strftime("%H:%M:%S"),
                    snapped.strftime("%H:%M:%S"),
                )
                return True, snapped_diff / 60.0, snapped.strftime("%Y-%m-%d %H:%M:%S")

        normalized = entry_dt.strftime("%Y-%m-%d %H:%M:%S")
        return False, minutes_until, normalized

    def _parse_entry_time(self, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)

        try:
            ts = int(str(value))
            if ts > 1_000_000_000_000:
                ts = ts / 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass

        text = str(value).strip()
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        logger.warning("⚠️ Could not parse entry time: %s", value)
        return None
