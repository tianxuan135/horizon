"""Yahoo Finance 公开图表接口适配（个人研究用途；请遵守其服务条款与频率限制）。

仅访问公开 JSON 接口（query1.finance.yahoo.com），不做页面抓取、不绕过任何访问控制。
"""

from __future__ import annotations

from ..cache import get as cache_get
from ..cache import set as cache_set
from ..config import settings
from .base import Bar, Quote
from .synthetic import _NAME_BY_SYMBOL

BASE = "https://query1.finance.yahoo.com"
UA = "Mozilla/5.0 (compatible; Horizon/0.1; +https://github.com/) research-client"


class YahooProvider:
    id = "yahoo"
    name = "Yahoo Finance"
    markets = ("us", "cn")

    def available(self) -> bool:
        return bool(settings.yahoo_enabled)

    def _client(self):
        import httpx

        return httpx.Client(timeout=8.0, headers={"User-Agent": UA}, follow_redirects=True)

    def bars(self, symbol: str, days: int = 400) -> Bar | None:
        key = f"yahoo:bars:{symbol}:{days}"
        hit = cache_get(key)
        if hit:
            return Bar(**hit)
        rng = "2y" if days <= 500 else "5y"
        url = f"{BASE}/v8/finance/chart/{symbol}"
        with self._client() as c:
            r = c.get(url, params={"range": rng, "interval": "1d", "includePrePost": "false"})
            r.raise_for_status()
            payload = r.json()
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return None
        ts = result[0].get("timestamp") or []
        closes = (((result[0].get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
        from datetime import datetime, timezone

        dates, vals = [], []
        for t, v in zip(ts, closes):
            if v is None:
                continue
            dates.append(datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat())
            vals.append(float(v))
        if len(vals) < 20:
            return None
        bar = Bar(dates=dates[-days:], closes=[round(v, 4) for v in vals[-days:]], source=self.id)
        cache_set(key, {"dates": bar.dates, "closes": bar.closes, "source": bar.source}, 900)
        return bar

    def quote(self, symbol: str) -> Quote | None:
        bar = self.bars(symbol, 30)
        if not bar or len(bar.closes) < 2:
            return None
        return Quote(
            symbol=symbol,
            name=_NAME_BY_SYMBOL.get(symbol, symbol),
            price=bar.closes[-1],
            prev_close=bar.closes[-2],
            currency="USD",
            source=self.id,
        )

    def search(self, q: str, market: str) -> list[dict] | None:
        if not q:
            return None
        url = f"{BASE}/v1/finance/search"
        with self._client() as c:
            r = c.get(url, params={"q": q, "quotesCount": 10, "newsCount": 0})
            r.raise_for_status()
            payload = r.json()
        rows = []
        for it in payload.get("quotes", []):
            sym = it.get("symbol")
            if not sym:
                continue
            rows.append(
                {
                    "symbol": sym,
                    "name": it.get("shortname") or it.get("longname") or sym,
                    "exchange": it.get("exchDisp") or it.get("exchange") or "",
                    "market": market,
                }
            )
        return rows or None