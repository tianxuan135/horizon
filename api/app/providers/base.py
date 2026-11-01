"""Provider 抽象、路由与降级链。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from ..config import settings


@dataclass
class Bar:
    dates: list[str] = field(default_factory=list)   # ISO 日期 YYYY-MM-DD
    closes: list[float] = field(default_factory=list)
    source: str = "synthetic"

    def __len__(self) -> int:
        return len(self.dates)


@dataclass
class Quote:
    symbol: str
    name: str
    price: float
    prev_close: float
    currency: str
    source: str

    @property
    def change(self) -> float:
        if not self.prev_close:
            return 0.0
        return self.price - self.prev_close

    @property
    def change_pct(self) -> float:
        if not self.prev_close:
            return 0.0
        return (self.price - self.prev_close) / self.prev_close


@dataclass
class SourceStatus:
    id: str
    name: str
    kind: str
    ok: bool
    license: str
    note: str = ""
    latency_ms: int = 0


class Provider(Protocol):
    id: str
    name: str
    markets: tuple[str, ...]

    def available(self) -> bool: ...
    def bars(self, symbol: str, days: int = 400) -> Bar | None: ...
    def quote(self, symbol: str) -> Quote | None: ...
    def search(self, q: str, market: str) -> list[dict] | None: ...


_CHECK_CACHE: dict[str, tuple[float, bool]] = {}


def _chain(market: str) -> list[Provider]:
    from . import akshare_provider, synthetic, yahoo

    chain: list[Provider] = []
    if market == "cn":
        if settings.akshare_enabled:
            chain.append(akshare_provider.AkshareProvider())
        if settings.yahoo_enabled:
            chain.append(yahoo.YahooProvider())
    else:
        if settings.yahoo_enabled:
            chain.append(yahoo.YahooProvider())
        if settings.akshare_enabled:
            chain.append(akshare_provider.AkshareProvider())
    chain.append(synthetic.SyntheticProvider())
    return [p for p in chain if market in p.markets]


def get_bars(symbol: str, market: str = "us", days: int = 400) -> Bar:
    """按降级链取日线；永不抛异常（最终 synthetic 兜底）。"""
    for p in _chain(market):
        if not p.available():
            continue
        try:
            bar = p.bars(symbol, days)
            if bar and len(bar) > 20:
                return bar
        except Exception:
            continue
    from . import synthetic

    return synthetic.SyntheticProvider().bars(symbol, days) or Bar()


def get_quote(symbol: str, market: str = "us") -> Quote:
    for p in _chain(market):
        if not p.available():
            continue
        try:
            q = p.quote(symbol)
            if q:
                return q
        except Exception:
            continue
    from . import synthetic

    return synthetic.SyntheticProvider().quote(symbol)  # type: ignore[return-value]


def search_symbols(q: str, market: str = "us") -> list[dict]:
    for p in _chain(market):
        if not p.available():
            continue
        try:
            rows = p.search(q, market)
            if rows:
                return rows
        except Exception:
            continue
    from . import synthetic

    return synthetic.SyntheticProvider().search(q, market) or []


def provider_status() -> list[SourceStatus]:
    """给 /meta/status 用：各数据源可行性与合规信息。"""
    from . import akshare_provider, synthetic, yahoo

    out: list[SourceStatus] = []
    for p, lic in (
        (yahoo.YahooProvider(), "Yahoo 公开接口（非商业/个人研究用途，请遵守其条款）"),
        (akshare_provider.AkshareProvider(), "AKShare 开源库（MIT），二次分发需遵守上游来源条款"),
        (synthetic.SyntheticProvider(), "内置合成代理数据（确定性生成，仅供离线演示，非真实行情）"),
    ):
        t0 = time.perf_counter()
        try:
            ok = p.available()
        except Exception:
            ok = False
        ms = int((time.perf_counter() - t0) * 1000)
        out.append(
            SourceStatus(
                id=p.id,
                name=p.name,
                kind="open-source" if p.id == "akshare" else ("free-public" if p.id == "yahoo" else "synthetic"),
                ok=ok,
                license=lic,
                latency_ms=ms,
                note="" if ok else "未安装或不可达，将自动降级",
            )
        )
    return out