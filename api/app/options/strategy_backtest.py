"""期权策略月度滚动回测（API_CONTRACT §6 POST /options/backtest）。

数据来源与口径
==============
* **标的行情**：``providers.get_bars`` 的真实日线（yahoo → akshare → 合成，
  ``source`` 字段如实回显用的是哪条链路）。
* **期权价格**：本地**无法**取到历史期权报价（无期权数据源，且不得新增依赖），
  因此每期开仓时用 Black-Scholes + 标的 60 日已实现波动率 + 偏斜微笑
  （见 ``app/options/pricing.py``）**模型定价**。这一点在响应的
  ``optionPricing`` 字段里显式标注为 ``model:blackscholes-realised-vol``，
  绝不伪装成真实历史权利金。
* **滚动节奏**：每月最后一个交易日开仓，持有到下一个开仓日（≈1 个月）到期结算，
  结算价 = 标的当日收盘价（欧式、现金交割近似）。
* **收益口径**：每期损益（金额，1 张合约）除以开仓时名义 ``spot*100``，
  逐期复利得到 ``nav``。基准 = 期间**买入并持有同一标的**的净值。

合规：仅做策略损益推演与研究，不接任何券商、无下单能力。
"""

from __future__ import annotations

import numpy as np

from ..backtest.engine import _month_end_indices
from ..analytics.common import utc_now_iso
from ..backtest.metrics import performance_metrics
from ..providers.base import get_bars
from .pricing import RISK_FREE, bs_price, realised_vol_of, smile_iv, strike_step
from .payoff import MULTIPLIER, Leg, pnl_total

OPTION_BACKTEST_SOURCE = "model:blackscholes-realised-vol"

# 支持的策略 -> 需要正股?
OPTION_STRATEGIES: dict[str, str] = {
    "long_call": "买入 1 张平值看涨：押注上行，成本为权利金，亏损封顶、盈利理论无限",
    "long_put": "买入 1 张平值看跌：押注下行，亏损封顶于权利金",
    "covered_call": "持有 100 股 + 卖出 1 张虚值看涨：以封顶上行换取权利金收入",
    "protective_put": "持有 100 股 + 买入 1 张虚值看跌：为持仓买保险，付出权利金",
    "straddle": "同价买入看涨+看跌：押注大幅波动，成本为两份权利金",
    "strangle": "买入虚值看跌+虚值看涨：更便宜的波动率多头",
    "collar": "持股 + 买虚值看跌 + 卖虚值看涨：把损益压缩进区间，常近似零成本",
}

_NEEDS_STOCK = {"covered_call", "protective_put", "collar"}


def _legs_for(sid: str, spot: float, sigma: float, rate: float, years: float) -> list[Leg]:
    """按当期现价/波动率构造一组期权腿（行权价取整到标准档位）。"""
    step = strike_step(spot)

    def k(mult: float) -> float:
        return round(spot * mult / step) * step

    def px(strike: float, kind: str) -> float:
        iv = smile_iv(sigma, spot, strike)
        return bs_price(spot, strike, years, rate, iv, kind)

    if sid == "long_call":
        kk = k(1.0)
        return [Leg("call", "long", kk, px(kk, "call"), 1)]
    if sid == "long_put":
        kk = k(1.0)
        return [Leg("put", "long", kk, px(kk, "put"), 1)]
    if sid == "covered_call":
        kk = k(1.05)
        return [
            Leg("stock", "long", 0.0, 0.0, MULTIPLIER, basis=spot),
            Leg("call", "short", kk, px(kk, "call"), 1),
        ]
    if sid == "protective_put":
        kk = k(0.95)
        return [
            Leg("stock", "long", 0.0, 0.0, MULTIPLIER, basis=spot),
            Leg("put", "long", kk, px(kk, "put"), 1),
        ]
    if sid == "straddle":
        kk = k(1.0)
        return [Leg("call", "long", kk, px(kk, "call"), 1), Leg("put", "long", kk, px(kk, "put"), 1)]
    if sid == "strangle":
        kc, kp = k(1.05), k(0.95)
        return [Leg("call", "long", kc, px(kc, "call"), 1), Leg("put", "long", kp, px(kp, "put"), 1)]
    if sid == "collar":
        kc, kp = k(1.08), k(0.92)
        return [
            Leg("stock", "long", 0.0, 0.0, MULTIPLIER, basis=spot),
            Leg("put", "long", kp, px(kp, "put"), 1),
            Leg("call", "short", kc, px(kc, "call"), 1),
        ]
    raise ValueError(
        f"未知期权策略 strategyId={sid}，可选：{', '.join(OPTION_STRATEGIES)}"
    )


def run_option_backtest(
    *,
    symbol: str,
    market: str = "us",
    strategy_id: str = "covered_call",
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """月度滚动回测主入口，返回与 ``/factor/backtest`` 同形的结构。"""
    sid = (strategy_id or "").strip().lower()
    if sid not in OPTION_STRATEGIES:
        raise ValueError(
            f"未知期权策略 strategyId={strategy_id}，可选：{', '.join(OPTION_STRATEGIES)}"
        )
    bar = get_bars(symbol, market, days=1600)
    dates = list(bar.dates)
    closes = np.asarray(bar.closes, dtype=float)
    if len(dates) < 400:
        raise ValueError(f"{symbol} 历史数据不足（{len(dates)} 个交易日），无法做月度滚动回测")

    if start:
        keep = [i for i, d in enumerate(dates) if d >= start]
        lo = keep[0] if keep else 0
    else:
        lo = 260
    hi = len(dates) - 1
    if end:
        keep = [i for i, d in enumerate(dates) if d <= end]
        if keep:
            hi = keep[-1]
    lo = max(lo, 260)
    if hi - lo < 60:
        raise ValueError("回测区间过短（<60 个交易日），请放宽 start/end")

    rebal = _month_end_indices(dates, lo, hi)
    if len(rebal) < 3:
        raise ValueError("可用的月度开仓点不足 3 个")
    if rebal[-1] >= hi:
        rebal = rebal[:-1]

    rate = RISK_FREE.get(market, 0.03)
    nav, bench_nav = 1.0, 1.0
    equity: list[dict] = []
    trades: list[dict] = []
    period_rets: list[float] = []
    bench_rets: list[float] = []

    for a, b in zip(rebal, rebal[1:]):
        spot = float(closes[a])
        sigma = realised_vol_of(closes[: a + 1], lookback=60)
        years = max((b - a), 1) / 252.0
        legs = _legs_for(sid, spot, sigma, rate, years)
        settle = float(closes[b])
        pnl = float(pnl_total(legs, np.asarray([settle]), spot)[0])
        notional = spot * MULTIPLIER
        r = pnl / notional
        r = max(-1.0, r)
        nav *= 1.0 + r
        bench_nav *= settle / spot
        period_rets.append(r)
        bench_rets.append(settle / spot - 1.0)
        equity.append(
            {
                "t": dates[b],
                "nav": round(nav, 6),
                "bench": round(bench_nav, 6),
                "periodReturn": round(r, 6),
                "premiumAtOpen": round(float(-sum(l.sign * l.qty * MULTIPLIER * l.premium for l in legs if l.type != "stock")), 2),
                "spotOpen": round(spot, 4),
                "spotClose": round(settle, 4),
            }
        )
        trades.append(
            {
                "open": dates[a],
                "close": dates[b],
                "spotOpen": round(spot, 4),
                "spotClose": round(settle, 4),
                "sigma": round(sigma, 4),
                "pnl": round(pnl, 2),
                "return": round(r, 6),
                "legs": [l.as_dict() for l in legs],
            }
        )

    metrics = performance_metrics(
        nav=[1.0] + [e["nav"] for e in equity],
        bench_nav=[1.0] + [e["bench"] for e in equity],
        strat_ret=period_rets,
        bench_ret=bench_rets,
        period_returns=None,
    )
    metrics["optionPeriods"] = len(period_rets)
    metrics["avgPremiumAtOpen"] = round(float(np.mean([t["premiumAtOpen"] for t in equity])), 2)
    metrics["positivePeriodRatio"] = round(
        float(sum(1 for r in period_rets if r > 0) / max(1, len(period_rets))), 4
    )

    return {
        "asOf": utc_now_iso(),
        "market": market,
        "symbol": symbol,
        "strategyId": sid,
        "strategyName": sid,
        "strategyDesc": OPTION_STRATEGIES[sid],
        "requiresStock": sid in _NEEDS_STOCK,
        "equity": equity,
        "metrics": metrics,
        "benchmark": {"id": "buyhold", "symbol": symbol, "name": f"{symbol} 买入持有"},
        "trades": trades,
        "start": dates[rebal[0]],
        "end": dates[rebal[-1]],
        "optionPricing": OPTION_BACKTEST_SOURCE,
        "source": bar.source,
        "warnings": [
            "期权权利金由 Black-Scholes + 历史已实现波动率模型定价，非真实历史期权报价",
            "结算按到期日标的收盘价现金交割近似，未计滑点、税费与提前平仓",
            "研究用途推演，不构成投资建议，不提供下单能力",
        ],
    }