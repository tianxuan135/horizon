"""行业清单、周期、维度权重、分数带与打分基元 —— 全项目唯一真相来源。

规范来源（产品规格，不得改动）
------------------------------
1. 行业清单：固定 13 个行业，不允许用户增删（见 INDUSTRIES）。key 用于前端路由与
   缓存键，name 为中文展示名，nameEn 为英文名。
2. 周期：PERIODS 是前端可切换的回看窗口，PERIOD_DAYS 把它换算成交易日数。
3. 五维权重**固定**：funding 0.33 / pullback 0.22 / anxiety 0.18 / social 0.15 /
   spread 0.12（见 DIMENSIONS / WEIGHTS）。任何调用方都不得改写。
4. 分数带：0-100 分映射 5 档颜色，见 SCORE_BANDS 与 band()：
   >=80 极度贪婪 greed / 65-80 偏进攻 attack / 45-65 中立 neutral /
   30-45 偏保守 defend / <30 极度恐慌 panic。

打分基元（供 crowding / rotation 复用）
---------------------------------------
- to_score(z)：z 分数软饱和到 0-100，score = 50 * (1 + tanh(z / 1.5))。
  用 tanh 而不是线性截断，保证极端行情下分数不会黏在 0/100 上。
- rolling_z(s)：滚动标准化 z = (x - μ_window) / σ_window。
- series_points(s)：Series -> [{"t": 日期, "v": 值}]，剔除 NaN，可选只取最近 N 个点。

所有输出都是「研究参考用指标」，不构成任何投资建议。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from ..analytics.common import rnd


@dataclass(frozen=True)
class Industry:
    """固定行业项：key 唯一，name 中文，name_en 英文。"""

    key: str
    name: str
    name_en: str


@dataclass(frozen=True)
class Dimension:
    """五维之一：权重由产品规格固定，不得改动。"""

    key: str
    name: str
    weight: float


# --- 13 个固定行业（顺序即前端热力图栅格顺序，不随分数重排）---------------------
INDUSTRIES: Final[tuple[Industry, ...]] = (
    Industry("chips", "芯片", "Chips"),
    Industry("semiconductor", "半导体", "Semiconductor"),
    Industry("software", "软件", "Software"),
    Industry("robotics", "机器人", "Robotics"),
    Industry("biotech", "生物医药", "Biotech"),
    Industry("telecom", "通讯", "Telecom"),
    Industry("consumer", "消费", "Consumer"),
    Industry("energy", "油气能源", "Energy"),
    Industry("transport", "运输", "Transport"),
    Industry("power", "算力电力", "Compute & Power"),
    Industry("financials", "银行证券", "Financials"),
    Industry("precious_metals", "贵金属", "Precious Metals"),
    Industry("aerospace", "航空航天", "Aerospace & Defense"),
)
INDUSTRY_BY_KEY: Final[dict[str, Industry]] = {i.key: i for i in INDUSTRIES}
INDUSTRY_KEYS: Final[tuple[str, ...]] = tuple(i.key for i in INDUSTRIES)

# --- 周期 ----------------------------------------------------------------------
PERIODS: Final[tuple[str, ...]] = ("1d", "3d", "5d", "10d", "30d", "90d", "250d")
PERIOD_DAYS: Final[dict[str, int]] = {
    "1d": 1,
    "3d": 3,
    "5d": 5,
    "10d": 10,
    "30d": 30,
    "90d": 90,
    "250d": 250,
}

# --- 五维（权重固定，顺序即展示顺序）-------------------------------------------
DIMENSIONS: Final[tuple[Dimension, ...]] = (
    Dimension("funding", "资金拥挤度", 0.33),
    Dimension("pullback", "补仓力度", 0.22),
    Dimension("anxiety", "焦虑指数", 0.18),
    Dimension("social", "社交热度", 0.15),
    Dimension("spread", "传播热度", 0.12),
)
WEIGHTS: Final[dict[str, float]] = {d.key: d.weight for d in DIMENSIONS}
DIMENSION_BY_KEY: Final[dict[str, Dimension]] = {d.key: d for d in DIMENSIONS}

# --- 5 档分数带：(下界, 中文标签, 颜色 key)，从高到低匹配 -----------------------
SCORE_BANDS: Final[tuple[tuple[float, str, str], ...]] = (
    (80.0, "极度贪婪", "greed"),
    (65.0, "偏进攻", "attack"),
    (45.0, "中立", "neutral"),
    (30.0, "偏保守", "defend"),
    (0.0, "极度恐慌", "panic"),
)

# 滚动标准化窗口：252 个交易日（约一年）
Z_WINDOW: Final[int] = 252
Z_MIN_PERIODS: Final[int] = 120
# z -> 0-100 的软饱和尺度
SCORE_Z_SCALE: Final[float] = 1.5


def band(score: float | None) -> tuple[str, str]:
    """0-100 综合分 -> (中文标签, 颜色 key)；非法输入按中立处理。"""
    if score is None:
        return "中立", "neutral"
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "中立", "neutral"
    if not np.isfinite(value):
        return "中立", "neutral"
    for lower, label, color in SCORE_BANDS:
        if value >= lower:
            return label, color
    return "极度恐慌", "panic"


def to_score(z: float | np.ndarray) -> float | np.ndarray:
    """z 分数 -> 0-100 软饱和分数：score = 50 * (1 + tanh(z / 1.5))。

    标量入参返回 float，数组/Series/DataFrame 入参返回同形状 ndarray。
    NaN 会原样传播（下游统一剔除）。
    """
    arr = np.asarray(z, dtype="float64")
    out = 50.0 * (1.0 + np.tanh(arr / SCORE_Z_SCALE))
    if np.isscalar(z) or arr.ndim == 0:
        return float(out)
    return out


def rolling_z(
    s: pd.Series | pd.DataFrame,
    window: int = Z_WINDOW,
    min_periods: int = Z_MIN_PERIODS,
) -> pd.Series | pd.DataFrame:
    """滚动标准化：z = (x - rolling_mean) / rolling_std。

    window 默认 252 个交易日；样本不足时按 min_periods 起算（比硬性要求满 252 日
    更早给出可读曲线，文档已注明）。标准差为 0（横盘）时记 NaN，避免除零炸出 inf。
    """
    mean = s.rolling(window, min_periods=min_periods).mean()
    std = s.rolling(window, min_periods=min_periods).std()
    return (s - mean) / std.replace(0.0, np.nan)


def series_points(s: pd.Series, digits: int = 1, limit: int | None = None) -> list[dict]:
    """Series -> [{"t": "YYYY-MM-DD", "v": number}]，剔除 NaN，只保留最近 limit 个点。"""
    if s is None or len(s) == 0:
        return []
    clean = s.dropna()
    if limit is not None and len(clean) > limit:
        clean = clean.iloc[-int(limit):]
    points: list[dict] = []
    for idx, val in clean.items():
        v = rnd(val, digits)
        if v is None:
            continue
        points.append({"t": str(idx)[:10], "v": v})
    return points


def last_value(s: pd.Series | None, digits: int = 1) -> float | None:
    """Series 最后一个有效值（四舍五入），全为 NaN 时返回 None。"""
    if s is None or len(s) == 0:
        return None
    clean = s.dropna()
    if len(clean) == 0:
        return None
    return rnd(clean.iloc[-1], digits)