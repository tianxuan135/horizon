"""市场拥挤度模型：13 个固定行业 x 五维加权 -> 0-100 综合分（API_CONTRACT 第 2 节）。

数据来源
--------
- 行业价格代理：每个行业取一只高流动性 ETF / 指数作为该行业的「价格代理」
  （见 PROXY_SYMBOLS），统一经 app.analytics.series.load_closes 获取，内部降级链为
  Yahoo Finance -> AKShare -> synthetic。真实数据不可得时 source 会如实写成
  "synthetic"，绝不伪装成真实行情。
- 市场基准指数：us = ^GSPC（标普500），cn = 000300（沪深300）。用于
  composite.index.value，以及「传播热度」维度里的市场联动基准。

代理指标说明（合规重点，务必如实标注）
--------------------------------------
真实产品口径中的资金 / 情绪子指标 —— 美股：ETF 净流入比、暗池成交占比、13F 集中度、
相对 SPY 成交量；A 股：主力净流入占比、ETF 净申购、龙虎榜机构净买、板块成交额占比 ——
**均无合法免费数据源**（交易所 Level-2、Dark Pool、13F 明细均为付费/受限数据），
本实现只用免费日线收盘价构造**公开代理指标**，绝不把代理值标注成真实资金流，
并在响应 warnings[] 中逐条说明：

1. funding  资金拥挤度（权重 0.33）
   raw = 区间涨幅(period 个交易日) / 20 日年化波动率
   —— 风险调整后的资金推动强度代理。（无成交量数据，故不能用成交额占比口径。）
2. pullback 补仓力度（权重 0.22）
   raw = 近 20 日内「下跌日之后 2 个交易日累计对数收益」的均值 / 20 日年化波动率
   —— 跌下去有没有人接盘的强度代理；只用到 t 及以前的信息，无未来函数。
3. anxiety  焦虑指数（权重 0.18）
   raw = 20 日年化已实现波动率 —— 波动越大，市场越焦虑。
4. social   社交热度（权重 0.15）
   raw = period 日内平均 |日对数收益| / 20 日年化波动率
   —— 无合法社媒数据源，用「异常波动关注度」代理讨论/关注度。
5. spread   传播热度（权重 0.12）
   raw = 该行业日收益与市场指数日收益的 60 日滚动相关系数
   —— 联动越强，情绪与风险越容易在板块间扩散（传染）。

计算逻辑
--------
1) 每个 raw 指标先做 252 日滚动标准化：z = (raw - μ252) / σ252
   （样本不足 252 日时从 min_periods=120 起算，有偏但可用，已在文档注明）。
2) score = 50 * (1 + tanh(z / 1.5)) 软饱和映射到 0-100，避免极端值把色带撑爆。
3) 行业综合分 = Σ(维度权重 x 维度分)，权重固定见 app/scoring/composite.py。
4) 市场综合分 = 13 个行业综合分的等权均值，再经 band() 映射 5 档色带。
5) 全程确定性（同一输入 -> 同一输出），结果按 (market, period) 缓存 TTL["daily"] 秒。

口径约定：mainSeries / 各维度 series 中的点全部为「当日收盘后可得」的值，不含未来数据。
"""

from __future__ import annotations

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
from .composite import (
    DIMENSIONS,
    INDUSTRY_BY_KEY,
    INDUSTRY_KEYS,
    PERIOD_DAYS,
    Z_MIN_PERIODS,
    Z_WINDOW,
    band,
    rolling_z,
    series_points,
    to_score,
)

__all__ = ["INDEX", "PROXY_SYMBOLS", "history_payload", "score_payload"]

# 市场基准指数：key -> (代码, 中文名)
INDEX: Final[dict[str, tuple[str, str]]] = {
    "us": ("^GSPC", "标普500"),
    "cn": ("000300", "沪深300"),
}

# 行业价格代理：每个行业一只高流动性标的（美股用行业 ETF，A 股用场内行业 ETF）。
# 说明：这些标的只是**行业价格代理**，不是「该行业的全部成分股」，口径已在文档与
# warnings 中注明；代理标的代码变更时只需改这张表。
PROXY_SYMBOLS: Final[dict[str, dict[str, str]]] = {
    "us": {
        "chips": "SMH",
        "semiconductor": "SOXX",
        "software": "IGV",
        "robotics": "BOTZ",
        "biotech": "XBI",
        "telecom": "XLC",
        "consumer": "XLY",
        "energy": "XLE",
        "transport": "IYT",
        "power": "XLU",
        "financials": "XLF",
        "precious_metals": "GLD",
        "aerospace": "ITA",
    },
    "cn": {
        "chips": "159995",
        "semiconductor": "512480",
        "software": "515230",
        "robotics": "562500",
        "biotech": "512010",
        "telecom": "515880",
        "consumer": "159928",
        "energy": "159930",
        "transport": "516910",
        "power": "561560",
        "financials": "512880",
        "precious_metals": "518880",
        "aerospace": "512660",
    },
}

# 各维度序列返回的点数（前端趋势图足够，同时把响应体压在 ~100KB 以内）
DIM_SERIES_POINTS: Final[int] = 250

PROXY_WARNING: Final[str] = (
    "资金/情绪类子指标（美股 ETF 净流入比、暗池成交占比、13F 集中度、相对 SPY 成交量；"
    "A 股主力净流入占比、ETF 净申购、龙虎榜机构净买、板块成交额占比）均无合法免费数据源，"
    "本接口已改用「仅依赖日线收盘价」的公开代理指标（口径见 app/scoring/crowding.py 模块文档），"
    "请勿将其视作真实资金流数据。"
)

_IDX_COL: Final[str] = "__market_index__"


def score_payload(market: str, period: str) -> dict:
    """返回 /crowding/score 的完整响应（含 5 维序列与主序列），按 (market, period) 缓存。"""
    key = f"crowding:v1:{market}:{period}"
    hit = cache_get(key)
    if hit is not None:
        return hit
    payload = _compute(market, period)
    cache_set(key, payload, TTL["daily"])
    return payload


def history_payload(market: str, days: int, period: str) -> dict:
    """返回 /crowding/history 的响应：从 score_payload 复用计算结果，只按日历天数裁剪主序列。"""
    payload = score_payload(market, period)
    cutoff = (date.today() - timedelta(days=int(days))).isoformat()
    series = [p for p in payload.get("mainSeries", []) if p["t"] >= cutoff]
    warnings = list(payload.get("warnings", []))
    if not series:
        warnings.append(f"最近 {days} 天内没有可用数据点（历史样本需满足 252 日标准化预热），已返回空序列。")
    return {
        "asOf": payload["asOf"],
        "dataThrough": payload.get("dataThrough"),
        "source": payload["source"],
        "market": market,
        "period": period,
        "days": int(days),
        "series": series,
        "warnings": warnings,
    }


def _dimension_scores(px: pd.DataFrame, index_close: pd.Series, period: str) -> dict[str, pd.DataFrame]:
    """五个维度的 0-100 分数矩阵（index=交易日，columns=行业 key）。"""
    ret = np.log(px / px.shift(1))
    vol20 = (ret.rolling(20, min_periods=10).std() * np.sqrt(252)).replace(0.0, np.nan)

    h = max(1, min(PERIOD_DAYS.get(period, 5), max(1, len(px) - 2)))
    mom = px / px.shift(h) - 1.0
    # 资金推动强度 = 区间涨幅 / 年化波动（风险调整后的动量，作为资金拥挤度代理）
    funding_raw = mom / vol20

    # 补仓力度：只看「下跌日（t-2）」之后 t-1、t 两日的累计涨幅，无未来函数
    bounce = (ret + ret.shift(1)).where(ret.shift(2) < 0.0)
    pullback_raw = bounce.rolling(20, min_periods=3).mean() / vol20

    # 焦虑指数：直接用已实现波动率本身
    anxiety_raw = vol20

    # 社交热度：period 日内平均绝对收益 / 年化波动（异常波动关注度代理）
    social_raw = ret.abs().rolling(h, min_periods=max(1, min(h, h // 2))).mean() / vol20

    # 传播热度：与市场指数的 60 日滚动相关系数
    idx_ret = np.log(index_close / index_close.shift(1))
    spread_raw = pd.DataFrame(
        {key: ret[key].rolling(60, min_periods=20).corr(idx_ret) for key in ret.columns},
        index=ret.index,
    )

    raws: dict[str, pd.DataFrame] = {
        "funding": funding_raw,
        "pullback": pullback_raw,
        "anxiety": anxiety_raw,
        "social": social_raw,
        "spread": spread_raw,
    }
    scores: dict[str, pd.DataFrame] = {}
    for dim in DIMENSIONS:
        raw = raws[dim.key]
        scores[dim.key] = pd.DataFrame(
            to_score(rolling_z(raw, Z_WINDOW, Z_MIN_PERIODS)),
            index=raw.index,
            columns=raw.columns,
        )
    return scores


def _empty_payload(market: str, period: str, source: str, warnings: list[str]) -> dict:
    """历史样本不足时的兜底响应：结构完整、数值为 None，前端不会崩。"""
    return {
        "asOf": utc_now_iso(),
        "dataThrough": None,
        "source": source,
        "market": market,
        "period": period,
        "industries": [],
        "composite": {
            "score": None,
            "label": "中立",
            "color": "neutral",
            "index": {"symbol": INDEX[market][0], "name": INDEX[market][1], "value": None},
        },
        "dimensions": [
            {"key": d.key, "name": d.name, "weight": d.weight, "score": None, "series": []}
            for d in DIMENSIONS
        ],
        "mainSeries": [],
        "warnings": warnings,
    }


def _compute(market: str, period: str) -> dict:
    warnings: list[str] = [PROXY_WARNING]
    symbols = PROXY_SYMBOLS[market]
    closes: dict[str, pd.Series] = {}
    sources: list[str] = []

    for key in INDUSTRY_KEYS:
        sym = symbols[key]
        series, src = load_closes(sym, market, LOOKBACK_BARS)
        closes[key] = series
        sources.append(src)
        if len(series) < Z_MIN_PERIODS + 40:
            warnings.append(
                f"行业 {INDUSTRY_BY_KEY[key].name}（代理标的 {sym}）历史样本仅 {len(series)} 条，"
                "滚动标准化预热不足，评分可能缺失或不稳定。"
            )

    idx_sym, idx_name = INDEX[market]
    idx_close, idx_src = load_closes(idx_sym, market, LOOKBACK_BARS)
    sources.append(idx_src)

    source = merge_source(sources)
    syn = synthetic_warning(source)
    if syn:
        warnings.append(syn)

    frame = align({**closes, _IDX_COL: idx_close})
    n = int(frame.shape[0])
    if n < Z_MIN_PERIODS:
        warnings.append(
            f"对齐后仅 {n} 个共同交易日，不足以做 252 日滚动标准化（至少需要 {Z_MIN_PERIODS} 个），"
            "本次返回空序列。"
        )
        return _empty_payload(market, period, source, warnings)

    index_close = frame.pop(_IDX_COL)
    px = frame[list(INDUSTRY_KEYS)]

    scores = _dimension_scores(px, index_close, period)

    # 行业综合分：Σ(权重 x 维度分)，五个维度都算出来之后才计入
    industry_score: pd.DataFrame | None = None
    for dim in DIMENSIONS:
        part = scores[dim.key] * float(dim.weight)
        industry_score = part if industry_score is None else industry_score + part
    assert industry_score is not None
    industry_score = industry_score.dropna(how="any")

    if len(industry_score) == 0:
        warnings.append(
            "各维度 z 分数尚在预热期（252 日窗口 + 20~60 日特征窗口），暂无完整可用的综合分，本次返回空序列。"
        )
        return _empty_payload(market, period, source, warnings)

    composite_series = industry_score.mean(axis=1)
    index_aligned = index_close.reindex(composite_series.index)

    # 主序列：每个交易日一个综合分 + 当日指数点位
    main_series: list[dict] = []
    for ts, value in composite_series.items():
        label, _color = band(float(value))
        idx_val = rnd(index_aligned.get(ts), 2)
        main_series.append(
            {"t": str(ts)[:10], "score": rnd(float(value), 1), "label": label, "indexValue": idx_val}
        )

    last_ts = industry_score.index[-1]
    ref_ts = industry_score.index[-6] if len(industry_score) > 5 else industry_score.index[0]

    industries: list[dict] = []
    for key in INDUSTRY_KEYS:
        meta = INDUSTRY_BY_KEY[key]
        cur = float(industry_score.loc[last_ts, key])
        prev = float(industry_score.loc[ref_ts, key])
        label, color = band(cur)
        industries.append(
            {
                "key": key,
                "name": meta.name,
                "nameEn": meta.name_en,
                "score": rnd(cur, 1),
                "label": label,
                "color": color,
                # 与 5 个交易日前的差值，供热力图显示涨跌箭头
                "change": rnd(cur - prev, 1),
                # 价格代理标的，前端「数据来源」浮层可直接展示
                "proxy": symbols[key],
                "dims": {d.key: rnd(scores[d.key].loc[last_ts, key], 1) for d in DIMENSIONS},
            }
        )

    dimensions: list[dict] = []
    for dim in DIMENSIONS:
        mean_series = scores[dim.key].mean(axis=1)
        dimensions.append(
            {
                "key": dim.key,
                "name": dim.name,
                "weight": dim.weight,
                "score": rnd(mean_series.dropna().iloc[-1], 1) if mean_series.notna().any() else None,
                "series": series_points(mean_series, digits=1, limit=DIM_SERIES_POINTS),
            }
        )

    composite_value = float(composite_series.iloc[-1])
    label, color = band(composite_value)

    return {
        "asOf": utc_now_iso(),
        "dataThrough": str(last_ts)[:10],
        "source": source,
        "market": market,
        "period": period,
        "industries": industries,
        "composite": {
            "score": rnd(composite_value, 1),
            "label": label,
            "color": color,
            "index": {
                "symbol": idx_sym,
                "name": idx_name,
                "value": rnd(index_aligned.iloc[-1], 2),
            },
        },
        "dimensions": dimensions,
        "mainSeries": main_series,
        "warnings": warnings,
    }