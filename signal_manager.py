"""
Aboud Trading Bot - Signal Manager v3.2
========================================
Fixes trade-result analysis by using the exact 15-minute candle OPEN/CLOSE
from intraday candle data, not delayed spot quotes.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from config import (
    SIGNAL_CONFIRM_MIN_SECONDS,
    SIGNAL_CONFIRM_MAX_SECONDS,
    SIGNAL_CONFIRM_CHECK_INTERVAL,
    TRADE_DURATION_MINUTES,
    TRADING_PAIRS,
    TRADING_START_HOUR_UTC,
    TRADING_END_HOUR_UTC,
    BOT_TIMEZONE,
    RESULT_CANDLE_BUFFER_SECONDS,
    RESULT_FETCH_RETRY_SECONDS,
    RESULT_MAX_WAIT_AFTER_EXPIRY_SECONDS,
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
        self.active_pending = {}
        self.pending_results = {}
        self.active_trade = None
        self.active_trade_lock = asyncio.Lock()
        self._last_signal = {}

    def is_trading_hours(self):
        if TRADING_START_HOUR_UTC == 0 and TRADING_END_HOUR_UTC == 24:
            return True
        now = datetime.now(timezone.utc)
        return TRADING_START_HOUR_UTC <= now.hour < TRADING_END_HOUR_UTC

    def is_valid_pair(self, pair):
        return pair.upper().replace("/", "") in TRADING_PAIRS

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
                if raw.isdigit():
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
            logger.warning("Failed to parse target entry time from payload: %s", exc)

        return self.get_next_candle_time()

    def utc_to_local(self, dt):
        return dt.astimezone(BOT_TIMEZONE)

    def has_active_trade(self):
        return self.active_trade is not None

    async def process_webhook_signal(self, data):
        pair = data.get("pair", "").upper().replace("/", "")
        direction = data.get("direction", "").upper()
        action = data.get("action", "SIGNAL").upper()
        indicators = data.get("indicators", {})

        logger.info("Webhook: %s %s %s", pair, direction, action)

        if not is_signals_enabled():
            return {"status": "disabled"}

        if not self.is_valid_pair(pair):
            return {"status": "error", "message": f"Invalid pair: {pair}"}

        if direction not in ["CALL", "PUT"]:
            return {"status": "error", "message": f"Invalid direction: {direction}"}

        if not self.is_trading_hours():
            return {"status": "skipped", "message": "Outside trading hours"}

        if action == "SIGNAL":
            self._last_signal[pair] = {
                "direction": direction,
                "time": datetime.now(timezone.utc),
            }

        if action == "CANCEL":
            self._last_signal.pop(pair, None)
            return await self._cancel_active_pending(pair)

        if self.has_active_trade():
            return {"status": "blocked", "message": "Active trade in progress"}

        if pair in self.active_pending and not self.active_pending[pair].done():
            return {"status": "duplicate", "message": f"Pending signal exists for {pair}"}

        return await self._create_temporary_signal(pair, direction, indicators, data)

    async def _create_temporary_signal(self, pair, direction, indicators, payload):
        now = datetime.now(timezone.utc)
        target_entry = self.get_target_entry_time_from_payload(payload)

        signal_id = create_pending_signal(
            pair=pair,
            direction=direction,
            detected_at=now.isoformat(),
            target_entry_time=target_entry.isoformat(),
            indicator_data=indicators,
        )

        local_entry = self.utc_to_local(target_entry)
        logger.info(
            "Pending #%s: %s %s (entry %s UTC+3)",
            signal_id,
            pair,
            direction,
            local_entry.strftime("%H:%M"),
        )

        if pair in self.active_pending:
            old_task = self.active_pending[pair]
            if not old_task.done():
                old_task.cancel()

        task = asyncio.create_task(
            self._smart_confirmation(signal_id, pair, direction, target_entry, indicators)
        )
        self.active_pending[pair] = task
        return {"status": "pending", "signal_id": signal_id}

    async def _smart_confirmation(self, signal_id, pair, direction, target_entry, indicators):
        try:
            elapsed = 0
            confirmed = False

            while elapsed < SIGNAL_CONFIRM_MAX_SECONDS:
                await asyncio.sleep(SIGNAL_CONFIRM_CHECK_INTERVAL)
                elapsed += SIGNAL_CONFIRM_CHECK_INTERVAL

                if not is_signals_enabled():
                    cancel_pending_signal(signal_id)
                    logger.info("#%s cancelled - signals disabled", signal_id)
                    return

                if self.has_active_trade():
                    cancel_pending_signal(signal_id)
                    logger.info("#%s cancelled - active trade appeared", signal_id)
                    self.active_pending.pop(pair, None)
                    return

                last = self._last_signal.get(pair)
                if not last or last["direction"] != direction:
                    cancel_pending_signal(signal_id)
                    logger.info("#%s cancelled - signal disappeared for %s", signal_id, pair)
                    self.active_pending.pop(pair, None)
                    return

                if elapsed >= SIGNAL_CONFIRM_MIN_SECONDS:
                    confirmed = True
                    break

            if not confirmed:
                cancel_pending_signal(signal_id)
                logger.info("#%s timed out after %ss", signal_id, elapsed)
                self.active_pending.pop(pair, None)
                return

            confirm_pending_signal(signal_id)
            logger.info("#%s CONFIRMED after %ss: %s %s", signal_id, elapsed, pair, direction)

            local_entry = self.utc_to_local(target_entry)
            entry_time_str = local_entry.strftime("%H:%M")

            trade_id = create_trade(
                pair=pair,
                direction=direction,
                entry_time=target_entry.isoformat(),
                entry_price=None,
            )

            async with self.active_trade_lock:
                self.active_trade = {
                    "trade_id": trade_id,
                    "pair": pair,
                    "direction": direction,
                    "entry_time": entry_time_str,
                    "target_entry_utc": target_entry,
                }

            stats = get_pair_statistics(pair) or {"total_wins": 0, "total_losses": 0}
            await self.telegram.send_signal(
                pair=pair,
                direction=direction,
                entry_time=entry_time_str,
                stats=stats,
            )
            logger.info("Signal sent: %s %s at %s", pair, direction, entry_time_str)

            result_task = asyncio.create_task(
                self._monitor_trade(trade_id, pair, direction, entry_time_str, target_entry)
            )
            self.pending_results[trade_id] = result_task

            self.active_pending.pop(pair, None)
            self._last_signal.pop(pair, None)

        except asyncio.CancelledError:
            cancel_pending_signal(signal_id)
            logger.info("#%s cancelled externally", signal_id)
            self.active_pending.pop(pair, None)
        except Exception as exc:
            logger.error("Error in confirmation #%s: %s", signal_id, exc, exc_info=True)
            cancel_pending_signal(signal_id)
            self.active_pending.pop(pair, None)

    async def _cancel_active_pending(self, pair):
        if pair in self.active_pending:
            task = self.active_pending[pair]
            if not task.done():
                task.cancel()
                return {"status": "cancelled"}
        return {"status": "no_pending"}

    async def _wait_for_trade_candle(self, pair, target_entry, expiry):
        deadline = expiry + timedelta(seconds=RESULT_MAX_WAIT_AFTER_EXPIRY_SECONDS)
        while datetime.now(timezone.utc) <= deadline:
            candle = await price_service.get_trade_candle(pair, target_entry)
            if candle and candle.get("entry_price") is not None and candle.get("exit_price") is not None:
                return candle
            await asyncio.sleep(RESULT_FETCH_RETRY_SECONDS)
        return None

    def _determine_result(self, direction, entry_price, exit_price):
        if direction == "CALL":
            return "WIN" if exit_price > entry_price else "LOSS"
        return "WIN" if exit_price < entry_price else "LOSS"

    async def _monitor_trade(self, trade_id, pair, direction, entry_time_str, target_entry):
        try:
            now = datetime.now(timezone.utc)
            wait_until_entry = (target_entry - now).total_seconds()
            if wait_until_entry > 0:
                logger.info("Trade #%s: waiting %.0fs until entry", trade_id, wait_until_entry)
                await asyncio.sleep(wait_until_entry)

            await asyncio.sleep(RESULT_CANDLE_BUFFER_SECONDS)

            # Save entry open from the exact 15m candle if already available.
            entry_open = await price_service.get_candle_open(pair, target_entry)
            if entry_open is not None:
                update_trade_entry_price(trade_id, entry_open)
                logger.info("Trade #%s: exact candle open saved = %s", trade_id, entry_open)

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
                logger.info(
                    "Trade #%s: reliable candle result via %s (%s) | entry=%s exit=%s => %s",
                    trade_id,
                    candle.get("source"),
                    candle.get("consensus"),
                    entry_price,
                    exit_price,
                    result,
                )
            else:
                logger.warning(
                    "Trade #%s: exact 15m candle unavailable after retries. Falling back to current spot quote.",
                    trade_id,
                )
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
                pair=pair,
                direction=direction,
                entry_time=entry_time_str,
                result=result,
            )

            logger.info(
                "Trade #%s completed: %s (entry=%s, exit=%s)",
                trade_id,
                result,
                entry_price,
                exit_price,
            )

        except Exception as exc:
            logger.error("Error in trade #%s: %s", trade_id, exc, exc_info=True)
        finally:
            async with self.active_trade_lock:
                self.active_trade = None
            self.pending_results.pop(trade_id, None)
            logger.info("Trade completed. Ready for new signals.")
