"""确定性合成数据源（降级兜底 / 离线演示）。

重要合规说明：本模块生成的是**明确标注为 synthetic 的代理数据**，
用于无网络或数据源不可用时保证系统可运行、图表可交互，
绝不在响应中伪装成真实行情（响应 source 字段恒为 "synthetic"）。
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import numpy as np

from .base import Bar, Quote

# 内置标的字典仅用于展示与检索，不构成任何投资建议
SYMBOLS: dict[str, list[tuple[str, str, str]]] = {
    "us": [
        ("AAPL", "Apple Inc.", "NASDAQ"),
        ("MSFT", "Microsoft Corp.", "NASDAQ"),
        ("NVDA", "NVIDIA Corp.", "NASDAQ"),
        ("TSLA", "Tesla Inc.", "NASDAQ"),
        ("AMZN", "Amazon.com Inc.", "NASDAQ"),
        ("GOOGL", "Alphabet Inc.", "NASDAQ"),
        ("META", "Meta Platforms Inc.", "NASDAQ"),
        ("AMD", "Advanced Micro Devices", "NASDAQ"),
        ("AVGO", "Broadcom Inc.", "NASDAQ"),
        ("XOM", "Exxon Mobil Corp.", "NYSE"),
        ("JPM", "JPMorgan Chase & Co.", "NYSE"),
        ("KO", "Coca-Cola Co.", "NYSE"),
        ("PFE", "Pfizer Inc.", "NYSE"),
        ("CAT", "Caterpillar Inc.", "NYSE"),
        ("^GSPC", "S&P 500", "INDEX"),
        ("^RUT", "Russell 2000", "INDEX"),
        ("^IXIC", "Nasdaq Composite", "INDEX"),
        ("^DJI", "Dow Jones Industrial Average", "INDEX"),
        ("^VIX", "CBOE Volatility Index", "INDEX"),
    ],
    "cn": [
        ("600519", "贵州茅台", "SH"),
        ("000858", "五粮液", "SZ"),
        ("300750", "宁德时代", "SZ"),
        ("002594", "比亚迪", "SZ"),
        ("601318", "中国平安", "SH"),
        ("600036", "招商银行", "SH"),
        ("000001", "平安银行", "SZ"),
        ("601899", "紫金矿业", "SH"),
        ("600276", "恒瑞医药", "SH"),
        ("688981", "中芯国际", "SH"),
        ("000300", "沪深300", "INDEX"),
        ("399006", "创业板指", "INDEX"),
        ("000001.SH", "上证指数", "INDEX"),
        ("932000", "中证2000", "INDEX"),
        ("000922", "中证红利", "INDEX"),
    ],
}

_NAME_BY_SYMBOL = {s: n for rows in SYMBOLS.values() for s, n, _ in rows}


def seed_of(symbol: str, salt: str = "") -> int:
    digest = hashlib.sha256(f"{symbol}:{salt}".encode()).hexdigest()
    return int(digest[:16], 16)


def price_of(symbol: str) -> float:
    rng = np.random.default_rng(seed_of(symbol, "price"))
    base = float(rng.uniform(18, 460))
    if symbol.startswith("^") or symbol in {"000300", "399006", "000001.SH", "932000", "000922"}:
        base = float(rng.uniform(1200, 4200)) if symbol != "^VIX" else float(rng.uniform(11, 32))
    return round(base, 2)


class SyntheticProvider:
    id = "synthetic"
    name = "Synthetic (offline proxy)"
    markets = ("us", "cn")

    def available(self) -> bool:
        return True

    def bars(self, symbol: str, days: int = 400) -> Bar:
        days = max(30, int(days))
        rng = np.random.default_rng(seed_of(symbol, "bars"))
        n = days
        # 几何布朗运动 + 轻微均值回复，保证曲线形态自然且可复现
        vol = 0.014 if not symbol.startswith("^") else 0.008
        drift = 0.0004
        shocks = rng.normal(drift, vol, n)
        prices = price_of(symbol) * np.exp(np.cumsum(shocks - 0.0002))
        start = date.today() - timedelta(days=int(n * 1.45))
        d = start
        dates: list[str] = []
        while len(dates) < n:
            if d.weekday() < 5:
                dates.append(d.isoformat())
            d += timedelta(days=1)
        return Bar(dates=dates, closes=[round(float(p), 4) for p in prices], source=self.id)

    def quote(self, symbol: str) -> Quote:
        bar = self.bars(symbol, 30)
        price = bar.closes[-1]
        return Quote(
            symbol=symbol,
            name=_NAME_BY_SYMBOL.get(symbol, symbol),
            price=price,
            prev_close=bar.closes[-2] if len(bar.closes) > 1 else price,
            currency="USD" if not symbol.endswith((".SH", ".SZ")) and not symbol.isdigit() else "CNY",
            source=self.id,
        )

    def search(self, q: str, market: str) -> list[dict]:
        ql = (q or "").strip().lower()
        rows = SYMBOLS.get(market, [])
        hits = [
            {"symbol": s, "name": n, "exchange": ex, "market": market}
            for s, n, ex in rows
            if not ql or ql in s.lower() or ql in n.lower()
        ]
        return hits[:12]