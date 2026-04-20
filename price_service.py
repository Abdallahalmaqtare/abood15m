"""
Aboud Trading Bot - Price Service v3.2
=====================================
Reliable candle-based result verification.

Primary use-case:
- Verify 15-minute trade result using the OPEN and CLOSE of the exact
  15-minute candle for the trade, instead of comparing two delayed spot quotes.

Sources:
- TwelveData intraday 15m candles (primary)
- Yahoo Finance intraday 15m candles (fallback / consistency check)
- Spot quote APIs kept only as last-resort fallback
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timezone

from config import RESULT_CANDLE_LOOKBACK_DAYS

logger = logging.getLogger(__name__)


class PriceService:
    """Service to fetch forex candle/price data from free APIs."""

    def __init__(self):
        self.session = None
        self.default_headers = {
            "User-Agent": "Mozilla/5.0 (AboudTradingBot/3.2)",
            "Accept": "application/json,text/plain,*/*",
        }

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers=self.default_headers,
            )
        return self.session

    def _parse_pair(self, pair):
        pair = pair.upper().replace("/", "")
        if len(pair) == 6:
            return pair[:3], pair[3:]
        return None, None

    def _to_yahoo_symbol(self, pair):
        pair = pair.upper().replace("/", "")
        return f"{pair}=X"

    def _to_twelvedata_symbol(self, pair):
        base, quote = self._parse_pair(pair)
        if not base or not quote:
            return None
        return f"{base}/{quote}"

    def _safe_float(self, value):
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _pip_size(self, pair):
        pair = pair.upper().replace("/", "")
        return 0.01 if pair.endswith("JPY") else 0.0001

    def _normalize_candle_start(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)

    def _candle_direction(self, entry_price, exit_price, pair):
        if entry_price is None or exit_price is None:
            return "UNKNOWN"
        delta = exit_price - entry_price
        neutral_threshold = self._pip_size(pair) * 0.05
        if abs(delta) <= neutral_threshold:
            return "FLAT"
        return "UP" if delta > 0 else "DOWN"

    async def get_price(self, pair):
        """Legacy current-spot fetch, used only as last fallback."""
        fetchers = [self._fetch_spot_from_twelvedata, self._fetch_spot_from_yahoo]
        for fetcher in fetchers:
            try:
                price = await fetcher(pair)
                if price and price > 0:
                    logger.info("Spot price for %s from %s: %s", pair, fetcher.__name__, price)
                    return price
            except Exception as exc:
                logger.warning("Spot fetch failed for %s via %s: %s", pair, fetcher.__name__, exc)
        logger.error("All spot price sources failed for %s", pair)
        return None

    async def get_candle_open(self, pair, candle_start):
        """Fetch open price of the exact 15m candle starting at candle_start."""
        candle = await self.get_trade_candle(pair, candle_start)
        if candle:
            return candle["entry_price"]
        return None

    async def get_trade_candle(self, pair, entry_time):
        """
        Return the exact 15m candle used for binary-result verification.

        Output:
        {
          "entry_price": float,
          "exit_price": float,
          "source": "twelvedata" | "yahoo",
          "candle_start": "ISO datetime",
          "consensus": "matched" | "single-source" | "conflict-preferred-twelvedata"
        }
        """
        entry_time = self._normalize_candle_start(entry_time)

        results = await asyncio.gather(
            self._fetch_trade_candle_from_twelvedata(pair, entry_time),
            self._fetch_trade_candle_from_yahoo(pair, entry_time),
            return_exceptions=True,
        )

        valid = []
        for result in results:
            if isinstance(result, dict):
                valid.append(result)
            elif isinstance(result, Exception):
                logger.warning("Candle fetch exception for %s: %s", pair, result)

        if not valid:
            logger.error("No candle source returned usable 15m data for %s at %s", pair, entry_time.isoformat())
            return None

        preferred = None
        twelvedata = next((x for x in valid if x["source"] == "twelvedata"), None)
        yahoo = next((x for x in valid if x["source"] == "yahoo"), None)

        if twelvedata and yahoo:
            td_dir = self._candle_direction(twelvedata["entry_price"], twelvedata["exit_price"], pair)
            yh_dir = self._candle_direction(yahoo["entry_price"], yahoo["exit_price"], pair)
            if td_dir == yh_dir:
                preferred = dict(twelvedata)
                preferred["consensus"] = "matched"
                logger.info(
                    "Candle consensus matched for %s at %s (%s)",
                    pair,
                    entry_time.isoformat(),
                    td_dir,
                )
            else:
                preferred = dict(twelvedata)
                preferred["consensus"] = "conflict-preferred-twelvedata"
                logger.warning(
                    "Candle source conflict for %s at %s | TwelveData=%s (%s -> %s) | Yahoo=%s (%s -> %s). Preferring TwelveData.",
                    pair,
                    entry_time.isoformat(),
                    td_dir,
                    twelvedata["entry_price"],
                    twelvedata["exit_price"],
                    yh_dir,
                    yahoo["entry_price"],
                    yahoo["exit_price"],
                )
            return preferred

        preferred = dict(valid[0])
        preferred["consensus"] = "single-source"
        return preferred

    async def _fetch_trade_candle_from_twelvedata(self, pair, entry_time):
        symbol = self._to_twelvedata_symbol(pair)
        if not symbol:
            return None

        session = await self._get_session()
        url = (
            "https://api.twelvedata.com/time_series"
            f"?symbol={symbol}&interval=15min&outputsize=64&timezone=UTC&apikey=demo"
        )

        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

        values = data.get("values") or []
        target = entry_time.strftime("%Y-%m-%d %H:%M:%S")
        for candle in values:
            if candle.get("datetime") == target:
                entry_price = self._safe_float(candle.get("open"))
                exit_price = self._safe_float(candle.get("close"))
                if entry_price is None or exit_price is None:
                    return None
                return {
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "source": "twelvedata",
                    "candle_start": entry_time.isoformat(),
                }
        return None

    async def _fetch_trade_candle_from_yahoo(self, pair, entry_time):
        symbol = self._to_yahoo_symbol(pair)
        session = await self._get_session()
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            f"?interval=15m&range={RESULT_CANDLE_LOOKBACK_DAYS}d&includePrePost=false"
        )

        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

        chart = (data.get("chart") or {}).get("result") or []
        if not chart:
            return None

        result = chart[0]
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        closes = quote.get("close") or []

        target_ts = int(entry_time.timestamp())
        for idx, ts in enumerate(timestamps):
            if abs(int(ts) - target_ts) <= 60:
                entry_price = self._safe_float(opens[idx] if idx < len(opens) else None)
                exit_price = self._safe_float(closes[idx] if idx < len(closes) else None)
                # Ignore the odd live candle sometimes returned with non-quarter timestamps.
                if int(ts) % 900 != 0:
                    continue
                if entry_price is None or exit_price is None:
                    continue
                return {
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "source": "yahoo",
                    "candle_start": datetime.fromtimestamp(int(ts), timezone.utc).isoformat(),
                }
        return None

    async def _fetch_spot_from_twelvedata(self, pair):
        symbol = self._to_twelvedata_symbol(pair)
        if not symbol:
            return None
        session = await self._get_session()
        url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey=demo"
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        return self._safe_float(data.get("price"))

    async def _fetch_spot_from_yahoo(self, pair):
        symbol = self._to_yahoo_symbol(pair)
        session = await self._get_session()
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d&includePrePost=false"
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

        chart = (data.get("chart") or {}).get("result") or []
        if not chart:
            return None

        quote = ((chart[0].get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        for value in reversed(closes):
            price = self._safe_float(value)
            if price is not None and price > 0:
                return price
        return None

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


price_service = PriceService()
