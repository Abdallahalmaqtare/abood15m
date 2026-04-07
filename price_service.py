"""
Aboud Trading Bot - Price Service v3.1
FIX: Use REAL-TIME forex APIs, not daily rates.
     Frankfurter gives DAILY rates = WRONG results!
"""
import aiohttp
import logging

logger = logging.getLogger(__name__)


class PriceService:
    def __init__(self):
        self.session = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self.session

    def _parse_pair(self, pair):
        pair = pair.upper().replace("/", "")
        if len(pair) == 6:
            return pair[:3], pair[3:]
        return None, None

    async def get_price(self, pair):
        """Get real-time price. Tries multiple APIs."""
        apis = [
            self._fetch_twelvedata,
            self._fetch_fxratesapi,
            self._fetch_exchangerate_host,
        ]
        for fn in apis:
            try:
                p = await fn(pair)
                if p and p > 0:
                    logger.info(f"Price {pair}: {p}")
                    return p
            except Exception as e:
                logger.warning(f"Price API fail {pair}: {e}")
        logger.error(f"ALL price APIs failed for {pair}")
        return None

    async def _fetch_twelvedata(self, pair):
        """Twelvedata real-time (free: 8 req/min)."""
        b, q = self._parse_pair(pair)
        if not b: return None
        s = await self._get_session()
        async with s.get(f"https://api.twelvedata.com/price?symbol={b}/{q}&apikey=demo") as r:
            if r.status == 200:
                d = await r.json()
                if "price" in d:
                    return float(d["price"])
        return None

    async def _fetch_fxratesapi(self, pair):
        """FXRatesAPI - free real-time forex."""
        b, q = self._parse_pair(pair)
        if not b: return None
        s = await self._get_session()
        async with s.get(f"https://api.fxratesapi.com/latest?base={b}&currencies={q}&resolution=1m") as r:
            if r.status == 200:
                d = await r.json()
                if d.get("success") and q in d.get("rates", {}):
                    return float(d["rates"][q])
        return None

    async def _fetch_exchangerate_host(self, pair):
        """ExchangeRate.host - free forex."""
        b, q = self._parse_pair(pair)
        if not b: return None
        s = await self._get_session()
        async with s.get(f"https://api.exchangerate.host/latest?base={b}&symbols={q}") as r:
            if r.status == 200:
                d = await r.json()
                if d.get("success") and q in d.get("rates", {}):
                    return float(d["rates"][q])
        return None

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


price_service = PriceService()
