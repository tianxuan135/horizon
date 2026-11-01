"""价格序列装载、按交易日对齐与上游可用性探测（拥挤度 / 风格轮动共用数据层）。

数据来源
--------
- 一律通过 app.providers.base.get_bars(symbol, market, days) 取日线收盘价。该函数
  内置降级链「Yahoo Finance -> AKShare -> synthetic」，并把实际使用的数据源写在
  Bar.source 中；本模块把 source 原样透传到接口响应，前端据此在「数据状态」页展示。
  合规要求：source = "synthetic" 时必须如实暴露，绝不伪装成真实行情。

- 上游探测：免费公开接口在无网络 / 被限流时，每个标的都要等一次连接超时
  （逐标的 1~8s，14 个标的会把首次请求拖到十几秒）。因此本模块先做一次轻量探测，
  结果缓存 PROBE_TTL 秒；探测失败时直接使用内置 synthetic 确定性代理数据，
  保证接口稳定在百毫秒级，并在响应里明确标注 source = "synthetic"。

- 对齐：各标的交易日历不同（美股指数 / 美股 ETF / A 股 ETF / 中证指数），
  任何跨标的计算（ln(A/B)、滚动相关系数）之前都必须按交易日做内连接对齐，
  否则会把不同日期的价格当成同一天比较。

时间口径：对外时间戳统一为 UTC ISO 8601（秒级，以 Z 结尾），复用 app.analytics.common。
"""

from __future__ import annotations

import time
from typing import Iterable

import pandas as pd

from ..cache import TTL, get as cache_get, set as cache_set
from ..providers.base import Bar, get_bars
from .common import utc_now_iso

__all__ = [
    "LOOKBACK_BARS",
    "align",
    "load_closes",
    "merge_source",
    "synthetic_warning",
    "utc_now_iso",
]

# 上游可用性探测结果缓存（秒）
PROBE_TTL = 600
_probe: dict[str, tuple[float, bool]] = {}

# 统一回看交易日数：252 日滚动标准化 + 10 日位移 + 缓冲；520 个交易日约 2 年，足够。
LOOKBACK_BARS = 520


def _upstream_ok() -> bool:
    """免费公开上游是否可用（只探测一次，结果缓存 PROBE_TTL 秒）。"""
    from ..config import settings

    if not settings.yahoo_enabled:
        return False
    now = time.time()
    hit = _probe.get("yahoo")
    if hit and hit[0] > now:
        return hit[1]
    ok = False
    try:
        from ..providers import yahoo

        probe = yahoo.YahooProvider().bars("^GSPC", 25)
        ok = bool(probe and len(probe) > 20 and probe.source != "synthetic")
    except Exception:
        ok = False
    _probe["yahoo"] = (now + PROBE_TTL, ok)
    return ok


def _akshare_ok() -> bool:
    """AKShare 是否可用（未安装 / 未启用时返回 False，全程不抛异常）。"""
    try:
        from ..providers import akshare_provider

        return akshare_provider.AkshareProvider().available()
    except Exception:
        return False


def _fetch_bars(symbol: str, market: str, days: int) -> Bar:
    """取原始日线：上游全部不可用时直接走内置 synthetic，避免逐标的超时等待。"""
    if _upstream_ok() or _akshare_ok():
        return get_bars(symbol, market, days)
    from ..providers import synthetic

    bar = synthetic.SyntheticProvider().bars(symbol, days)
    return bar or Bar()


def load_closes(symbol: str, market: str, days: int = LOOKBACK_BARS) -> tuple[pd.Series, str]:
    """取单个标的的日线收盘价序列。

    返回 (series, source)：
    - series：index 为 YYYY-MM-DD 交易日（升序、去重），value 为收盘价 float。
    - source：实际数据源 id（"yahoo" / "akshare" / "synthetic"），必须透传到响应。
    """
    key = f"bars:v1:{market}:{symbol}:{days}"
    hit = cache_get(key)
    if hit:
        bar = Bar(dates=list(hit["dates"]), closes=list(hit["closes"]), source=str(hit["source"]))
    else:
        bar = _fetch_bars(symbol, market, days)
        cache_set(key, {"dates": bar.dates, "closes": bar.closes, "source": bar.source}, TTL["daily"])

    idx = pd.Index([str(d)[:10] for d in bar.dates], name="date")
    series = pd.Series([float(c) for c in bar.closes], index=idx, dtype="float64")
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series, bar.source


def align(named: dict[str, pd.Series]) -> pd.DataFrame:
    """多条价格序列按交易日做内连接对齐。

    columns 顺序严格等于传入字典的键顺序（下游按列名取值，不依赖 pandas 键排序），
    只保留所有标的同时有交易的日子，杜绝跨标的日期错位。
    """
    if not named:
        return pd.DataFrame()
    cols = list(named.keys())
    frame = pd.concat([named[c] for c in cols], axis=1, join="inner")
    frame.columns = cols
    return frame.dropna(how="any").sort_index()


def merge_source(sources: Iterable[str]) -> str:
    """把多个标的的数据源合并成一个标识：单一来源原样返回，混合时给 "mixed:a+b"。"""
    uniq = sorted({str(s) for s in sources if s})
    if not uniq:
        return "synthetic"
    if len(uniq) == 1:
        return uniq[0]
    return "mixed:" + "+".join(uniq)


def synthetic_warning(source: str) -> str | None:
    """source 含 synthetic 时给出统一告警文案，否则返回 None。"""
    if "synthetic" in str(source):
        return (
            "当前价格序列包含内置 synthetic 合成代理数据（确定性生成，仅用于离线演示/网络不可用时的降级），"
            "非真实行情，请以响应的 source 字段为准，不要用于任何真实决策。"
        )
    return None