"""
Aboud Trading Bot - Signal Manager v6.0 (TV-RESULT DELIVERY)
============================================================
What's new vs v5.3
------------------
- PRIMARY result source is now the TradingView `action=RESULT` webhook
  (sent by Pine Script v6.1 on close of the entry candle). This contains
  the real entry_price (candle open) and exit_price (candle close).
- The bot waits for that webhook using an asyncio.Future, so the WIN/LOSS
  message is delivered IMMEDIATELY when the candle closes.
- External price APIs (TwelveData / Yahoo) are kept ONLY as a last-resort
  fallback (used if TradingView webhook fails to arrive within the grace
  window after expiry).
- Duplicate RESULT webhooks for the same pair are ignored (idempotent).
- Exactly 2 TradingView webhook calls per trade (SIGNAL + RESULT), so
  TradingView is never overloaded.
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

# How long to wait AFTER the entry candle is supposed to close before we give
# up on TradingView and fall back to the external API. Keep this short —
# TradingView normally fires the alert within 1-2 seconds of candle close.
TV_RESULT_GRACE_SECONDS = 90


class SignalManager:
    """Receives, validates, sends, and tracks trading signals."""

    def __init__(self, telegram_sender, price_service=None):
        self.telegram_sender = telegram_sender
        self.price_service = price_service or default_price_service
        self.active_signals = {}           # pair -> last signal UTC datetime
        self.active_trade = None           # used by admin_bot manual close helper
        self.active_trade_lock = asyncio.Lock()
        self._processing_lock = asyncio.Lock()

        # pair (upper) -> asyncio.Future that resolves with TradingView's
        # {entry_price, exit_price} when the RESULT webhook arrives.
        self._result_futures = {}

    # ─────────────────────────────────────────────────────────────
    # Compatibility alias expected by main.py
    # ─────────────────────────────────────────────────────────────
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

        # NEW: TradingView result webhook — deliver exit price straight from TV.
        if action == "RESULT":
            return await self._handle_tv_result(data)

        return await self.process_signal(data)

    # ─────────────────────────────────────────────────────────────
    # NEW: TradingView RESULT webhook handler
    # ─────────────────────────────────────────────────────────────
    async def _handle_tv_result(self, data: dict) -> dict:
        pair = (data.get("ticker") or data.get("pair") or "").upper().replace("/", "")
        if not pair:
            return {"status": "rejected", "message": "Missing pair"}

        try:
            entry_price = float(data.get("entry_price"))
            exit_price = float(data.get("exit_price"))
        except (TypeError, ValueError):
            logger.warning("RESULT webhook missing/bad prices: %s", data)
            return {"status": "rejected", "message": "Bad prices"}

        fut = self._result_futures.get(pair)
        if fut and not fut.done():
            fut.set_result({
                "entry_price": entry_price,
                "exit_price": exit_price,
                "source": "tradingview",
            })
            logger.info(
                "🎯 TV RESULT received for %s: entry=%s exit=%s — delivering to monitor",
                pair, entry_price, exit_price,
            )
            return {"status": "accepted", "message": f"Result delivered for {pair}"}

        # No active trade waiting — this is either a duplicate or a late signal.
        # Ignore silently so TradingView doesn't retry.
        logger.info(
            "ℹ️  TV RESULT for %s ignored (no active trade waiting). entry=%s exit=%s",
            pair, entry_price, exit_price,
        )
        return {"status": "ignored", "message": "No active trade"}

    # ─────────────────────────────────────────────────────────────
    # Main SIGNAL pipeline
    # ─────────────────────────────────────────────────────────────
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

    # ─────────────────────────────────────────────────────────────
    # Trade monitor — waits for TV RESULT webhook (primary) or API (fallback)
    # ─────────────────────────────────────────────────────────────
    async def _monitor_trade(self, pending_id, pair, direction, entry_time, signal_score=0):
        try:
            entry_dt = self._parse_entry_time(entry_time)
            if not entry_dt:
                logger.error("❌ Cannot parse entry time: %s", entry_time)
                delete_pending_signal(pending_id)
                return

            # Register a future BEFORE we sleep, so a fast TV RESULT webhook
            # that arrives while we're still waiting for the entry candle to
            # open can still be delivered.
            loop = asyncio.get_event_loop()
            result_future = loop.create_future()
            # If an old future is still hanging around for this pair, drop it.
            old = self._result_futures.get(pair)
            if old and not old.done():
                old.cancel()
            self._result_futures[pair] = result_future

            # Wait until the entry candle opens.
            wait_seconds = (entry_dt - datetime.now(timezone.utc)).total_seconds()
            if wait_seconds > 0:
                logger.info("⏳ Waiting %.1f seconds for entry %s %s", wait_seconds, pair, direction)
                await asyncio.sleep(wait_seconds)

            # Create the trade row in DB (entry_price will be set when we learn it).
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
                self._result_futures.pop(pair, None)
                return

            update_pending_signal(pending_id, "ACTIVE")

            async with self.active_trade_lock:
                self.active_trade = {
                    "id": trade_id,
                    "pair": pair,
                    "direction": direction,
                    "entry_time": entry_time,
                    "expiry_time": expiry_time,
                    "entry_price": None,
                    "signal_score": signal_score,
                }

            # ── Wait for RESULT ────────────────────────────────────────
            # Primary path: TradingView sends action=RESULT at the close of
            # the entry candle (~15 min from entry_dt). We wait until then
            # plus a small grace period for the alert to reach us.
            total_wait = (expiry_dt - datetime.now(timezone.utc)).total_seconds() + TV_RESULT_GRACE_SECONDS
            if total_wait < 0:
                total_wait = TV_RESULT_GRACE_SECONDS

            entry_price = None
            exit_price = None
            source = "unknown"

            try:
                payload = await asyncio.wait_for(result_future, timeout=total_wait)
                entry_price = payload.get("entry_price")
                exit_price = payload.get("exit_price")
                source = payload.get("source", "tradingview")
                logger.info(
                    "✅ Result from TradingView for %s: entry=%s exit=%s",
                    pair, entry_price, exit_price,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "⚠️ TradingView RESULT webhook did not arrive for %s — "
                    "falling back to external candle API",
                    pair,
                )
                # Fallback: query TwelveData / Yahoo for the exact 15m candle.
                candle = None
                try:
                    candle = await self.price_service.get_trade_candle(pair, entry_dt)
                except Exception as e:
                    logger.warning("Fallback candle fetch failed: %s", e)

                if candle:
                    entry_price = candle.get("entry_price")
                    exit_price = candle.get("exit_price")
                    source = candle.get("source", "api")
                else:
                    # Last resort: one spot quote. Result will likely be DRAW.
                    try:
                        exit_price = await self.price_service.get_price(pair)
                        source = "spot-fallback"
                    except Exception as e:
                        logger.warning("Spot fallback failed: %s", e)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("❌ Unexpected error waiting for RESULT: %s", e)
            finally:
                self._result_futures.pop(pair, None)

            # Persist prices.
            if entry_price is not None:
                update_trade(trade_id, entry_price=entry_price)

            result = self._determine_result(direction, entry_price, exit_price)
            logger.info(
                "📊 Trade completed: %s %s result=%s entry=%s exit=%s source=%s",
                pair, direction, result, entry_price, exit_price, source,
            )

            update_trade(
                trade_id,
                exit_price=exit_price,
                status="COMPLETED",
                result=result,
            )
            update_statistics(pair, result)
            update_pending_signal(pending_id, "COMPLETED")

            # ── SEND THE RESULT MESSAGE ────────────────────────────────
            try:
                await self.telegram_sender.send_result(pair, direction, entry_time, result)
                logger.info("📤 Telegram result sent: %s %s -> %s", pair, direction, result)
            except Exception as e:
                logger.exception("❌ Telegram send_result failed: %s", e)

            async with self.active_trade_lock:
                self.active_trade = None

        except asyncio.CancelledError:
            logger.info("Trade monitor cancelled for %s", pair)
            self._result_futures.pop(pair, None)
        except Exception as e:
            logger.exception("❌ Trade monitor error for %s: %s", pair, e)
            self._result_futures.pop(pair, None)
            async with self.active_trade_lock:
                self.active_trade = None

    # ─────────────────────────────────────────────────────────────
    # Recovery after restart (preserved from v6.1)
    # ─────────────────────────────────────────────────────────────
    async def recover_pending_trades(self) -> int:
        """Re-spawn monitor tasks for trades that were ACTIVE before restart.

        Render free-tier cycles the process frequently. Without this,
        any trade that was mid-flight would never get its result message.
        """
        try:
            from database import get_active_trades
        except Exception as e:
            logger.warning("recover: cannot import get_active_trades: %s", e)
            return 0

        try:
            active = get_active_trades() or []
        except Exception as e:
            logger.warning("recover: get_active_trades failed: %s", e)
            return 0

        count = 0
        now_utc = datetime.now(timezone.utc)
        for t in active:
            try:
                entry_time = t.get("entry_time")
                entry_dt = self._parse_entry_time(entry_time)
                if not entry_dt:
                    continue
                expiry_dt = entry_dt + timedelta(minutes=TRADE_DURATION_MINUTES)
                # If already way past expiry + grace, skip (can't recover reliably).
                if (now_utc - expiry_dt).total_seconds() > 3600:
                    continue

                asyncio.create_task(
                    self._monitor_trade(
                        pending_id=0,
                        pair=t.get("pair", ""),
                        direction=t.get("direction", ""),
                        entry_time=entry_time,
                        signal_score=int(t.get("signal_score", 0) or 0),
                    )
                )
                count += 1
            except Exception as e:
                logger.warning("recover: failed to resume trade %s: %s", t.get("id"), e)
        return count

    # ─────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────
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

        min_seconds = SIGNAL_CONFIRM_MIN_SECONDS if SIGNAL_CONFIRM_MIN_SECONDS > 0 else -120
        max_seconds = SIGNAL_CONFIRM_MAX_SECONDS if SIGNAL_CONFIRM_MAX_SECONDS > 0 else 960

        if min_seconds <= diff <= max_seconds:
            normalized = entry_dt.strftime("%Y-%m-%d %H:%M:%S")
            return True, minutes_until, normalized

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
