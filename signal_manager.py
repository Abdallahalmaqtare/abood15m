"""
Aboud Trading Bot - Signal Manager v3
========================================
CHANGES:
- Confirmation window: 2-10 minutes (checks every 30s)
- One trade at a time
- Result from entry time + 15 min
- All times UTC+3
- No random resets
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
)
from database import (
    create_pending_signal, confirm_pending_signal, cancel_pending_signal,
    create_trade, update_trade_entry_price, update_trade_result,
    update_statistics, is_signals_enabled, get_pair_statistics,
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
        # Track last webhook per pair to detect if signal is still active
        self._last_signal = {}  # {pair: {"direction": str, "time": datetime}}

    def is_trading_hours(self):
        if TRADING_START_HOUR_UTC == 0 and TRADING_END_HOUR_UTC == 24:
            return True
        now = datetime.now(timezone.utc)
        return TRADING_START_HOUR_UTC <= now.hour < TRADING_END_HOUR_UTC

    def is_valid_pair(self, pair):
        return pair.upper().replace("/", "") in TRADING_PAIRS

    def get_next_candle_time(self):
        now = datetime.now(timezone.utc)
        m = now.minute
        ns = ((m // 15) + 1) * 15
        if ns >= 60:
            return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return now.replace(minute=ns, second=0, microsecond=0)

    def utc_to_local(self, dt):
        return dt.astimezone(BOT_TIMEZONE)

    def has_active_trade(self):
        return self.active_trade is not None

    async def process_webhook_signal(self, data):
        pair = data.get("pair", "").upper().replace("/", "")
        direction = data.get("direction", "").upper()
        action = data.get("action", "SIGNAL").upper()
        indicators = data.get("indicators", {})

        logger.info(f"Webhook: {pair} {direction} {action}")

        if not is_signals_enabled():
            return {"status": "disabled"}

        if not self.is_valid_pair(pair):
            return {"status": "error", "message": f"Invalid pair: {pair}"}

        if direction not in ["CALL", "PUT"]:
            return {"status": "error", "message": f"Invalid direction: {direction}"}

        if not self.is_trading_hours():
            return {"status": "skipped", "message": "Outside trading hours"}

        # Update last signal tracker
        if action == "SIGNAL":
            self._last_signal[pair] = {
                "direction": direction,
                "time": datetime.now(timezone.utc),
            }

        if action == "CANCEL":
            # Remove from tracker
            self._last_signal.pop(pair, None)
            return await self._cancel_active_pending(pair, direction)

        # Block if active trade exists
        if self.has_active_trade():
            return {"status": "blocked", "message": "Active trade in progress"}

        # Block duplicate pending
        if pair in self.active_pending and not self.active_pending[pair].done():
            return {"status": "duplicate", "message": f"Pending signal exists for {pair}"}

        return await self._create_temporary_signal(pair, direction, indicators)

    async def _create_temporary_signal(self, pair, direction, indicators):
        now = datetime.now(timezone.utc)
        next_candle = self.get_next_candle_time()

        signal_id = create_pending_signal(
            pair=pair, direction=direction,
            detected_at=now.isoformat(),
            target_entry_time=next_candle.isoformat(),
            indicator_data=indicators
        )

        local_entry = self.utc_to_local(next_candle)
        logger.info(f"Pending #{signal_id}: {pair} {direction} (entry: {local_entry.strftime('%H:%M')} UTC+3)")

        if pair in self.active_pending:
            old = self.active_pending[pair]
            if not old.done():
                old.cancel()

        task = asyncio.create_task(
            self._smart_confirmation(signal_id, pair, direction, next_candle, indicators)
        )
        self.active_pending[pair] = task

        return {"status": "pending", "signal_id": signal_id}

    async def _smart_confirmation(self, signal_id, pair, direction, target_entry, indicators):
        """
        Smart confirmation: wait 2-10 minutes.
        Every 30 seconds, check if the signal is still valid.
        Send as soon as confirmed after minimum 2 minutes.
        Cancel if signal disappears before confirmation.
        """
        try:
            elapsed = 0
            confirmed = False

            while elapsed < SIGNAL_CONFIRM_MAX_SECONDS:
                await asyncio.sleep(SIGNAL_CONFIRM_CHECK_INTERVAL)
                elapsed += SIGNAL_CONFIRM_CHECK_INTERVAL

                # Check if cancelled externally
                if not is_signals_enabled():
                    cancel_pending_signal(signal_id)
                    logger.info(f"#{signal_id} cancelled - signals disabled")
                    return

                if self.has_active_trade():
                    cancel_pending_signal(signal_id)
                    logger.info(f"#{signal_id} cancelled - active trade appeared")
                    if pair in self.active_pending:
                        del self.active_pending[pair]
                    return

                # Check if signal still exists (not cancelled by CANCEL webhook)
                last = self._last_signal.get(pair)
                if not last or last["direction"] != direction:
                    cancel_pending_signal(signal_id)
                    logger.info(f"#{signal_id} cancelled - signal disappeared for {pair}")
                    if pair in self.active_pending:
                        del self.active_pending[pair]
                    return

                # After minimum time, confirm
                if elapsed >= SIGNAL_CONFIRM_MIN_SECONDS:
                    confirmed = True
                    break

            if not confirmed:
                cancel_pending_signal(signal_id)
                logger.info(f"#{signal_id} timed out after {elapsed}s")
                if pair in self.active_pending:
                    del self.active_pending[pair]
                return

            # === CONFIRMED ===
            confirm_pending_signal(signal_id)
            logger.info(f"#{signal_id} CONFIRMED after {elapsed}s: {pair} {direction}")

            local_entry = self.utc_to_local(target_entry)
            entry_time_str = local_entry.strftime("%H:%M")

            trade_id = create_trade(
                pair=pair, direction=direction,
                entry_time=target_entry.isoformat(),
                entry_price=None
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
                pair=pair, direction=direction,
                entry_time=entry_time_str, stats=stats
            )

            logger.info(f"Signal sent: {pair} {direction} at {entry_time_str}")

            # Monitor trade lifecycle
            result_task = asyncio.create_task(
                self._monitor_trade(trade_id, pair, direction, entry_time_str, target_entry)
            )
            self.pending_results[trade_id] = result_task

            if pair in self.active_pending:
                del self.active_pending[pair]

            # Clean signal tracker
            self._last_signal.pop(pair, None)

        except asyncio.CancelledError:
            cancel_pending_signal(signal_id)
            logger.info(f"#{signal_id} CANCELLED externally")
            if pair in self.active_pending:
                del self.active_pending[pair]
        except Exception as e:
            logger.error(f"Error in confirmation #{signal_id}: {e}", exc_info=True)
            cancel_pending_signal(signal_id)
            if pair in self.active_pending:
                del self.active_pending[pair]

    async def _cancel_active_pending(self, pair, direction):
        if pair in self.active_pending:
            task = self.active_pending[pair]
            if not task.done():
                task.cancel()
                return {"status": "cancelled"}
        return {"status": "no_pending"}

    async def _monitor_trade(self, trade_id, pair, direction, entry_time_str, target_entry):
        """Wait until entry, capture price, wait 15 min, check result."""
        try:
            now = datetime.now(timezone.utc)

            # Wait until entry
            wait = (target_entry - now).total_seconds()
            if wait > 0:
                logger.info(f"Trade #{trade_id}: waiting {wait:.0f}s until entry")
                await asyncio.sleep(wait)

            await asyncio.sleep(1)

            # Capture entry price
            entry_price = await price_service.get_price(pair)
            if not entry_price:
                await asyncio.sleep(3)
                entry_price = await price_service.get_price(pair)

            if entry_price:
                update_trade_entry_price(trade_id, entry_price)
                logger.info(f"Trade #{trade_id}: entry price = {entry_price}")

            # Wait until expiry
            expiry = target_entry + timedelta(minutes=TRADE_DURATION_MINUTES)
            now = datetime.now(timezone.utc)
            wait = (expiry - now).total_seconds()
            if wait > 0:
                logger.info(f"Trade #{trade_id}: waiting {wait:.0f}s until expiry")
                await asyncio.sleep(wait)

            await asyncio.sleep(2)

            # Capture exit price
            exit_price = await price_service.get_price(pair)
            if not exit_price:
                await asyncio.sleep(3)
                exit_price = await price_service.get_price(pair)

            # Determine result
            if entry_price and exit_price:
                if direction == "CALL":
                    is_win = exit_price > entry_price
                else:
                    is_win = exit_price < entry_price
                result = "WIN" if is_win else "LOSS"
            else:
                result = "LOSS"

            update_trade_result(trade_id, exit_price, result)
            update_statistics(pair, result == "WIN")

            await self.telegram.send_result(
                pair=pair, direction=direction,
                entry_time=entry_time_str, result=result
            )

            logger.info(f"Trade #{trade_id}: {result} (entry={entry_price}, exit={exit_price})")

            # Release lock
            async with self.active_trade_lock:
                self.active_trade = None
            logger.info("Trade completed. Ready for new signals.")

            self.pending_results.pop(trade_id, None)

        except Exception as e:
            logger.error(f"Error in trade #{trade_id}: {e}", exc_info=True)
            async with self.active_trade_lock:
                self.active_trade = None
            self.pending_results.pop(trade_id, None)
