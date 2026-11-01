"""通用数值与时间工具。

所有函数都是纯函数（无 I/O、无全局状态），便于单元测试。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timezone

import numpy as np

TRADING_DAYS = 252


def utc_now_iso() -> str:
    """返回 UTC ISO 8601 时间戳，形如 2025-01-03T14:30:00Z。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def clamp(x: float, lo: float, hi: float) -> float:
    """把 x 限制在 [lo, hi] 内。"""
    return lo if x < lo else hi if x > hi else x


def scale(x: float, lo: float, hi: float) -> float:
    """线性映射到 0~100：x<=lo -> 0，x>=hi -> 100（hi<lo 时自动反向）。

    用于把任意尺度的统计量折算成 0~100 的评分刻度。
    """
    if hi == lo:
        return 50.0
    return float(clamp((x - lo) / (hi - lo), 0.0, 1.0) * 100.0)


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    """除法保护：分母为 0 或非有限时返回 default。"""
    if not b or not math.isfinite(b):
        return default
    out = a / b
    return out if math.isfinite(out) else default


def rnd(x: float | None, nd: int = 6) -> float | None:
    """四舍五入并过滤 NaN/Inf（JSON 不允许 NaN，前端会崩）。"""
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(xf):
        return None
    return round(xf, nd)


def log_returns(closes: Sequence[float]) -> np.ndarray:
    """对数收益率 r_t = ln(P_t / P_{t-1})。价格非正时该点记为 0。"""
    p = np.asarray([float(c) for c in closes], dtype=float)
    if p.size < 2:
        return np.zeros(0)
    prev = p[:-1]
    cur = p[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where((prev > 0) & (cur > 0), np.log(cur / np.where(prev > 0, prev, 1.0)), 0.0)
    return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)


def total_return(closes: Sequence[float], lookback: int = TRADING_DAYS) -> float:
    """区间累计收益：close[-1] / close[-1-lookback] - 1（不足则用首根）。"""
    p = [float(c) for c in closes]
    if len(p) < 2:
        return 0.0
    i = max(0, len(p) - 1 - int(lookback))
    base = p[i]
    return safe_div(p[-1] - base, base)


def annualised_vol(closes: Sequence[float], lookback: int = TRADING_DAYS) -> float:
    """年化波动率：std(对数收益) * sqrt(252)，取最近 lookback 个收益。"""
    r = log_returns(closes)
    if r.size < 2:
        return 0.0
    r = r[-int(lookback):]
    return float(np.std(r, ddof=1) * math.sqrt(TRADING_DAYS))


def drawdown_series(nav: Sequence[float]) -> np.ndarray:
    """回撤序列：nav / cummax(nav) - 1（恒 <= 0）。"""
    a = np.asarray([float(x) for x in nav], dtype=float)
    if a.size == 0:
        return a
    peak = np.maximum.accumulate(a)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, a / np.where(peak > 0, peak, 1.0) - 1.0, 0.0)
    return np.nan_to_num(dd, nan=0.0, posinf=0.0, neginf=0.0)


def max_drawdown(nav: Sequence[float]) -> float:
    """最大回撤，返回**负值或 0**（契约里 mdd=-0.21 表示回撤 21%）。"""
    dd = drawdown_series(nav)
    return float(dd.min()) if dd.size else 0.0


def mean_std(x: Sequence[float]) -> tuple[float, float]:
    """均值和样本标准差（样本不足 2 个时标准差记 0）。"""
    a = np.asarray([float(v) for v in x], dtype=float)
    if a.size == 0:
        return 0.0, 0.0
    if a.size == 1:
        return float(a[0]), 0.0
    return float(a.mean()), float(a.std(ddof=1))


def corr(a: Sequence[float], b: Sequence[float]) -> float | None:
    """皮尔逊相关系数；样本不足或方差为 0 时返回 None。"""
    x = np.asarray([float(v) for v in a], dtype=float)
    y = np.asarray([float(v) for v in b], dtype=float)
    n = min(x.size, y.size)
    if n < 10:
        return None
    x, y = x[-n:], y[-n:]
    if x.std() == 0 or y.std() == 0:
        return None
    out = float(np.corrcoef(x, y)[0, 1])
    return out if math.isfinite(out) else None


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Spearman 秩相关系数 = 对秩做皮尔逊相关。

    秩的并列值取平均秩（pandas rank(method="average")），
    与 scipy.stats.spearmanr 的定义一致。
    """
    x = np.asarray([float(v) for v in a], dtype=float)
    y = np.asarray([float(v) for v in b], dtype=float)
    n = min(x.size, y.size)
    if n < 4:
        return None
    x, y = x[:n], y[:n]
    rx, ry = _average_rank(x), _average_rank(y)
    if rx.std() == 0 or ry.std() == 0:
        return None
    out = float(np.corrcoef(rx, ry)[0, 1])
    return out if math.isfinite(out) else None


def _average_rank(v: np.ndarray) -> np.ndarray:
    """平均秩（并列取平均），等价 pandas.Series.rank(method="average")。"""
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(v.size, dtype=float)
    ranks[order] = np.arange(1, v.size + 1, dtype=float)
    sorted_v = v[order]
    i = 0
    while i < v.size:
        j = i
        while j + 1 < v.size and sorted_v[j + 1] == sorted_v[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    return ranks


def downsample(items: Sequence[object], max_points: int = 600) -> list:
    """等距抽样把序列压到 max_points 以内（保留末点），避免响应体过大。"""
    arr = list(items)
    n = len(arr)
    if max_points <= 1 or n <= max_points:
        return arr
    step = n / float(max_points)
    idx = sorted({min(n - 1, int(round(k * step))) for k in range(max_points)} | {n - 1})
    return [arr[i] for i in idx]