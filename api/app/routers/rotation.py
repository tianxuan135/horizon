"""风格 / 市值轮动路由（API_CONTRACT §3）。

端点
====
* ``GET /api/v1/rotation/score?market=us&group=size&days=365``

数据来源与算法
==============
两条腿的日线由 ``app.analytics.series.load_closes`` 提供（yahoo -> akshare -> synthetic），
计算在 ``app.scoring.rotation``：``R=ln(A/B)``、``M10=R-R(t-10)``、
``Z=(M10-μ252)/σ252``、``score=100*tanh(Z/2)``。免费源缺「消费品质」指数，
us/style 的 B 腿用 XLP 作公开代理，响应 ``pair.bProxy=true`` 并在 ``warnings`` 中注明。
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, HTTPException, Query

from ..scoring.rotation import GROUPS, rotation_payload

router = APIRouter(prefix="/api/v1/rotation", tags=["rotation"])

MARKETS: Final[tuple[str, ...]] = ("us", "cn")
MAX_DAYS: Final[int] = 3650


def _market(market: str | None) -> str:
    m = (market or "us").strip().lower()
    if m not in MARKETS:
        raise HTTPException(status_code=400, detail=f"market 必须是 {MARKETS}，收到 {market!r}")
    return m


def _group(market: str, group: str | None) -> str:
    g = (group or "size").strip().lower()
    allowed = tuple(GROUPS[market].keys())
    if g not in allowed:
        raise HTTPException(status_code=400, detail=f"group 必须是 {allowed}，收到 {group!r}")
    return g


@router.get("/score")
def score(
    market: str = Query("us", max_length=8),
    group: str = Query("size", max_length=16),
    days: int = Query(365, ge=1, le=MAX_DAYS),
) -> dict:
    """轮动强度序列。``series[]``：t / r / m10 / z / score；score>0 表示 A 腿相对走强。"""
    m = _market(market)
    return rotation_payload(m, _group(m, group), int(days))