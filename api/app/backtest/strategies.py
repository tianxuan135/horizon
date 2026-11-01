"""因子策略与基准指数定义（API_CONTRACT §5）。

策略是"因子组合"的唯一来源：``id`` 用于前端选择，``factors`` 决定引擎
计算哪些因子并做横截面 z-score 合成。所有因子实现见 engine.py。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    factors: tuple[str, ...]
    desc: str


STRATEGIES: tuple[Strategy, ...] = (
    Strategy(
        id="momentum",
        name="动量因子",
        factors=("mom_12_1",),
        desc="12 个月动量（跳过最近 1 个月）：close[t-21]/close[t-252]-1，取横截面最高分位等权持有",
    ),
    Strategy(
        id="reversal",
        name="短期反转",
        factors=("reversal_1m",),
        desc="1 个月反转：-(close[t]/close[t-21]-1)，押注短期超跌反弹（A 股经典反转效应）",
    ),
    Strategy(
        id="value",
        name="低估值因子",
        factors=("value_proxy",),
        desc="盈利收益率代理 1/pe_proxy，pe_proxy 由价格统计量推导（见 analytics/valuation.py）",
    ),
    Strategy(
        id="lowvol",
        name="低波动因子",
        factors=("low_vol",),
        desc="60 日已实现波动率取负：-std(日对数收益)*sqrt(252)，低波动组合",
    ),
    Strategy(
        id="quality",
        name="质量因子",
        factors=("quality",),
        desc="风险调整动量：12 个月收益 / 年化波动，近似类夏普质量分。",
    ),
    Strategy(
        id="multifactor",
        name="多因子合成",
        factors=("mom_12_1", "value_proxy", "low_vol"),
        desc="动量 + 低估值 + 低波动三因子 z-score 等权合成，降低单因子失效风险",
    ),
)

STRATEGY_BY_ID: dict[str, Strategy] = {s.id: s for s in STRATEGIES}

FACTORS: tuple[str, ...] = (
    "mom_12_1",
    "mom_6_1",
    "reversal_1m",
    "value_proxy",
    "low_vol",
    "quality",
)

FACTOR_DESC: dict[str, str] = {
    "mom_12_1": "12-1 月动量：close[t-21]/close[t-252]-1（跳过最近 21 日以规避短期反转）",
    "mom_6_1": "6-1 月动量：close[t-21]/close[t-126]-1",
    "reversal_1m": "1 月反转：-(close[t]/close[t-21]-1)，越大表示越超跌",
    "value_proxy": "盈利收益率代理：1/pe_proxy，pe_proxy 由价格统计量推导（非财报口径）",
    "low_vol": "低波动：-std(60 日日对数收益)*sqrt(252)",
    "quality": "质量（风险调整动量）：12-1 月动量 / 年化波动",
}


@dataclass(frozen=True)
class Benchmark:
    id: str
    symbol: str
    name: str


BENCHMARKS: dict[str, tuple[Benchmark, ...]] = {
    "us": (
        Benchmark("spx", "^GSPC", "标普500"),
        Benchmark("dji", "^DJI", "道琼斯工业平均"),
        Benchmark("ndx", "^IXIC", "纳斯达克综合"),
    ),
    "cn": (
        Benchmark("sse", "000001.SH", "上证指数"),
        Benchmark("csi300", "000300", "沪深300"),
        Benchmark("chinext", "399006", "创业板指"),
    ),
}

DEFAULT_BENCHMARK = {"us": "spx", "cn": "csi300"}


def benchmarks_for(market: str) -> list[dict]:
    """返回该市场的基准列表（契约：直接返回数组）。"""
    return [
        {"id": b.id, "symbol": b.symbol, "name": b.name, "market": market}
        for b in BENCHMARKS.get(market, ())
    ]


def benchmark_of(market: str, bid: str | None) -> Benchmark | None:
    """按 id 查基准，缺省时回落到该市场默认基准。"""
    rows = BENCHMARKS.get(market, ())
    target = bid or DEFAULT_BENCHMARK.get(market)
    for b in rows:
        if b.id == target:
            return b
    for b in rows:
        if b.symbol == target:
            return b
    return rows[0] if rows else None


def strategies_payload() -> list[dict]:
    """契约：``GET /factor/strategies`` 直接返回数组。"""
    return [
        {"id": s.id, "name": s.name, "factors": list(s.factors), "desc": s.desc}
        for s in STRATEGIES
    ]