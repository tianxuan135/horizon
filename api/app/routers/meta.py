"""元信息路由（API_CONTRACT §1）：数据源健康状态与合规声明。

端点
====
* ``GET /api/v1/meta/status?market=us``  各数据源可用性 + 版本 + 免责声明

数据来源
========
``sources`` 全部来自 ``app.providers.base.provider_status()``（真实探测各 provider 的
``available()``，含耗时），本路由不做任何美化：不可用的源 ``ok=false`` 且附 ``note``。
``freshness`` 是对该源**更新节奏**的静态说明（写在下方 FRESHNESS 表里），属于文案而非
探测结果，只随 provider 更换而修改。

合规
====
响应固定携带 ``disclaimer``；本服务不提供任何买卖建议、不预测个股、不下投资结论。
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, HTTPException, Query

from .. import __version__
from ..analytics.common import utc_now_iso
from ..cache import TTL, get as cache_get, set as cache_set
from ..providers.base import provider_status

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])

MARKETS: Final[tuple[str, ...]] = ("us", "cn")

DISCLAIMER: Final[str] = "本工具所有数据及分析结果仅供学习研究参考，不构成任何投资建议。"

# 各数据源的更新节奏说明（静态文案，非探测结果）
FRESHNESS: Final[dict[str, str]] = {
    "yahoo": "上游为准：盘中为延迟行情，日线为收盘后更新",
    "akshare": "日终行情，收盘后更新（部分接口 T+1）",
    "synthetic": "内置确定性合成序列，无真实时效（离线兜底）",
}


def _market(market: str | None) -> str:
    m = (market or "us").strip().lower()
    if m not in MARKETS:
        raise HTTPException(status_code=400, detail=f"market 必须是 {MARKETS}，收到 {market!r}")
    return m


@router.get("/status")
def status(market: str = Query("us", max_length=8)) -> dict:
    """数据源状态。``sources[]`` 字段：id / name / kind / ok / latencySec / license / freshness。"""
    m = _market(market)
    key = f"meta:status:v1:{m}"
    hit = cache_get(key)
    if hit is not None:
        return hit

    sources = []
    for s in provider_status():
        sources.append(
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind,
                "ok": bool(s.ok),
                # 探测耗时（秒），保留 3 位；探测本身很轻，主要是可用性判断
                "latencySec": round(int(s.latency_ms) / 1000.0, 3),
                "license": s.license,
                "freshness": FRESHNESS.get(s.id, "未标注"),
                "note": s.note,
            }
        )

    payload = {
        "asOf": utc_now_iso(),
        "app": "Horizon",
        "version": __version__,
        "market": m,
        "sources": sources,
        "source": "provider:status",
        "disclaimer": DISCLAIMER,
    }
    # 探测有网络耗时，缓存 60 秒即可，避免频繁探活上游
    cache_set(key, payload, TTL["quote"])
    return payload