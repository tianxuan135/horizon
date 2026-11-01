"""市场拥挤度路由（API_CONTRACT §2）。

端点
====
* ``GET /api/v1/crowding/industries``                      13 个固定行业字典
* ``GET /api/v1/crowding/score?market=us&period=5d``        行业评分 + 五维 + 主序列
* ``GET /api/v1/crowding/history?market=us&days=365&period=5d`` 综合分历史序列

数据来源与算法
==============
计算全部在 ``app.scoring.crowding``（价格代理 -> 五维代理指标 -> 252 日滚动标准化 ->
``50*(1+tanh(z/1.5))`` 映射 0-100 分）；行业/维度/色带的唯一事实来源是
``app.scoring.composite``。付费口径子指标（ETF 净流入、暗池、13F、主力净流入 …）
无合法免费源，一律使用文档化的公开价格代理，并在 ``warnings[]`` 中如实标注，
绝不把代理值伪装成真实资金流。
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, HTTPException, Query

from ..analytics.common import utc_now_iso
from ..scoring.composite import INDUSTRIES, PERIODS
from ..scoring.crowding import history_payload, score_payload

router = APIRouter(prefix="/api/v1/crowding", tags=["crowding"])

MARKETS: Final[tuple[str, ...]] = ("us", "cn")
DEFAULT_PERIOD: Final[str] = "5d"
MAX_DAYS: Final[int] = 3650


def _market(market: str | None) -> str:
    m = (market or "us").strip().lower()
    if m not in MARKETS:
        raise HTTPException(status_code=400, detail=f"market 必须是 {MARKETS}，收到 {market!r}")
    return m


def _period(period: str | None) -> str:
    p = (period or DEFAULT_PERIOD).strip().lower()
    if p not in PERIODS:
        raise HTTPException(status_code=400, detail=f"period 必须是 {PERIODS}，收到 {period!r}")
    return p


@router.get("/industries")
def industries() -> dict:
    """13 个固定行业（不可增删）。``industries[]``：key / name / nameEn。"""
    return {
        "asOf": utc_now_iso(),
        "source": "static:app/scoring/composite.py",
        "industries": [{"key": i.key, "name": i.name, "nameEn": i.name_en} for i in INDUSTRIES],
        "periods": list(PERIODS),
    }


@router.get("/score")
def score(market: str = Query("us", max_length=8), period: str = Query(DEFAULT_PERIOD, max_length=8)) -> dict:
    """行业拥挤度评分：13 行业分 + 综合分 + 五维（各带历史序列）+ 主序列（历史综合分）。"""
    return score_payload(_market(market), _period(period))


@router.get("/history")
def history(
    market: str = Query("us", max_length=8),
    days: int = Query(365, ge=1, le=MAX_DAYS),
    period: str = Query(DEFAULT_PERIOD, max_length=8),
) -> dict:
    """综合分历史（``series[]``：t / score / indexValue），按日历天数裁剪，复用 /score 的缓存结果。"""
    return history_payload(_market(market), int(days), _period(period))