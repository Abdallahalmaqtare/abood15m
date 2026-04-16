"""
Aboud Trading Bot - Signal Manager v5.3
======================================
FIX v5.3:
- Auto-corrects entry time when PineScript sends time_close + 15min (old indicator)
- Computes next 15-min candle boundary from signal_time for maximum reliability
- Removes rigid timing validation that was rejecting valid signals
"""

import asyncio
import logging
import math
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
        self.active_signals = {}
        self.active_trade = None
        self.active_trade_lock = asyncio.Lock()
        self._processing_lock = asyncio.Lock()

    # ── main.py calls this name ──
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
            logger.info("🚫 Cancel ignored for %s", pair)
            return {"status": "ignored", "message": "Cancel ignored"}

        return await self.process_signal(data)

    # ─────────────────────────────────────────
    #  CORE: process incoming signal
    # ─────────────────────────────────────────
    async def process_signal(self, signal_data: dict) -> dict:
        async with self._processing_lock:
            pair = (signal_data.get("ticker") or signal_data.get("pair") or "").upper().replace("/", "")
            direction = str(signal_data.get("direction", "")).upper()
            raw_signal_time = signal_data.get("signal_time")
            raw_entry_time = signal_data.get("target_entry_time") or signal_data.get("entry_time")

            try:
                signal_score = int(float(signal_data.get("signal_score", 0) or 0))
            except (ValueError, TypeError):
                signal_score = 0

            logger.info(
                "📨 Signal received: pair=%s dir=%s score=%s raw_entry=%s raw_signal=%s",
                pair, direction, signal_score, raw_entry_time, raw_signal_time,
            )

            # ── Basic validation ──
            if not is_signals_enabled():
                return {"status": "rejected", "message": "Signals disabled"}
            if pair not in TRADING_PAIRS:
                return {"status": "rejected", "message": f"Pair {pair} not allowed"}
            if direction not in ("CALL", "PUT"):
                return {"status": "rejected", "message": f"Invalid direction {direction}"}
            if signal_score < MIN_SIGNAL_SCORE:
                return {"status": "rejected", "message": f"Score {signal_score} < {MIN_SIGNAL_SCORE}"}
            if not self._is_trading_hours():
                return {"status": "rejected", "message": "Outside trading hours"}
            now_utc = datetime.now(timezone.utc)
            if now_utc.weekday() >= 5:
                return {"status": "rejected", "message": "Weekend"}
            if not self._check_cooldown(pair):
                return {"status": "rejected", "message": f"Cooldown active for {pair}"}

            # ── Smart entry time calculation ──
            entry_dt = self._compute_entry_time(raw_entry_time, raw_signal_time)
            if entry_dt is None:
                return {"status": "rejected", "message": "Cannot determine entry time"}

            normalized_entry_time = entry_dt.strftime("%Y-%m-%d %H:%M:%S")
            diff_seconds = (entry_dt - now_utc).total_seconds()
            logger.info(
                "✅ Signal ACCEPTED: %s %s score=%s entry=%s (in %.1f min)",
                pair, direction, signal_score, normalized_entry_time, diff_seconds / 60,
            )

            # ── Save to DB ──
            try:
                pending_id = create_pending_signal(
                    pair=pair,
                    direction=direction,
                    signal_time=str(raw_signal_time or ""),
                    entry_time=normalized_entry_time,
                    status="ACCEPTED",
                    signal_score=signal_score,
                )
            except Exception as e:
                logger.exception("❌ DB error: %s", e)
                return {"status": "error", "message": f"Database error: {e}"}

            self.active_signals[pair] = now_utc

            # ── Send Telegram ──
            pair_stats = get_statistics(pair) or {}
            send_stats = {
                "total_wins": int(pair_stats.get("total_wins", 0)),
                "total_losses": int(pair_stats.get("total_losses", 0)),
            }
            try:
                await self.telegram_sender.send_signal(
                    pair, direction, normalized_entry_time, send_stats, score=signal_score,
                )
                logger.info("📤 Telegram signal sent: %s %s", pair, direction)
            except Exception as e:
                logger.exception("❌ Telegram send failed: %s", e)

            # ── Monitor trade in background ──
            asyncio.create_task(
                self._monitor_trade(
                    pending_id=pending_id,
                    pair=pair,
                    direction=direction,
                    entry_time=normalized_entry_time,
                    entry_dt=entry_dt,
                    signal_score=signal_score,
                )
            )

            return {
                "status": "accepted",
                "message": f"Signal accepted: {pair} {direction} ({signal_score}/10)",
                "pending_id": pending_id,
            }

    # ─────────────────────────────────────────
    #  SMART ENTRY TIME
    # ─────────────────────────────────────────
    def _compute_entry_time(self, raw_entry, raw_signal):
        """
        Determine the correct 15-min candle entry time.

        Strategy:
        1. Parse signal_time (= candle close = next candle open) → that IS the entry.
        2. If signal_time unavailable, parse target_entry_time and auto-correct
           if it's too far (old PineScript adds +15min).
        3. Fallback: next 15-min boundary from now.
        """
        now = datetime.now(timezone.utc)

        # Try using signal_time directly — it equals time_close = next candle open
        signal_dt = self._parse_timestamp(raw_signal)
        if signal_dt:
            diff = (signal_dt - now).total_seconds()
            # signal_time should be in the recent past or very near future (candle just closed)
            if -120 <= diff <= 120:
                # The candle JUST closed at signal_dt, so the next candle starts at signal_dt
                # But since it already passed or is at exactly now, use it as entry
                logger.info("📍 Using signal_time as entry: %s", signal_dt.strftime("%H:%M:%S"))
                return signal_dt

        # Parse raw entry time
        entry_dt = self._parse_timestamp(raw_entry)
        if entry_dt:
            diff = (entry_dt - now).total_seconds()
            minutes_until = diff / 60.0

            if -60 <= diff <= 960:
                # Entry is within 0-16 min → use as-is
                logger.info("📍 Using target_entry_time as-is: %s (%.1f min)", entry_dt.strftime("%H:%M:%S"), minutes_until)
                return entry_dt

            if 960 < diff <= 2400:
                # Entry is 16-40 min away → old PineScript bug, subtract 15 min
                corrected = entry_dt - timedelta(minutes=15)
                logger.info(
                    "📍 Auto-corrected entry: %s → %s (was %.1f min away, now %.1f)",
                    entry_dt.strftime("%H:%M:%S"),
                    corrected.strftime("%H:%M:%S"),
                    minutes_until,
                    (corrected - now).total_seconds() / 60,
                )
                return corrected

        # Fallback: next 15-minute boundary from now
        fallback = self._next_15min_boundary(now)
        logger.info("📍 Fallback entry (next 15m boundary): %s", fallback.strftime("%H:%M:%S"))
        return fallback

    def _next_15min_boundary(self, dt: datetime) -> datetime:
        """Return the next 15-minute candle start >= dt."""
        minute = dt.minute
        next_slot = (math.ceil((minute + 1) / 15)) * 15
        if next_slot >= 60:
            result = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            result = dt.replace(minute=next_slot, second=0, microsecond=0)
        return result

    # ─────────────────────────────────────────
    #  TRADE MONITORING
    # ─────────────────────────────────────────
    async def _monitor_trade(self, pending_id, pair, direction, entry_time, entry_dt, signal_score=0):
        try:
            wait_seconds = (entry_dt - datetime.now(timezone.utc)).total_seconds()
            if wait_seconds > 0:
                logger.info("⏳ Waiting %.1f sec for %s %s entry", wait_seconds, pair, direction)
                await asyncio.sleep(wait_seconds)

            await asyncio.sleep(3)

            candle = await self.price_service.get_trade_candle(pair, entry_dt)
            entry_price = candle.get("entry_price") if candle else None
            if entry_price is None:
                entry_price = await self.price_service.get_price(pair)

            expiry_dt = entry_dt + timedelta(minutes=TRADE_DURATION_MINUTES)
            expiry_time = expiry_dt.strftime("%Y-%m-%d %H:%M:%S")

            try:
                trade_id = create_trade(
                    pair=pair, direction=direction,
                    entry_time=entry_time, expiry_time=expiry_time,
                    status="ACTIVE", signal_score=signal_score,
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
                    "id": trade_id, "pair": pair, "direction": direction,
                    "entry_time": entry_time, "expiry_time": expiry_time,
                    "entry_price": entry_price, "signal_score": signal_score,
                }

            remaining = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                logger.info("⏳ Trade #%s active for %.1f sec", trade_id, remaining)
                await asyncio.sleep(remaining)

            await asyncio.sleep(6)

            result_candle = await self.price_service.get_trade_candle(pair, entry_dt)
            exit_price = result_candle.get("exit_price") if result_candle else None
            if exit_price is None:
                exit_price = await self.price_service.get_price(pair)

            result = self._determine_result(direction, entry_price, exit_price)
            logger.info("📊 Result: %s %s → %s (entry=%s exit=%s)", pair, direction, result, entry_price, exit_price)

            update_trade(trade_id, exit_price=exit_price, status="COMPLETED", result=result)
            update_statistics(pair, result)
            update_pending_signal(pending_id, "COMPLETED")

            try:
                await self.telegram_sender.send_result(pair, direction, entry_time, result)
            except Exception as e:
                logger.exception("❌ Telegram result failed: %s", e)

            async with self.active_trade_lock:
                self.active_trade = None

        except asyncio.CancelledError:
            logger.info("Trade monitor cancelled for %s", pair)
        except Exception as e:
            logger.exception("❌ Trade monitor error: %s %s: %s", pair, direction, e)
            async with self.active_trade_lock:
                self.active_trade = None

    # ─────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────
    def _determine_result(self, direction, entry_price, exit_price):
        if entry_price is None or exit_price is None:
            return "DRAW"
        if direction == "CALL":
            return "WIN" if exit_price > entry_price else ("LOSS" if exit_price < entry_price else "DRAW")
        return "WIN" if exit_price < entry_price else ("LOSS" if exit_price > entry_price else "DRAW")

    def _is_trading_hours(self) -> bool:
        hour = datetime.now(timezone.utc).hour
        if TRADING_START_HOUR_UTC <= TRADING_END_HOUR_UTC:
            return TRADING_START_HOUR_UTC <= hour < TRADING_END_HOUR_UTC
        return hour >= TRADING_START_HOUR_UTC or hour < TRADING_END_HOUR_UTC

    def _check_cooldown(self, pair: str) -> bool:
        last = self.active_signals.get(pair)
        if not last:
            return True
        return (datetime.now(timezone.utc) - last).total_seconds() >= (SIGNAL_COOLDOWN_MINUTES * 60)

    def _parse_timestamp(self, value):
        """Parse a timestamp from various formats (ms epoch, seconds epoch, string)."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)

        # Numeric (int or string of digits)
        try:
            ts = int(str(value).strip())
            if ts > 1_000_000_000_000:
                ts = ts / 1000  # ms → seconds
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass

        text = str(value).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        logger.warning("⚠️ Cannot parse timestamp: %s", value)
        return None
