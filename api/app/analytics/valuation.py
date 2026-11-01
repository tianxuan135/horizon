"""估值维度评分引擎（API_CONTRACT §4 估值分析）。

数据来源（provenance，合规重点）
================================
本项目只接入**只提供日线收盘价**的公开数据源（yahoo / akshare / synthetic，
见 ``app/providers``），没有付费基本面数据库。因此本模块严格区分两类输出：

1. ``priceStats`` —— **真实可得**，由收盘价直接计算：

   - ``ret1y``    = close[-1] / close[-1-252] - 1
   - ``vol``      = std(ln(close_t/close_{t-1}), 最近 252 个) * sqrt(252)
   - ``mdd``      = min(close / cummax(close) - 1)，负值
   - ``pb200``    = close[-1] / mean(close[-200:]) - 1
   - ``persist60``= 最近 8 个互不重叠 60 日窗口里收益为正的比例
   - ``corr``     = 与基准指数日对数收益的皮尔逊相关系数（无基准时为 null）

2. ``metrics`` —— **代理估值倍数**（proxy），不是财报披露值。
   没有财报口径的 EPS/BPS/营收，就用下面的显式公式从真实价格统计量推导，
   响应里用 ``metricsBasis="price-derived-proxy"`` 标注，并在 ``warnings``
   声明"非财报口径"。``marketCap`` 需要总股本，价格源拿不到，直接返回 null，
   **绝不编造**。

公式（σ = vol，g = ret1y，0.28 为美股长期中位波动率基准）::

    pe        = clamp(28 - 25*(σ - 0.28) + 12*g,        6,   95)
    pb        = pe * clamp(0.55 + 2.6*σ,                0.6, 2.2)
    ps        = pe * net_margin(bucket)   # consumer .12 / tech .22 / cyclical .08
    fcfYield  = (1/pe) * clamp(1 + 0.5*(g - 0.10),      0.6, 1.4)
    marketCap = None

维度评分（0~100，全部由上面的真实统计量 + 代理倍数驱动）
========================================================
``_v(x, lo, hi)`` 表示把 x 线性映射到 0~100 并截断（见 common.scale）。

基本面 fundamental（越高越"便宜且稳"）::

    value  = _v(pe, pe_hi, pe_lo)                  # 低 PE = 便宜
    steady = _v(-mdd, 0, 0.55)                     # 回撤小 = 稳
    score  = 0.6*value + 0.4*steady

护城河 moat（定价权/持续性代理）::

    趋势持续性 persist60、低波动补偿 lowvol = _v(0.60 - vol, 0, 0.45)、
    趋势领导力   trend  = _v(pb200, -0.15, 0.35)
    score = 0.40*persist60*100 + 0.35*lowvol + 0.25*trend

可替代性 substitutability（**越高越容易被替代**，与护城河反向）::

    corrw   = _v(corr, 0.30, 0.95)     # 越贴指数 = 越同质化
    generic = 100 - moat
    volw    = _v(vol, 0.15, 0.65)
    score   = 0.45*corrw + 0.35*generic + 0.20*volw

资本开支 capex（越高=越资本密集）::

    score = 0.50*_v(vol, 0.15, 0.65) + 0.30*_v(-mdd, 0.08, 0.55) + 0.20*_v(|g|, 0, 0.60)

行业分组 bucket（消费股 consumer / 周期股 cyclical / 科技股 tech）
====================================================================
优先用 ``BUCKET_MAP`` 人工口径（A 股/美股常见标的），未收录的标的一律
``tech`` 并在 warnings 里注明"分组为默认值"，绝不根据股价猜行业。

派生序列 series
===============
``pe`` 序列：假设滚动 EPS 在窗口内不变，则 PE_t = PE_last * close_t/close_last，
因此序列与价格走势同形。这是唯一在"只有价格"时仍可解释的构造方式，
响应 ``seriesBasis`` 字段里同样注明。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from .common import (
    annualised_vol,
    clamp,
    corr,
    log_returns,
    max_drawdown,
    rnd,
    safe_div,
    scale,
    total_return,
    utc_now_iso,
)

BUCKETS = ("consumer", "cyclical", "tech")

BUCKET_NAMES = {"consumer": "消费股", "cyclical": "周期股", "tech": "科技股"}

# 人工行业口径（仅用于分组展示，非投资建议）。未收录标的默认 tech。
BUCKET_MAP: dict[str, str] = {
    # 美股
    "AAPL": "tech", "MSFT": "tech", "NVDA": "tech", "AMD": "tech", "AVGO": "tech",
    "AMZN": "tech", "GOOGL": "tech", "GOOG": "tech", "META": "tech", "NFLX": "tech",
    "TSLA": "cyclical", "XOM": "cyclical", "CVX": "cyclical", "CAT": "cyclical",
    "BA": "cyclical", "DE": "cyclical", "F": "cyclical", "GM": "cyclical",
    "JPM": "cyclical", "GS": "cyclical", "MS": "cyclical", "BAC": "cyclical",
    "KO": "consumer", "PEP": "consumer", "PG": "consumer", "WMT": "consumer",
    "COST": "consumer", "MCD": "consumer", "PFE": "consumer", "JNJ": "consumer",
    "MRK": "consumer", "UNH": "consumer", "LLY": "consumer",
    # A 股
    "600519": "consumer", "000858": "consumer", "600887": "consumer",
    "600276": "consumer", "600036": "cyclical", "601318": "cyclical",
    "000001": "cyclical", "601899": "cyclical", "002594": "cyclical",
    "300750": "cyclical", "601012": "cyclical", "688981": "tech",
    "002415": "tech", "300059": "tech", "002230": "tech",
}

# 分组对应的典型净利率（用于 ps 的代理换算，见模块 docstring 的公式）
_NET_MARGIN = {"consumer": 0.12, "tech": 0.22, "cyclical": 0.08}

# 分组对应的 PE 合理区间 (cheap, expensive)，用于 fundamental 的 value 分项
_BUCKET_PE = {"consumer": (10.0, 45.0), "tech": (15.0, 80.0), "cyclical": (6.0, 30.0)}

_METRICS_WARNING = (
    "metrics 中的 pe/pb/ps/fcfYield 是价格统计量推导的**代理值**"
    "（metricsBasis=price-derived-proxy），并非财报披露口径"
)
_MKTCAP_WARNING = "marketCap 需要总股本数据，当前数据源仅提供价格序列，故为 null（不编造）"


def _v(x: float, lo: float, hi: float) -> float:
    """0~100 线性刻度（同 common.scale，局部别名便于阅读公式）。"""
    return scale(x, lo, hi)


def bucket_of(symbol: str, market: str = "us") -> tuple[str, str]:
    """返回 (bucket, 说明)。未收录标的默认 ``tech`` 并给出说明。"""
    sym = (symbol or "").strip().upper()
    b = BUCKET_MAP.get(sym)
    if b:
        return b, "人工行业口径命中"
    return "tech", "未收录该标的行业口径，默认按科技股处理（展示用途）"


@dataclass
class PriceStats:
    """可由收盘价直接计算的真实统计量。"""

    n: int = 0
    last: float = 0.0
    ret1y: float = 0.0
    vol: float = 0.0
    mdd: float = 0.0          # 负值
    pb200: float = 0.0
    persist60: float = 0.0
    mom6: float = 0.0
    corr_bench: float | None = None


def price_stats(closes: Sequence[float], bench_closes: Sequence[float] | None = None) -> PriceStats:
    """把收盘价序列压成一组真实统计量（公式见模块 docstring）。"""
    p = [float(c) for c in closes if c is not None and float(c) > 0]
    if not p:
        return PriceStats()
    n = len(p)
    last = p[-1]

    ret1y = total_return(p, 252)
    vol = annualised_vol(p, 252)
    mdd = max_drawdown(p)
    ma200 = float(np.mean(p[-200:])) if n >= 5 else last
    pb200 = safe_div(last - ma200, ma200)
    mom6 = total_return(p, 126)

    # 最近 8 个互不重叠 60 日窗口中收益为正的比例（持续性代理）
    windows = 0
    wins = 0
    i = n
    while windows < 8 and i - 60 >= 0:
        seg = p[i - 60:i]
        seg_ret = safe_div(seg[-1] - seg[0], seg[0])
        wins += 1 if seg_ret > 0 else 0
        windows += 1
        i -= 60
    persist60 = safe_div(wins, windows)

    cb = None
    if bench_closes is not None and len(bench_closes) >= 20:
        cb = corr(log_returns(p), log_returns(list(bench_closes)))

    return PriceStats(
        n=n,
        last=last,
        ret1y=ret1y,
        vol=vol,
        mdd=mdd,
        pb200=pb200,
        persist60=persist60,
        mom6=mom6,
        corr_bench=cb,
    )


def implied_multiples(stats: PriceStats, bucket: str) -> dict[str, float | None]:
    """由真实价格统计量推导代理估值倍数（公式见模块 docstring，非财报口径）。"""
    b = bucket if bucket in _NET_MARGIN else "tech"
    sigma = stats.vol
    g = stats.ret1y
    pe = clamp(28.0 - 25.0 * (sigma - 0.28) + 12.0 * g, 6.0, 95.0)
    pb = pe * clamp(0.55 + 2.6 * sigma, 0.6, 2.2)
    ps = pe * _NET_MARGIN[b]
    ey = safe_div(1.0, pe)
    fcf_yield = ey * clamp(1.0 + 0.5 * (g - 0.10), 0.6, 1.4)
    return {
        "pe": rnd(pe, 2),
        "pb": rnd(pb, 2),
        "ps": rnd(ps, 2),
        "fcfYield": rnd(fcf_yield, 4),
        "marketCap": None,
    }


def dimensions(stats: PriceStats, metrics: dict[str, float | None], bucket: str) -> dict[str, int]:
    """四维评分（0~100 整数），公式见模块 docstring。"""
    pe = float(metrics.get("pe") or 0.0)
    lo, hi = _BUCKET_PE.get(bucket, _BUCKET_PE["tech"])
    mdd_mag = abs(stats.mdd)
    vol = stats.vol

    # 基本面：便宜 + 稳
    value = _v(pe, hi, lo)
    steady = _v(-mdd_mag, 0.0, 0.55)
    fundamental = 0.60 * value + 0.40 * steady

    # 护城河：持续性 + 低波动 + 趋势领导力
    lowvol = _v(0.60 - vol, 0.0, 0.45)
    trend = _v(stats.pb200, -0.15, 0.35)
    moat = 0.40 * stats.persist60 * 100.0 + 0.35 * lowvol + 0.25 * trend

    # 可替代性：同质化（贴指数）+ 护城河反向 + 波动
    corrw = _v(stats.corr_bench if stats.corr_bench is not None else 0.55, 0.30, 0.95)
    generic = 100.0 - moat
    volw = _v(vol, 0.15, 0.65)
    substitutability = 0.45 * corrw + 0.35 * generic + 0.20 * volw

    # 资本开支强度：波动 + 回撤 + 增长绝对值
    capex = (
        0.50 * _v(vol, 0.15, 0.65)
        + 0.30 * _v(-mdd_mag, 0.08, 0.55)
        + 0.20 * _v(abs(stats.ret1y), 0.0, 0.60)
    )

    def _i(x: float) -> int:
        return int(round(clamp(x, 0.0, 100.0)))

    return {
        "fundamental": _i(fundamental),
        "moat": _i(moat),
        "substitutability": _i(substitutability),
        "capex": _i(capex),
    }



def score_payload(
    *,
    symbol: str,
    market: str,
    name: str,
    closes: Sequence[float],
    dates: Sequence[str],
    bar_source: str,
    bench_closes: Sequence[float] | None = None,
    bucket: str | None = None,
) -> dict:
    """组装 §4 ``/valuation/score/{symbol}`` 的完整响应体。

    ``bar_source`` 为真实的数据来源标识（yahoo/akshare/synthetic），
    原样透传到响应 ``source``，不做任何美化。
    """
    stats = price_stats(closes, bench_closes)
    b, b_reason = bucket_of(symbol, market)
    if bucket in BUCKETS:
        b, b_reason = bucket, "调用方指定"
    metrics = implied_multiples(stats, b)
    dims = dimensions(stats, metrics, b)

    series_raw = _series_with_dates(closes, dates, float(metrics.get("pe") or 0.0))

    warnings: list[str] = [_METRICS_WARNING, _MKTCAP_WARNING]
    if stats.n < 260:
        warnings.append(f"历史长度仅 {stats.n} 个交易日，1 年波动率/收益按可用样本计算")
    if stats.corr_bench is None:
        warnings.append("基准指数数据不可用，可替代性中的相关系数分项按中性值 0.55 填充")
    if b_reason != "人工行业口径命中" and b_reason != "调用方指定":
        warnings.append(b_reason)
    if bar_source == "synthetic":
        warnings.insert(0, "行情源为内置合成代理数据（synthetic），整页数值仅用于离线演示")

    return {
        "asOf": utc_now_iso(),
        "symbol": (symbol or "").upper(),
        "name": name or (symbol or "").upper(),
        "market": market,
        "bucket": b,
        "bucketName": BUCKET_NAMES.get(b, b),
        "metrics": metrics,
        "metricsBasis": "price-derived-proxy",
        "dimensions": dims,
        "priceStats": {
            "last": rnd(stats.last, 4),
            "ret1y": rnd(stats.ret1y, 4),
            "mom6": rnd(stats.mom6, 4),
            "vol": rnd(stats.vol, 4),
            "mdd": rnd(stats.mdd, 4),
            "distMa200": rnd(stats.pb200, 4),
            "persist60": rnd(stats.persist60, 4),
            "corrBench": rnd(stats.corr_bench, 4),
            "samples": stats.n,
        },
        "series": series_raw,
        "seriesBasis": "pe_t = pe_last * close_t / close_last（假设窗口内滚动 EPS 不变）",
        "source": bar_source,
        "warnings": warnings,
    }


def _series_with_dates(closes: Sequence[float], dates: Sequence[str], pe_last: float) -> list[dict]:
    """生成带真实交易日的月度 PE 序列（`pe_t = pe_last * close_t / close_last`）。

    近似假设：窗口内滚动 EPS 不变，因此 PE 与价格同形；仅用于展示估值相对位置，
    不代表历史真实 PE（没有历史 EPS 数据源）。
    """
    p = [float(c) for c in closes if c is not None and float(c) > 0]
    d = [str(x) for x in dates]
    if len(p) < 2 or not pe_last:
        return []
    n = min(len(p), len(d))
    p, d = p[-n:], d[-n:]
    k = min(12, n)
    idx = [int(round(i * (n - 1) / max(1, k - 1))) for i in range(k)]
    return [{"t": d[i], "pe": rnd(pe_last * p[i] / p[-1], 2)} for i in idx]