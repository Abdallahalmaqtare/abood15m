"""
Aboud Trading Bot - Price Service
====================================
Fetches real-time forex prices for trade result verification.
Uses multiple free APIs as fallback.
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class PriceService:
    """Service to fetch forex prices from free APIs."""

    def __init__(self):
        self.session = None
        # Multiple free API sources for reliability
        self.apis = [
            self._fetch_from_twelvedata,
            self._fetch_from_frankfurter,
        ]

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self.session

    def _parse_pair(self, pair):
        """Parse pair like EURUSD into base=EUR, quote=USD."""
        pair = pair.upper().replace("/", "")
        if len(pair) == 6:
            return pair[:3], pair[3:]
        return None, None

    async def get_price(self, pair):
        """
        Get current price for a forex pair.
        Tries multiple APIs until one succeeds.

        Returns: float price or None
        """
        for api_func in self.apis:
            try:
                price = await api_func(pair)
                if price and price > 0:
                    logger.info(f"Got price for {pair}: {price}")
                    return price
            except Exception as e:
                logger.warning(f"API failed for {pair}: {e}")
                continue

        logger.error(f"All price APIs failed for {pair}")
        return None

    async def _fetch_from_twelvedata(self, pair):
        """Fetch from Twelve Data free tier."""
        base, quote = self._parse_pair(pair)
        if not base or not quote:
            return None

        session = await self._get_session()
        url = f"https://api.twelvedata.com/price?symbol={base}/{quote}&apikey=demo"

        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                if "price" in data:
                    return float(data["price"])
        return None

    async def _fetch_from_frankfurter(self, pair):
        """Fetch from Frankfurter API (free, no key needed)."""
        base, quote = self._parse_pair(pair)
        if not base or not quote:
            return None

        session = await self._get_session()
        url = f"https://api.frankfurter.dev/v1/latest?base={base}&symbols={quote}"

        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                rates = data.get("rates", {})
                if quote in rates:
                    return float(rates[quote])
        return None

    async def close(self):
        """Close the HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()


# Global instance
price_service = PriceService()
