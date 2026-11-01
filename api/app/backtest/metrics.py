"""回测指标（API_CONTRACT §5 的 metrics 字段）。

口径（全部按日频净值计算，rf = 0）::

    cagr    = (nav[-1]/nav[0]) ** (252/交易日数) - 1
    mdd     = min(nav / cummax(nav) - 1)                     # 负值
    vol     = std(日收益, ddof=1) * sqrt(252)                # 年化波动
    sharpe  = mean(日收益) / std(日收益) * sqrt(252)
    beta    = cov(策略日收益, 基准日收益) / var(基准日收益)
    alpha   = (mean(策略日收益) - beta * mean(基准日收益)) * 252   # 年化 Jensen alpha
    winRate = 各调仓周期中"策略跑赢基准"的比例
    winRateDaily = 日收益为正的比例
    calmar  = cagr / |mdd|

``sortino`` 用下行波动（std of negative returns）替代总波动。
所有输出都经过 rnd() 过滤 NaN/Inf，保证 JSON 合法。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from ..analytics.common import max_drawdown, rnd, safe_div

TRADING_DAYS = 252


def _to_arr(x: Sequence[float]) -> np.ndarray:
    return np.asarray([float(v) for v in x], dtype=float)


def performance_metrics(
    *,
    nav: Sequence[float],
    bench_nav: Sequence[float],
    strat_ret: Sequence[float],
    bench_ret: Sequence[float],
    period_returns: Sequence[tuple[float, float]] | None = None,
) -> dict[str, float | None]:
    """计算契约要求的 7 个指标 + 少量补充指标。

    ``period_returns`` 是 [(策略区间收益, 基准区间收益), ...]，用于 winRate；
    不传时退回"日收益为正比例"。
    """
    n = _to_arr(nav)
    b = _to_arr(bench_nav)
    rs = _to_arr(strat_ret)
    rb = _to_arr(bench_ret)

    out: dict[str, float | None] = {
        "cagr": None,
        "mdd": None,
        "sharpe": None,
        "vol": None,
        "alpha": None,
        "beta": None,
        "winRate": None,
        "winRateDaily": None,
        "calmar": None,
        "sortino": None,
        "days": int(max(rs.size, n.size)),
    }
    if n.size < 2 or n[0] <= 0:
        return out

    span = n.size - 1
    if span > 0 and n[-1] > 0:
        out["cagr"] = rnd((n[-1] / n[0]) ** (TRADING_DAYS / span) - 1.0, 4)

    mdd = max_drawdown(n)
    out["mdd"] = rnd(mdd, 4)
    out["calmar"] = rnd(safe_div((out["cagr"] or 0.0), abs(mdd)), 4) if mdd else None

    if rs.size >= 2:
        sd = float(np.std(rs, ddof=1))
        mu = float(np.mean(rs))
        out["vol"] = rnd(sd * math.sqrt(TRADING_DAYS), 4)
        out["sharpe"] = rnd(safe_div(mu, sd) * math.sqrt(TRADING_DAYS) if sd else 0.0, 4)
        down = rs[rs < 0]
        dsd = float(np.std(down, ddof=1)) if down.size >= 2 else 0.0
        out["sortino"] = rnd(safe_div(mu, dsd) * math.sqrt(TRADING_DAYS) if dsd else 0.0, 4)
        out["winRateDaily"] = rnd(float(np.mean(rs > 0)), 4)

    if rs.size >= 2 and rb.size >= 2:
        k = min(rs.size, rb.size)
        xs, xb = rs[-k:], rb[-k:]
        var_b = float(np.var(xb, ddof=1))
        if var_b > 0:
            cov = float(np.cov(xs, xb, ddof=1)[0, 1])
            beta = cov / var_b
            out["beta"] = rnd(beta, 4)
            out["alpha"] = rnd((float(np.mean(xs)) - beta * float(np.mean(xb))) * TRADING_DAYS, 4)

    if period_returns:
        wins = 0
        total = 0
        for sr, br in period_returns:
            total += 1
            wins += 1 if sr > br else 0
        out["winRate"] = rnd(safe_div(wins, total), 4)
    elif rs.size:
        out["winRate"] = out["winRateDaily"]

    # bench 也做一次可用性标注（bench 全 0 时 beta/alpha 无意义）
    if b.size >= 2 and float(np.var(b, ddof=1)) == 0:
        out["beta"] = None
        out["alpha"] = None

    return out