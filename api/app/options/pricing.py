"""期权定价与期权链推演（API_CONTRACT §6 expiries / chain / spot）。

数据来源（provenance）
======================
本项目**没有**可用的期权链数据源（免费公开源普遍受限或需要授权）。
因此：

- ``spot``：来自 ``providers.get_quote`` 的降级链（yahoo → akshare → synthetic），
  响应里如实回传 ``source``；
- ``expiries``：按交易所日历规则**推算**（美股为每月第三个周五，A 股为每月
  第四个周三），响应标注 ``basis="calendar"``；
- ``chain`` 的 bid/ask/iv：由 Black-Scholes 模型 + 标的**已实现波动率**推演，
  波动率微笑用下式的经验曲线刻画（m = ln(K/S)）::

      σ(K) = σ_atm * (1 + 0.55*m^2 - 0.35*m)      # 下跌侧 IV 更高，符合真实偏斜方向

  ``half_spread = max(0.01, 0.015 * mid)``，无风险利率取常数
  ``r_us = 4.5%`` / ``r_cn = 2.0%``（明确的模型假设，不是市场利率）。
  响应 ``source`` 为 ``model:blackscholes-realised-vol``。

**这些数字不是可交易报价**，只用于策略损益推演与交互演示。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta

from ..analytics.common import annualised_vol, clamp, log_returns, rnd, utc_now_iso
from ..providers import get_bars, get_quote

# 无风险利率假设（模型参数，不是行情）
RISK_FREE = {"us": 0.045, "cn": 0.020}

MODEL_SOURCE = "model:blackscholes-realised-vol"

_CN_HOLIDAY_HINT = "A 股期权到期日为每月第四个周三（遇节假日顺延的细节未建模）"


def _norm_cdf(x: float) -> float:
    """标准正态 CDF：0.5 * (1 + erf(x / sqrt(2)))，只用 stdlib。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, years: float, rate: float, sigma: float, kind: str) -> float:
    """Black-Scholes 欧式期权价格（无股息）。

    ``kind`` = ``"call"`` | ``"put"``。到期时间 <=0 时返回内在价值，
    波动率 <=0 或价格非正时同样退回内在价值，保证不产生 NaN。
    """
    k = kind.lower()
    intrinsic = max(spot - strike, 0.0) if k == "call" else max(strike - spot, 0.0)
    if years <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        return intrinsic
    sq = sigma * math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years) / sq
    d2 = d1 - sq
    disc = math.exp(-rate * years)
    if k == "call":
        return spot * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
    return strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def smile_iv(atm_vol: float, spot: float, strike: float) -> float:
    """经验波动率微笑：σ(K) = σ_atm * (1 + 0.55*m² - 0.35*m)，m = ln(K/S)。"""
    if spot <= 0 or strike <= 0:
        return atm_vol
    m = math.log(strike / spot)
    return float(clamp(atm_vol * (1.0 + 0.55 * m * m - 0.35 * m), 0.05, 3.0))


def realised_vol_of(closes: Sequence[float], lookback: int = 60) -> float:
    """标的已实现年化波动率（30~150% 截断，避免模型价格失真）。"""
    r = log_returns([float(c) for c in closes][-lookback:])
    if r.size < 5:
        return 0.30
    return float(clamp(annualised_vol([float(c) for c in closes][-lookback:]), 0.08, 1.5))


def third_friday(year: int, month: int) -> date:
    """某月第三个周五（美股月度期权到期日）。"""
    d = date(year, month, 1)
    offset = (4 - d.weekday()) % 7  # 4 = Friday
    return d + timedelta(days=offset + 14)


def fourth_wednesday(year: int, month: int) -> date:
    """某月第四个周三（A 股 ETF 期权到期日）。"""
    d = date(year, month, 1)
    offset = (2 - d.weekday()) % 7  # 2 = Wednesday
    return d + timedelta(days=offset + 21)


def expiries(market: str = "us", count: int = 8) -> list[str]:
    """按交易所日历规则推算未来 count 个到期日（ISO 字符串，升序）。"""
    today = date.today()
    out: list[str] = []
    y, m = today.year, today.month
    guard = 0
    while len(out) < count and guard < 36:
        guard += 1
        exp = third_friday(y, m) if market != "cn" else fourth_wednesday(y, m)
        if exp > today + timedelta(days=2):
            out.append(exp.isoformat())
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def strike_step(spot: float) -> float:
    """按价格区间给出价内/价外的行权价步长（近似真实链的最小变动价位）。"""
    if spot < 25:
        return 0.5
    if spot < 100:
        return 1.0
    if spot < 250:
        return 2.5
    if spot < 500:
        return 5.0
    return 10.0


def strikes_around(spot: float, steps_each_side: int = 9) -> list[float]:
    """以现价为中心生成等差数列行权价（含现价最近的整步长）。"""
    step = strike_step(spot)
    mid = round(spot / step) * step
    return [round(mid + k * step, 2) for k in range(-steps_each_side, steps_each_side + 1)]


def years_to(expiry: str, today: date | None = None) -> float:
    """到期剩余年化时间（按 365 天折算，最少 1/365）。"""
    t = today or date.today()
    try:
        exp = date.fromisoformat(str(expiry)[:10])
    except ValueError:
        return 30 / 365.0
    return max(1.0, float((exp - t).days)) / 365.0


def quote_spot(symbol: str, market: str = "us") -> dict:
    """取标的现价（走 providers 降级链，永不抛异常）。

    返回 ``{symbol, name, spot, currency, source, asOf}``。
    """
    sym = (symbol or "").strip()
    fallback_name = sym.upper()
    try:
        q = get_quote(sym, market)
        if q and float(q.price) > 0:
            return {
                "symbol": sym.upper(),
                "name": q.name or fallback_name,
                "spot": rnd(float(q.price), 4),
                "prevClose": rnd(float(q.prev_close), 4),
                "currency": q.currency or ("USD" if market == "us" else "CNY"),
                "source": q.source,
                "asOf": utc_now_iso(),
            }
    except Exception:
        pass
    try:
        bar = get_bars(sym, market, 30)
        if bar and bar.closes:
            return {
                "symbol": sym.upper(),
                "name": fallback_name,
                "spot": rnd(float(bar.closes[-1]), 4),
                "prevClose": rnd(float(bar.closes[-2]), 4) if len(bar.closes) > 1 else None,
                "currency": "USD" if market == "us" else "CNY",
                "source": bar.source,
                "asOf": utc_now_iso(),
                "warnings": ["现价取自最新收盘价（报价接口不可用）"],
            }
    except Exception:
        pass
    return {
        "symbol": sym.upper(),
        "name": fallback_name,
        "spot": None,
        "currency": "USD" if market == "us" else "CNY",
        "source": "unavailable",
        "asOf": utc_now_iso(),
        "warnings": ["标的现价不可用（所有数据源均失败）"],
    }


def build_chain(symbol: str, market: str = "us", expiry: str | None = None) -> dict:
    """推演一张期权链（模型价，非真实报价）。

    步骤：取现价 → 取已实现波动率 → 生成行权价 → 对每个行权价用
    Black-Scholes + 经验微笑求 mid，再按 ``half_spread = max(0.01, 0.015*mid)``
    给出 bid/ask。返回体与契约 §6 ``/chain`` 对齐（spot + rows）。
    """
    info = quote_spot(symbol, market)
    spot = info.get("spot")
    if not spot:
        raise ValueError(f"无法获取 {symbol} 的现价，期权链不可用")
    spot = float(spot)
    exps = expiries(market, 8)
    if expiry:
        use_expiry = str(expiry)[:10]
    else:
        use_expiry = exps[0] if exps else (date.today() + timedelta(days=30)).isoformat()

    try:
        bar = get_bars(symbol, market, 260)
        closes = list(bar.closes) if bar and bar.closes else []
        bar_source = bar.source if bar else "unavailable"
    except Exception:
        closes, bar_source = [], "unavailable"
    atm_vol = realised_vol_of(closes) if closes else 0.30

    years = years_to(use_expiry)
    rate = RISK_FREE.get(market, 0.045)
    rows: list[dict] = []
    for k in strikes_around(spot):
        iv = smile_iv(atm_vol, spot, k)
        c = bs_price(spot, k, years, rate, iv, "call")
        pv = bs_price(spot, k, years, rate, iv, "put")
        rows.append(
            {
                "strike": k,
                "callBid": _bid(c),
                "callAsk": _ask(c),
                "putBid": _bid(pv),
                "putAsk": _ask(pv),
                "iv": rnd(iv, 4),
                "callMid": rnd(c, 4),
                "putMid": rnd(pv, 4),
                "inTheMoney": bool(k <= spot),
            }
        )

    return {
        "asOf": utc_now_iso(),
        "symbol": (symbol or "").upper(),
        "market": market,
        "spot": rnd(spot, 4),
        "expiry": use_expiry,
        "rows": rows,
        "expiries": exps,
        "atmVol": rnd(atm_vol, 4),
        "riskFreeRate": rate,
        "model": {
            "pricing": "black-scholes(no dividend)",
            "ivCurve": "sigma_atm*(1+0.55*m^2-0.35*m), m=ln(K/S)",
            "halfSpread": "max(0.01, 0.015*mid)",
        },
        "source": MODEL_SOURCE,
        "quoteSource": info.get("source"),
        "barSource": bar_source,
        "warnings": [
            "本链为**模型推演价**（Black-Scholes + 已实现波动率），不是可交易报价",
            "到期日为按交易所日历规则推算，非官方合约清单",
        ] + (["A 股期权到期规则为第四个周三，节假日顺延未建模"] if market == "cn" else []),
    }


def _bid(mid: float) -> float:
    half = max(0.01, 0.015 * mid)
    return rnd(max(0.01, mid - half), 2) or 0.01


def _ask(mid: float) -> float:
    half = max(0.01, 0.015 * mid)
    return rnd(max(0.02, mid + half), 2) or 0.02