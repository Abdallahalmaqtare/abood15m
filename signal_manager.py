"""
Aboud Trading Bot - Signal Manager v4.2 (FINAL FIX)
=====================================================
CRITICAL FIX: Removed confirmation delay entirely.
Signal → Immediate send to Telegram. No waiting.
The 10-layer scoring system is the filter, not delay.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from config import (
    TRADE_DURATION_MINUTES,
    TRADING_PAIRS,
    TRADING_START_HOUR_UTC,
    TRADING_END_HOUR_UTC,
    BOT_TIMEZONE,
    RESULT_CANDLE_BUFFER_SECONDS,
    RESULT_FETCH_RETRY_SECONDS,
    RESULT_MAX_WAIT_AFTER_EXPIRY_SECONDS,
    MIN_SIGNAL_SCORE,
    SIGNAL_COOLDOWN_MINUTES,
)
from database import (
    create_pending_signal,
    confirm_pending_signal,
    cancel_pending_signal,
    create_trade,
    update_trade_entry_price,
    update_trade_result,
    update_statistics,
    is_signals_enabled,
    get_pair_statistics,
)
from price_service import price_service

logger = logging.getLogger(__name__)


class SignalManager:
    def __init__(self, telegram_sender):
        self.telegram = telegram_sender
        self.pending_results = {}
        self.active_trade = None
        self.active_trade_lock = asyncio.Lock()
        self._last_signal_time = {}

    def is_trading_hours(self):
        if TRADING_START_HOUR_UTC == 0 and TRADING_END_HOUR_UTC == 24:
            return True
        now = datetime.now(timezone.utc)
        return TRADING_START_HOUR_UTC <= now.hour < TRADING_END_HOUR_UTC

    def is_valid_pair(self, pair):
        return pair.upper().replace("/", "") in TRADING_PAIRS

    def is_in_cooldown(self, pair):
        last_time = self._last_signal_time.get(pair)
        if last_time is None:
            return False
        elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
        cooldown_seconds = SIGNAL_COOLDOWN_MINUTES * 60
        if elapsed < cooldown_seconds:
            logger.info(f"{pair} in cooldown, {cooldown_seconds - elapsed:.0f}s remaining")
            return True
        return False

    def get_next_candle_time(self, now=None):
        now = now or datetime.now(timezone.utc)
        minute = now.minute
        next_slot = ((minute // 15) + 1) * 15
        if next_slot >= 60:
            return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return now.replace(minute=next_slot, second=0, microsecond=0)

    def get_target_entry_time_from_payload(self, data):
        raw = data.get("target_entry_time") or data.get("entry_time") or data.get("entry_timestamp")
        if raw in (None, "", 0):
            return self.get_next_candle_time()
        try:
            if isinstance(raw, (int, float)):
                timestamp = float(raw)
                if timestamp > 10_000_000_000:
                    timestamp /= 1000.0
                dt = datetime.fromtimestamp(timestamp, timezone.utc)
                return dt.replace(second=0, microsecond=0)
            if isinstance(raw, str):
                raw = raw.strip()
                if raw.replace(".", "").isdigit():
                    timestamp = float(raw)
                    if timestamp > 10_000_000_000:
                        timestamp /= 1000.0
                    dt = datetime.fromtimestamp(timestamp, timezone.utc)
                    return dt.replace(second=0, microsecond=0)
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
        except Exception as exc:
            logger.warning("Failed to parse entry time: %s (raw=%s)", exc, raw)
        return self.get_next_candle_time()

    def _validate_entry_timing(self, target_entry):
        now = datetime.now(timezone.utc)
        seconds_until = (target_entry - now).total_seconds()
        if seconds_until < -60:
            return self.get_next_candle_time(now)
        if seconds_until > 20 * 60:
            return self.get_next_candle_time(now)
        return target_entry

    def utc_to_local(self, dt):
        return dt.astimezone(BOT_TIMEZONE)

    def has_active_trade(self):
        return self.active_trade is not None

    async def process_webhook_signal(self, data):
        """
        IMMEDIATE PROCESSING - No confirmation delay.
        Signal arrives → validate → send to Telegram instantly.
        """
        try:
            # Clean pair name (handle FX:GBPUSD, OANDA:GBPUSD etc)
            raw_pair = data.get("pair", "")
            pair = raw_pair.upper().replace("/", "")
            # Remove broker prefixes
            for prefix in ["FX:", "FXCM:", "OANDA:", "FOREXCOM:", "SAXO:", "PEPPERSTONE:"]:
                pair = pair.replace(prefix, "")
            pair = pair.strip()

            direction = data.get("direction", "").upper()
            action = data.get("action", "SIGNAL").upper()
            signal_score = data.get("signal_score", 0)

            logger.info(">>> Webhook: pair=%s dir=%s action=%s score=%s (raw_pair=%s)",
                        pair, direction, action, signal_score, raw_pair)

            # Ignore CANCEL actions entirely - we send immediately, no pending to cancel
            if action == "CANCEL":
                logger.info("CANCEL received - ignored (immediate mode)")
                return {"status": "ignored", "message": "No pending signals in immediate mode"}

            if not is_signals_enabled():
                logger.info("REJECTED: signals disabled")
                return {"status": "disabled"}

            if not self.is_valid_pair(pair):
                logger.info("REJECTED: invalid pair '%s' (valid: %s)", pair, TRADING_PAIRS)
                return {"status": "error", "message": f"Invalid pair: {pair}"}

            if direction not in ["CALL", "PUT"]:
                logger.info("REJECTED: invalid direction '%s'", direction)
                return {"status": "error", "message": f"Invalid direction: {direction}"}

            if not self.is_trading_hours():
                logger.info("REJECTED: outside trading hours")
                return {"status": "skipped", "message": "Outside trading hours"}

            try:
                score = float(signal_score)
            except (TypeError, ValueError):
                score = 0

            if score < MIN_SIGNAL_SCORE:
                logger.info("REJECTED: score %.1f < min %.1f", score, MIN_SIGNAL_SCORE)
                return {"status": "rejected", "message": f"Score {score} < {MIN_SIGNAL_SCORE}"}

            if self.has_active_trade():
                logger.info("REJECTED: active trade exists")
                return {"status": "blocked", "message": "Active trade in progress"}

            if self.is_in_cooldown(pair):
                return {"status": "cooldown", "message": f"{pair} in cooldown"}

            # ====== IMMEDIATE SEND - NO DELAY ======
            logger.info("✅ ACCEPTED: %s %s score=%.1f → sending NOW", pair, direction, score)
            return await self._send_signal_immediately(pair, direction, data, score)

        except Exception as exc:
            logger.error("CRASH in process_webhook_signal: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    async def _send_signal_immediately(self, pair, direction, payload, score):
        """Send signal to Telegram immediately without any confirmation delay."""
        try:
            now = datetime.now(timezone.utc)
            target_entry = self.get_target_entry_time_from_payload(payload)
            target_entry = self._validate_entry_timing(target_entry)
            indicators = payload.get("indicators", {})

            # Create DB records
            signal_id = create_pending_signal(
                pair=pair, direction=direction,
                detected_at=now.isoformat(),
                target_entry_time=target_entry.isoformat(),
                indicator_data=indicators, signal_score=score,
            )
            confirm_pending_signal(signal_id)

            # Set cooldown
            self._last_signal_time[pair] = now

            local_entry = self.utc_to_local(target_entry)
            entry_time_str = local_entry.strftime("%H:%M")

            trade_id = create_trade(
                pair=pair, direction=direction,
                entry_time=target_entry.isoformat(),
                entry_price=None, signal_score=score,
            )

            async with self.active_trade_lock:
                self.active_trade = {
                    "trade_id": trade_id, "pair": pair,
                    "direction": direction, "entry_time": entry_time_str,
                    "target_entry_utc": target_entry, "score": score,
                }

            # Send to Telegram
            stats = get_pair_statistics(pair) or {"total_wins": 0, "total_losses": 0}
            await self.telegram.send_signal(
                pair=pair, direction=direction,
                entry_time=entry_time_str, stats=stats, score=score,
            )
            logger.info("🚀 SIGNAL SENT TO TELEGRAM: %s %s at %s (score: %.1f)",
                        pair, direction, entry_time_str, score)

            # Start monitoring trade result in background
            result_task = asyncio.create_task(
                self._monitor_trade(trade_id, pair, direction, entry_time_str, target_entry)
            )
            self.pending_results[trade_id] = result_task

            return {"status": "sent", "signal_id": signal_id, "trade_id": trade_id, "score": score}

        except Exception as exc:
            logger.error("Error sending signal: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    def _determine_result(self, direction, entry_price, exit_price):
        if direction == "CALL":
            return "WIN" if exit_price > entry_price else "LOSS"
        return "WIN" if exit_price < entry_price else "LOSS"

    async def _wait_for_trade_candle(self, pair, target_entry, expiry):
        deadline = expiry + timedelta(seconds=RESULT_MAX_WAIT_AFTER_EXPIRY_SECONDS)
        while datetime.now(timezone.utc) <= deadline:
            candle = await price_service.get_trade_candle(pair, target_entry)
            if candle and candle.get("entry_price") is not None and candle.get("exit_price") is not None:
                return candle
            await asyncio.sleep(RESULT_FETCH_RETRY_SECONDS)
        return None

    async def _monitor_trade(self, trade_id, pair, direction, entry_time_str, target_entry):
        try:
            now = datetime.now(timezone.utc)
            wait_until_entry = (target_entry - now).total_seconds()
            if wait_until_entry > 0:
                logger.info("Trade #%s: waiting %.0fs until entry", trade_id, wait_until_entry)
                await asyncio.sleep(wait_until_entry)

            await asyncio.sleep(RESULT_CANDLE_BUFFER_SECONDS)

            entry_open = await price_service.get_candle_open(pair, target_entry)
            if entry_open is not None:
                update_trade_entry_price(trade_id, entry_open)

            expiry = target_entry + timedelta(minutes=TRADE_DURATION_MINUTES)
            now = datetime.now(timezone.utc)
            wait_until_expiry = (expiry - now).total_seconds()
            if wait_until_expiry > 0:
                logger.info("Trade #%s: waiting %.0fs until expiry", trade_id, wait_until_expiry)
                await asyncio.sleep(wait_until_expiry)

            await asyncio.sleep(RESULT_CANDLE_BUFFER_SECONDS)

            candle = await self._wait_for_trade_candle(pair, target_entry, expiry)

            if candle:
                entry_price = candle["entry_price"]
                exit_price = candle["exit_price"]
                update_trade_entry_price(trade_id, entry_price)
                result = self._determine_result(direction, entry_price, exit_price)
            else:
                entry_price = await price_service.get_candle_open(pair, target_entry)
                exit_price = await price_service.get_price(pair)
                if entry_price is None or exit_price is None:
                    result = "LOSS"
                else:
                    update_trade_entry_price(trade_id, entry_price)
                    result = self._determine_result(direction, entry_price, exit_price)

            update_trade_result(trade_id, exit_price, result)
            update_statistics(pair, result == "WIN")

            await self.telegram.send_result(
                pair=pair, direction=direction,
                entry_time=entry_time_str, result=result,
            )
            logger.info("Trade #%s: %s (entry=%s, exit=%s)", trade_id, result, entry_price, exit_price)

        except Exception as exc:
            logger.error("Error in trade #%s: %s", trade_id, exc, exc_info=True)
        finally:
            async with self.active_trade_lock:
                self.active_trade = None
            self.pending_results.pop(trade_id, None)
            logger.info("Trade #%s done. Ready for next.", trade_id)
