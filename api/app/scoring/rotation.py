"""风格/市值轮动强度：两条价格序列的相对强弱动量（API_CONTRACT 第 3 节）。

数据来源
--------
两条腿的价格序列都由 app.analytics.series.load_closes 提供，降级链为
Yahoo Finance -> AKShare -> synthetic；真实数据不可用时响应 source 会如实写成
"synthetic"，绝不把合成数据标注成真实行情。
- us/size : ^GSPC 标普500  vs  ^RUT 罗素2000（大盘 vs 小盘）
- us/style: ^IXIC 纳斯达克综指 vs XLP 消费品质（**代理**：免费源无「消费品质」指数，
            用必需消费 ETF XLP 作代理，响应内 bProxy=true 并在 warnings 注明）
- cn/size : 000300 沪深300  vs  932000 中证2000
- cn/style: 399006 创业板指   vs  000922 中证红利

公式（严格实现，不做任何平滑/调参）
----------------------------------
R(t)    = ln(A(t) / B(t))                    A、B 为按交易日对齐后的收盘价
M10(t)  = R(t) - R(t-10)                     10 个交易日相对动量变化
Z(t)    = (M10(t) - mean252(M10)) / std252(M10)   252 日滚动标准化（样本标准差 ddof=1）
score(t)= 100 * tanh(Z(t) / 2)               软饱和到 (-100, 100)：(0,100] A 相对走强，
                                             [-100,0) A 相对走弱，绝对值越大越极端

实现约束
--------
- 两条腿先按交易日做内连接对齐（align），对齐后至少需要 270 个交易日
  （10 日动量 + 252 日标准化窗口），不足则返回空序列 + warnings，不返回假数据。
- Z 的滚动窗口要求 min_periods=252，因此 series 中最早的点是完整窗口可得的第一个交易日。
- 每个点都只使用当日及以前的收盘价，无未来函数；同一 (market, group) 结果缓存
  TTL["daily"] 秒，保证同样输入得到同样输出。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

import numpy as np
import pandas as pd

from ..analytics.common import rnd, utc_now_iso
from ..analytics.series import (
    LOOKBACK_BARS,
    align,
    load_closes,
    merge_source,
    synthetic_warning,
)
from ..cache import TTL, get as cache_get, set as cache_set

__all__ = ["FORMULA", "GROUPS", "MIN_BARS", "Pair", "rotation_payload"]

FORMULA: Final[str] = (
    "R(t)=ln(A/B); M10(t)=R(t)-R(t-10); Z(t)=(M10-μ252)/σ252; score=100*tanh(Z/2)"
)

# 两条腿对齐后所需的最少交易日：10 日动量 + 252 日标准化窗口 + 余量
MIN_BARS: Final[int] = 270
MOM_WINDOW: Final[int] = 10
Z_WINDOW: Final[int] = 252


@dataclass(frozen=True)
class Pair:
    """一条轮动腿的组合定义；proxy=True 表示该腿是公开代理标的而非原生指数。"""

    a: str
    a_name: str
    b: str
    b_name: str
    a_proxy: bool = False
    b_proxy: bool = False


GROUPS: Final[dict[str, dict[str, Pair]]] = {
    "us": {
        "size": Pair("^GSPC", "标普500", "^RUT", "罗素2000"),
        "style": Pair("^IXIC", "纳斯达克综指", "XLP", "消费品质（代理 XLP）", b_proxy=True),
    },
    "cn": {
        "size": Pair("000300", "沪深300", "932000", "中证2000"),
        "style": Pair("399006", "创业板指", "000922", "中证红利"),
    },
}


def rotation_payload(market: str, group: str, days: int = 365) -> dict:
    """返回 /rotation/score 的响应；完整序列按 (market, group) 缓存，按日历天数裁剪后返回。"""
    full = _cached_series(market, group)
    cutoff = (date.today() - timedelta(days=int(days))).isoformat()
    series = [p for p in full["series"] if p["t"] >= cutoff]
    warnings = list(full["warnings"])
    if not series and full["series"]:
        warnings.append(
            f"最近 {days} 天内没有可用数据点（需 10 日动量 + 252 日标准化预热），已返回空序列。"
        )
    return {
        "asOf": utc_now_iso(),
        "dataThrough": full.get("dataThrough"),
        "source": full["source"],
        "market": market,
        "group": group,
        "days": int(days),
        "pair": full["pair"],
        "formula": FORMULA,
        "current": full.get("current"),
        "series": series,
        "warnings": warnings,
    }


def _cached_series(market: str, group: str) -> dict:
    key = f"rotation:v1:{market}:{group}"
    hit = cache_get(key)
    if hit is not None:
        return hit
    value = _compute(market, group)
    cache_set(key, value, TTL["daily"])
    return value


def _empty(market: str, group: str, pair: Pair, source: str, warnings: list[str]) -> dict:
    return {
        "asOf": utc_now_iso(),
        "dataThrough": None,
        "source": source,
        "market": market,
        "group": group,
        "pair": {
            "a": pair.a,
            "b": pair.b,
            "aName": pair.a_name,
            "bName": pair.b_name,
            "aProxy": pair.a_proxy,
            "bProxy": pair.b_proxy,
        },
        "current": None,
        "series": [],
        "warnings": warnings,
    }


def _compute(market: str, group: str) -> dict:
    pair = GROUPS[market][group]
    warnings: list[str] = []
    if pair.a_proxy or pair.b_proxy:
        legs = "、".join(
            name
            for proxy, name in ((pair.a_proxy, pair.a_name), (pair.b_proxy, pair.b_name))
            if proxy
        )
        warnings.append(
            f"免费数据源无「{legs}」对应原生指数，当前使用同名/近义 ETF 作为公开代理标的，"
            "口径与原生指数存在偏差，请勿视作指数本身。"
        )

    close_a, src_a = load_closes(pair.a, market, LOOKBACK_BARS)
    close_b, src_b = load_closes(pair.b, market, LOOKBACK_BARS)
    source = merge_source([src_a, src_b])
    syn = synthetic_warning(source)
    if syn:
        warnings.append(syn)

    frame = align({"a": close_a, "b": close_b})
    n = int(frame.shape[0])
    if n < MIN_BARS:
        warnings.append(
            f"两条腿按交易日对齐后仅 {n} 个共同交易日，少于所需 {MIN_BARS} 个"
            f"（{MOM_WINDOW} 日动量 + {Z_WINDOW} 日标准化窗口），本次返回空序列。"
        )
        return _empty(market, group, pair, source, warnings)

    r = np.log(frame["a"] / frame["b"])
    m10 = r - r.shift(MOM_WINDOW)
    mu = m10.rolling(Z_WINDOW, min_periods=Z_WINDOW).mean()
    sigma = m10.rolling(Z_WINDOW, min_periods=Z_WINDOW).std(ddof=1).replace(0.0, np.nan)
    z = (m10 - mu) / sigma
    score = 100.0 * np.tanh(z / 2.0)

    ok = score.notna()
    if not bool(ok.any()):
        warnings.append("Z 分数仍在预热期（需 252 个有效 M10 观测），本次返回空序列。")
        return _empty(market, group, pair, source, warnings)

    pts: list[dict] = []
    for ts in frame.index[ok.to_numpy()]:
        pts.append(
            {
                "t": str(ts)[:10],
                "r": rnd(float(r.loc[ts]), 4),
                "m10": rnd(float(m10.loc[ts]), 4),
                "z": rnd(float(z.loc[ts]), 2),
                "score": rnd(float(score.loc[ts]), 1),
            }
        )

    last = pts[-1]
    current = {
        **last,
        "mu252": rnd(float(mu.iloc[-1]), 4),
        "sigma252": rnd(float(sigma.iloc[-1]), 4),
        "bias": "A 相对走强" if last["score"] > 0 else ("A 相对走弱" if last["score"] < 0 else "中性"),
    }

    return {
        "asOf": utc_now_iso(),
        "dataThrough": last["t"],
        "source": source,
        "market": market,
        "group": group,
        "pair": {
            "a": pair.a,
            "b": pair.b,
            "aName": pair.a_name,
            "bName": pair.b_name,
            "aProxy": pair.a_proxy,
            "bProxy": pair.b_proxy,
        },
        "current": current,
        "series": pts,
        "warnings": warnings,
    }