"""
Aboud Trading Bot - Signal Manager (FIXED)
=============================================
Handles the core signal logic:
1. Receives temporary signals from TradingView webhook
2. Waits 2 minutes for confirmation
3. Re-validates conditions
4. Sends confirmed signals to Telegram
5. Schedules result checking after 15 minutes FROM ENTRY TIME (not from signal send time)

FIXES APPLIED:
- FIX 1: Result is now checked 15 minutes from ENTRY TIME, not from signal send time
- FIX 2: All times displayed in UTC+3 timezone
- FIX 3: Only ONE trade at a time - bot stops sending signals until current trade finishes
- FIX 4: No duplicate signals for the same pair
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
)
from database import (
    create_pending_signal,
    confirm_pending_signal,
    cancel_pending_signal,
    create_trade,
    update_trade_entry_price,
    is_signals_enabled,
    get_pair_statistics,
)
from price_service import price_service

logger = logging.getLogger(__name__)


class SignalManager:
    """Manages the complete signal lifecycle."""

    def __init__(self, telegram_sender):
        self.telegram = telegram_sender
        self.active_pending = {}  # {pair: asyncio.Task}
        self.pending_results = {}  # {trade_id: asyncio.Task}

        # ===== FIX 3: Track active trade =====
        # Only ONE trade can be active at a time.
        # When a trade is confirmed and waiting for result, no new signals are sent.
        self.active_trade = None  # Will hold info dict when a trade is active
        self.active_trade_lock = asyncio.Lock()

    def is_trading_hours(self):
        """Check if current time is within trading hours."""
        now = datetime.now(timezone.utc)
        return TRADING_START_HOUR_UTC <= now.hour < TRADING_END_HOUR_UTC

    def is_valid_pair(self, pair):
        """Check if the pair is in our trading list."""
        return pair.upper().replace("/", "") in TRADING_PAIRS

    def get_next_candle_time(self):
        """Calculate the next 15-minute candle opening time."""
        now = datetime.now(timezone.utc)
        minutes = now.minute
        # Next 15-min candle: 0, 15, 30, 45
        next_slot = ((minutes // 15) + 1) * 15
        if next_slot >= 60:
            next_candle = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_candle = now.replace(minute=next_slot, second=0, microsecond=0)
        return next_candle

    def utc_to_local(self, utc_dt):
        """
        ===== FIX 2: Convert UTC time to BOT_TIMEZONE (UTC+3) =====
        """
        return utc_dt.astimezone(BOT_TIMEZONE)

    def has_active_trade(self):
        """
        ===== FIX 3: Check if there's an active trade =====
        Returns True if a trade is currently running (waiting for result).
        """
        return self.active_trade is not None

    async def process_webhook_signal(self, data):
        """
        Process incoming webhook signal from TradingView.

        Expected data format:
        {
            "pair": "EURUSD",
            "direction": "CALL" or "PUT",
            "action": "SIGNAL" or "CANCEL",
            "indicators": {
                "ema_fast": 1.0850,
                "ema_slow": 1.0830,
                "rsi": 55.2,
                "supertrend": "UP",
                "adx": 25.3
            }
        }
        """
        pair = data.get("pair", "").upper().replace("/", "")
        direction = data.get("direction", "").upper()
        action = data.get("action", "SIGNAL").upper()
        indicators = data.get("indicators", {})

        logger.info(f"Received webhook: {pair} {direction} {action}")

        # Validations
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

        # Handle CANCEL action (signal reversed before confirmation)
        if action == "CANCEL":
            return await self._cancel_active_pending(pair, direction)

        # ===== FIX 3: Check if there's already an active trade =====
        if self.has_active_trade():
            active = self.active_trade
            logger.info(
                f"BLOCKED: Signal for {pair} {direction} rejected - "
                f"active trade exists: {active['pair']} {active['direction']} "
                f"(entry: {active['entry_time']})"
            )
            return {
                "status": "blocked",
                "message": (
                    f"Signal blocked: active trade in progress "
                    f"({active['pair']} {active['direction']} entry at {active['entry_time']}). "
                    f"Waiting for current trade to finish."
                )
            }

        # ===== FIX 4: Check if there's already a pending signal for this pair =====
        if pair in self.active_pending and not self.active_pending[pair].done():
            logger.info(f"BLOCKED: Duplicate signal for {pair} - pending signal already exists")
            return {
                "status": "duplicate",
                "message": f"Signal blocked: pending signal already exists for {pair}"
            }

        # Create temporary signal
        return await self._create_temporary_signal(pair, direction, indicators)

    async def _create_temporary_signal(self, pair, direction, indicators):
        """Create a temporary signal and start the 2-minute timer."""
        now = datetime.now(timezone.utc)
        next_candle = self.get_next_candle_time()

        # Create pending signal in DB
        signal_id = create_pending_signal(
            pair=pair,
            direction=direction,
            detected_at=now.isoformat(),
            target_entry_time=next_candle.isoformat(),
            indicator_data=indicators
        )

        # ===== FIX 2: Display time in UTC+3 =====
        local_entry = self.utc_to_local(next_candle)
        logger.info(
            f"Created pending signal #{signal_id}: {pair} {direction} "
            f"(target entry: {local_entry.strftime('%H:%M')} UTC+3)"
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
        Wait for SIGNAL_CONFIRM_DELAY_SECONDS (2 minutes).
        If not cancelled by then, confirm and send the signal.
        """
        try:
            logger.info(f"Starting {SIGNAL_CONFIRM_DELAY_SECONDS}s confirmation timer for signal #{signal_id}")

            # Wait 2 minutes
            await asyncio.sleep(SIGNAL_CONFIRM_DELAY_SECONDS)

            # Double-check signals are still enabled
            if not is_signals_enabled():
                cancel_pending_signal(signal_id)
                logger.info(f"Signal #{signal_id} cancelled - signals disabled")
                return

            # ===== FIX 3: Double-check no active trade before confirming =====
            if self.has_active_trade():
                cancel_pending_signal(signal_id)
                logger.info(
                    f"Signal #{signal_id} cancelled - active trade exists when trying to confirm"
                )
                if pair in self.active_pending:
                    del self.active_pending[pair]
                return

            # Confirm the signal!
            confirm_pending_signal(signal_id)
            logger.info(f"Signal #{signal_id} CONFIRMED: {pair} {direction}")

            # Get entry price
            entry_price = await price_service.get_price(pair)

            # ===== FIX 2: Use UTC+3 for display =====
            local_entry = self.utc_to_local(target_entry)
            entry_time_str = local_entry.strftime("%H:%M")

            # Create trade record
            trade_id = create_trade(
                pair=pair,
                direction=direction,
                entry_time=target_entry.isoformat(),
                entry_price=entry_price
            )

            # ===== FIX 3: Mark trade as active =====
            async with self.active_trade_lock:
                self.active_trade = {
                    "trade_id": trade_id,
                    "pair": pair,
                    "direction": direction,
                    "entry_time": entry_time_str,
                    "target_entry_utc": target_entry,
                }
            logger.info(f"Active trade set: {pair} {direction} (trade #{trade_id})")

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

            logger.info(f"Signal sent to Telegram: {pair} {direction} at {entry_time_str} (UTC+3)")

            # ===== FIX 1: Schedule result check from ENTRY TIME, not from now =====
            result_task = asyncio.create_task(
                self._check_result_after_expiry(
                    trade_id, pair, direction, entry_time_str, entry_price, target_entry
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
        ===== FIX 1: Wait until ENTRY TIME + 15 minutes, not from signal send time =====

        Calculate the exact seconds to wait from NOW until (target_entry + 15 minutes).
        This ensures the result is checked based on the actual candle entry time.
        """
        try:
            # Calculate when the trade expires: entry_time + 15 minutes
            expiry_time = target_entry + timedelta(minutes=TRADE_DURATION_MINUTES)
            now = datetime.now(timezone.utc)

            # Calculate how many seconds to wait from NOW until expiry
            wait_seconds = (expiry_time - now).total_seconds()

            if wait_seconds < 0:
                # If expiry is already in the past (shouldn't happen normally)
                wait_seconds = 0
                logger.warning(
                    f"Trade #{trade_id}: expiry time already passed! "
                    f"Entry: {target_entry}, Expiry: {expiry_time}, Now: {now}"
                )

            local_expiry = self.utc_to_local(expiry_time)
            logger.info(
                f"Trade #{trade_id}: Waiting {wait_seconds:.0f}s until expiry at "
                f"{local_expiry.strftime('%H:%M:%S')} UTC+3 "
                f"(entry was {entry_time_str} UTC+3 + {TRADE_DURATION_MINUTES} min)"
            )

            # Wait until the actual expiry time
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

            # Small delay to ensure candle closes
            await asyncio.sleep(2)

            # Get exit price
            exit_price = await price_service.get_price(pair)

            if exit_price is None or entry_price is None:
                logger.error(f"Could not get prices for trade #{trade_id}")
                # Try one more time after a short delay
                await asyncio.sleep(5)
                exit_price = await price_service.get_price(pair)

            # Determine result
            if entry_price and exit_price:
                if direction == "CALL":
                    is_win = exit_price > entry_price
                else:  # PUT
                    is_win = exit_price < entry_price

                result = "WIN" if is_win else "LOSS"
            else:
                # If we can't get prices, mark as unknown but treat as loss for safety
                result = "LOSS"
                logger.warning(f"Price unavailable for trade #{trade_id}, defaulting to LOSS")

            # Update trade in database
            from database import update_trade_result, update_statistics
            update_trade_result(trade_id, exit_price, result)
            update_statistics(pair, result == "WIN")

            # Send result to Telegram
            await self.telegram.send_result(
                pair=pair,
                direction=direction,
                entry_time=entry_time_str,
                result=result
            )

            logger.info(f"Trade #{trade_id} result: {result} ({pair} {direction})")

            # ===== FIX 3: Clear active trade - now the bot can accept new signals =====
            async with self.active_trade_lock:
                self.active_trade = None
            logger.info(f"Active trade cleared. Bot is ready for new signals.")

            # Clean up
            if trade_id in self.pending_results:
                del self.pending_results[trade_id]

        except Exception as e:
            logger.error(f"Error checking result for trade #{trade_id}: {e}", exc_info=True)

            # ===== FIX 3: Clear active trade even on error to prevent bot from being stuck =====
            async with self.active_trade_lock:
                self.active_trade = None
            logger.info(f"Active trade cleared (after error). Bot is ready for new signals.")

            if trade_id in self.pending_results:
                del self.pending_results[trade_id]
