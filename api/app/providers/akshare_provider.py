"""AKShare（MIT 开源）A 股数据适配。

AKShare 为可选依赖：未安装时 available() 返回 False，系统自动降级。
注意：AKShare 聚合了多个公开来源，商用/再分发请自行核对上游条款。
"""

from __future__ import annotations

from ..cache import get as cache_get
from ..cache import set as cache_set
from ..config import settings
from .base import Bar, Quote
from .synthetic import _NAME_BY_SYMBOL, SYMBOLS


class AkshareProvider:
    id = "akshare"
    name = "AKShare"
    markets = ("cn", "us")

    def __init__(self) -> None:
        self._ak = None
        self._tried = False

    def _lib(self):
        if not self._tried:
            self._tried = True
            try:
                import akshare as ak  # type: ignore

                self._ak = ak
            except Exception:
                self._ak = None
        return self._ak

    def available(self) -> bool:
        return bool(settings.akshare_enabled) and self._lib() is not None

    def bars(self, symbol: str, days: int = 400) -> Bar | None:
        ak = self._lib()
        if ak is None:
            return None
        key = f"ak:bars:{symbol}:{days}"
        hit = cache_get(key)
        if hit:
            return Bar(**hit)
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
        except Exception:
            return None
        if df is None or df.empty:
            return None
        tail = df.tail(days)
        date_col = "日期" if "日期" in tail.columns else tail.columns[0]
        close_col = "收盘" if "收盘" in tail.columns else tail.columns[2]
        dates = [str(d)[:10] for d in tail[date_col].tolist()]
        closes = [round(float(v), 4) for v in tail[close_col].tolist()]
        bar = Bar(dates=dates, closes=closes, source=self.id)
        cache_set(key, {"dates": dates, "closes": closes, "source": self.id}, 900)
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
            currency="CNY",
            source=self.id,
        )

    def search(self, q: str, market: str) -> list[dict] | None:
        ql = (q or "").strip().lower()
        rows = [
            {"symbol": s, "name": n, "exchange": ex, "market": market}
            for s, n, ex in SYMBOLS.get("cn", [])
            if not ql or ql in s.lower() or ql in n.lower()
        ]
        return rows[:12] or None