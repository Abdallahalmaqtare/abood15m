"""
Aboud Trading Bot - Signal Manager v2
=====================================
FIXES:
1. One trade at a time (no overlapping)
2. Result checked from ENTRY TIME + 15 min (not send time)
3. All display times in UTC+3
4. No duplicate signals for same pair/entry
"""

import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta

from config import (
    SIGNAL_CONFIRM_DELAY_SECONDS,
    TRADE_DURATION_MINUTES,
    TRADING_PAIRS,
    TRADING_START_HOUR_UTC,
    TRADING_END_HOUR_UTC,
    BOT_TIMEZONE,
    BOT_UTC_OFFSET,
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
    has_active_trade,
    find_duplicate_trade,
)
from price_service import price_service

logger = logging.getLogger(__name__)


class SignalManager:
    """Manages the complete signal lifecycle."""

    def __init__(self, telegram_sender):
        self.telegram = telegram_sender
        self.active_pending = {}  # {pair: asyncio.Task}
        self.pending_results = {}  # {trade_id: asyncio.Task}
        self._trade_lock = False  # Global lock: one trade at a time

    def is_trading_hours(self):
        now = datetime.now(timezone.utc)
        if TRADING_START_HOUR_UTC == 0 and TRADING_END_HOUR_UTC == 24:
            return True
        return TRADING_START_HOUR_UTC <= now.hour < TRADING_END_HOUR_UTC

    def is_valid_pair(self, pair):
        return pair.upper().replace("/", "") in TRADING_PAIRS

    def get_next_candle_time(self):
        """Calculate the next 15-minute candle opening time."""
        now = datetime.now(timezone.utc)
        minutes = now.minute
        next_slot = ((minutes // 15) + 1) * 15
        if next_slot >= 60:
            next_candle = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_candle = now.replace(minute=next_slot, second=0, microsecond=0)
        return next_candle

    def utc_to_local(self, utc_time):
        """Convert UTC datetime to local timezone (UTC+3)."""
        return utc_time.astimezone(BOT_TIMEZONE)

    def format_local_time(self, utc_time):
        """Format UTC time as local time string HH:MM."""
        local = self.utc_to_local(utc_time)
        return local.strftime("%H:%M")

    async def process_webhook_signal(self, data):
        """
        Process incoming webhook signal from TradingView.
        """
        pair = data.get("pair", "").upper().replace("/", "")
        direction = data.get("direction", "").upper()
        action = data.get("action", "SIGNAL").upper()
        indicators = data.get("indicators", {})

        logger.info(f"Received webhook: {pair} {direction} {action}")

        # === VALIDATION ===

        if not is_signals_enabled():
            logger.info("Signals are disabled. Ignoring.")
            return {"status": "disabled", "message": "Signals are currently disabled"}

        if not self.is_valid_pair(pair):
            logger.warning(f"Invalid pair: {pair}")
            return {"status": "error", "message": f"Invalid pair: {pair}"}

        if direction not in ["CALL", "PUT"]:
            logger.warning(f"Invalid direction: {direction}")
            return {"status": "error", "message": f"Invalid direction: {direction}"}

        if not self.is_trading_hours():
            logger.info("Outside trading hours. Ignoring signal.")
            return {"status": "skipped", "message": "Outside trading hours"}

        # === FIX 1: Block if there is an active trade ===
        if action != "CANCEL" and (self._trade_lock or has_active_trade()):
            logger.info(f"Active trade exists. Ignoring new signal for {pair} {direction}")
            return {
                "status": "blocked",
                "message": "Active trade in progress. Signal ignored."
            }

        # Handle CANCEL action
        if action == "CANCEL":
            return await self._cancel_active_pending(pair, direction)

        # Create temporary signal
        return await self._create_temporary_signal(pair, direction, indicators)

    async def _create_temporary_signal(self, pair, direction, indicators):
        """Create a temporary signal and start the 2-minute timer."""
        now = datetime.now(timezone.utc)
        next_candle = self.get_next_candle_time()

        # === FIX 4: Check for duplicate ===
        existing = find_duplicate_trade(pair, next_candle.isoformat())
        if existing:
            logger.info(f"Duplicate signal for {pair} at {next_candle}. Ignoring.")
            return {"status": "duplicate", "message": "Duplicate signal ignored"}

        # Create pending signal in DB
        signal_id = create_pending_signal(
            pair=pair,
            direction=direction,
            detected_at=now.isoformat(),
            target_entry_time=next_candle.isoformat(),
            indicator_data=indicators
        )

        logger.info(
            f"Created pending signal #{signal_id}: {pair} {direction} "
            f"(target entry: {self.format_local_time(next_candle)})"
        )

        # Cancel any existing pending signal for the same pair
        if pair in self.active_pending:
            old_task = self.active_pending[pair]
            if not old_task.done():
                old_task.cancel()
                logger.info(f"Cancelled previous pending signal for {pair}")

        # Start confirmation timer
        task = asyncio.create_task(
            self._confirmation_timer(signal_id, pair, direction, next_candle, indicators)
        )
        self.active_pending[pair] = task

        return {
            "status": "pending",
            "signal_id": signal_id,
            "message": f"Signal pending for {pair} {direction}. Confirming in {SIGNAL_CONFIRM_DELAY_SECONDS}s..."
        }

    async def _confirmation_timer(self, signal_id, pair, direction, target_entry, indicators):
        """
        Wait for 2 minutes. If not cancelled, confirm and send.
        """
        try:
            logger.info(f"Starting {SIGNAL_CONFIRM_DELAY_SECONDS}s confirmation timer for signal #{signal_id}")

            await asyncio.sleep(SIGNAL_CONFIRM_DELAY_SECONDS)

            # Double-check: signals still enabled?
            if not is_signals_enabled():
                cancel_pending_signal(signal_id)
                logger.info(f"Signal #{signal_id} cancelled - signals disabled")
                return

            # Double-check: no active trade appeared while waiting?
            if self._trade_lock or has_active_trade():
                cancel_pending_signal(signal_id)
                logger.info(f"Signal #{signal_id} cancelled - another trade is active")
                return

            # === LOCK: Set trade lock ===
            self._trade_lock = True

            # Confirm the signal
            confirm_pending_signal(signal_id)
            logger.info(f"Signal #{signal_id} CONFIRMED: {pair} {direction}")

            # Get entry price
            entry_price = await price_service.get_price(pair)

            # Format entry time in UTC+3
            entry_time_str = self.format_local_time(target_entry)

            # Create trade record
            trade_id = create_trade(
                pair=pair,
                direction=direction,
                entry_time=target_entry.isoformat(),
                entry_price=entry_price
            )

            # Get statistics for this pair
            stats = get_pair_statistics(pair) or {
                "total_wins": 0, "total_losses": 0
            }

            # Send signal to Telegram
            await self.telegram.send_signal(
                pair=pair,
                direction=direction,
                entry_time=entry_time_str,
                stats=stats
            )

            logger.info(f"Signal sent to Telegram: {pair} {direction} at {entry_time_str} (UTC+{BOT_UTC_OFFSET})")

            # === FIX 2: Schedule result check from ENTRY TIME, not from now ===
            result_task = asyncio.create_task(
                self._check_result_after_expiry(
                    trade_id=trade_id,
                    pair=pair,
                    direction=direction,
                    entry_time_str=entry_time_str,
                    entry_price=entry_price,
                    target_entry=target_entry
                )
            )
            self.pending_results[trade_id] = result_task

            # Clean up pending
            if pair in self.active_pending:
                del self.active_pending[pair]

        except asyncio.CancelledError:
            cancel_pending_signal(signal_id)
            logger.info(f"Signal #{signal_id} CANCELLED (timer cancelled): {pair} {direction}")
            if pair in self.active_pending:
                del self.active_pending[pair]

        except Exception as e:
            logger.error(f"Error in confirmation timer for signal #{signal_id}: {e}", exc_info=True)
            cancel_pending_signal(signal_id)
            self._trade_lock = False  # Release lock on error
            if pair in self.active_pending:
                del self.active_pending[pair]

    async def _cancel_active_pending(self, pair, direction):
        """Cancel an active pending signal for a pair."""
        if pair in self.active_pending:
            task = self.active_pending[pair]
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled pending signal for {pair} {direction} via webhook CANCEL")
                return {
                    "status": "cancelled",
                    "message": f"Pending signal for {pair} {direction} cancelled"
                }

        return {
            "status": "no_pending",
            "message": f"No active pending signal found for {pair}"
        }

    async def _check_result_after_expiry(self, trade_id, pair, direction, entry_time_str, entry_price, target_entry):
        """
        FIX 2: Wait until ENTRY TIME + TRADE_DURATION, then check result.
        NOT from signal send time.
        """
        try:
            now = datetime.now(timezone.utc)

            # Calculate how long to wait until entry time
            seconds_until_entry = (target_entry - now).total_seconds()
            if seconds_until_entry < 0:
                seconds_until_entry = 0

            # Total wait = time until entry + trade duration + small buffer
            total_wait = seconds_until_entry + (TRADE_DURATION_MINUTES * 60) + 3

            logger.info(
                f"Trade #{trade_id}: waiting {seconds_until_entry:.0f}s until entry, "
                f"then {TRADE_DURATION_MINUTES * 60}s trade duration. "
                f"Total wait: {total_wait:.0f}s"
            )

            # === Wait until entry time ===
            if seconds_until_entry > 0:
                await asyncio.sleep(seconds_until_entry)

            # === Get ACTUAL entry price at candle open ===
            actual_entry_price = await price_service.get_price(pair)
            if actual_entry_price:
                entry_price = actual_entry_price
                update_trade_entry_price(trade_id, entry_price)
                logger.info(f"Trade #{trade_id}: Updated entry price to {entry_price} at candle open")

            # === Wait for trade duration (15 minutes) ===
            await asyncio.sleep(TRADE_DURATION_MINUTES * 60 + 3)

            # === Get exit price ===
            exit_price = await price_service.get_price(pair)

            if exit_price is None:
                await asyncio.sleep(5)
                exit_price = await price_service.get_price(pair)

            # === Determine result ===
            if entry_price and exit_price:
                if direction == "CALL":
                    is_win = exit_price > entry_price
                else:  # PUT
                    is_win = exit_price < entry_price
                result = "WIN" if is_win else "LOSS"
            else:
                result = "LOSS"
                logger.warning(f"Price unavailable for trade #{trade_id}, defaulting to LOSS")

            # Update trade in database
            update_trade_result(trade_id, exit_price, result)
            update_statistics(pair, result == "WIN")

            # Send result to Telegram
            await self.telegram.send_result(
                pair=pair,
                direction=direction,
                entry_time=entry_time_str,
                result=result
            )

            logger.info(
                f"Trade #{trade_id} result: {result} "
                f"(entry: {entry_price}, exit: {exit_price}, {pair} {direction})"
            )

            # === UNLOCK: Release trade lock ===
            self._trade_lock = False

            # Clean up
            if trade_id in self.pending_results:
                del self.pending_results[trade_id]

        except Exception as e:
            logger.error(f"Error checking result for trade #{trade_id}: {e}", exc_info=True)
            self._trade_lock = False  # Always release lock on error
            if trade_id in self.pending_results:
                del self.pending_results[trade_id]
