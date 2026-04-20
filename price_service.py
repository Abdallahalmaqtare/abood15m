"""
Aboud Trading Bot - Price Service v4.0 (TradingView Integration)
===============================================================
Reliable price fetching directly from TradingView.

Features:
- Primary source: TradingView (via tradingview-ta)
- Fallback sources: TwelveData, Yahoo Finance
- Real-time price fetching for entry and exit
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timezone
from tradingview_ta import TA_Handler, Interval

from config import RESULT_CANDLE_LOOKBACK_DAYS

logger = logging.getLogger(__name__)


class PriceService:
    """Service to fetch forex prices from TradingView and other APIs."""

    def __init__(self):
        self.session = None
        self.default_headers = {
            "User-Agent": "Mozilla/5.0 (AboudTradingBot/4.0)",
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

    async def get_price(self, pair):
        """Fetch current price from TradingView, with fallbacks."""
        # 1. Try TradingView (Primary)
        try:
            price = await self._fetch_price_from_tradingview(pair)
            if price and price > 0:
                logger.info("Price for %s from TradingView: %s", pair, price)
                return price
        except Exception as e:
            logger.warning("TradingView fetch failed for %s: %s", pair, e)

        # 2. Fallback to TwelveData
        try:
            price = await self._fetch_spot_from_twelvedata(pair)
            if price and price > 0:
                logger.info("Price for %s from TwelveData: %s", pair, price)
                return price
        except Exception as e:
            logger.warning("TwelveData fetch failed for %s: %s", pair, e)

        # 3. Fallback to Yahoo Finance
        try:
            price = await self._fetch_spot_from_yahoo(pair)
            if price and price > 0:
                logger.info("Price for %s from Yahoo: %s", pair, price)
                return price
        except Exception as e:
            logger.warning("Yahoo fetch failed for %s: %s", pair, e)

        logger.error("All price sources failed for %s", pair)
        return None

    async def _fetch_price_from_tradingview(self, pair):
        """Fetch live price from TradingView using tradingview-ta."""
        # TradingView uses symbols like 'EURUSD' and exchange 'FX_IDC' or 'OANDA' for Forex
        pair = pair.upper().replace("/", "")
        
        # Run in executor because tradingview-ta is synchronous
        def get_tv_data():
            handler = TA_Handler(
                symbol=pair,
                screener="forex",
                exchange="FX_IDC",
                interval=Interval.INTERVAL_1_MINUTE
            )
            analysis = handler.get_analysis()
            return analysis.indicators.get("open") or analysis.indicators.get("close")

        loop = asyncio.get_event_loop()
        price = await loop.run_in_executor(None, get_tv_data)
        return self._safe_float(price)

    async def get_trade_candle(self, pair, entry_time):
        """
        Legacy support for candle-based verification.
        Now simply returns current prices since we moved to real-time precision.
        """
        price = await self.get_price(pair)
        if price:
            return {
                "entry_price": price,
                "exit_price": price,
                "source": "tradingview",
                "candle_start": entry_time.isoformat(),
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
