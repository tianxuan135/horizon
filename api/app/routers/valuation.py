"""估值分析路由（API_CONTRACT §4）。

端点
====
* ``GET  /search?q=&market=``          标的联想（真实 provider 检索链）
* ``GET  /watchlist?market=``          自选列表（DB 持久化，按 ``sort`` 升序）
* ``POST /watchlist``                  加入自选（幂等）
* ``DELETE /watchlist/{id}``           移除
* ``POST /watchlist/reorder``          重排（body ``{"ids": [...]}``）
* ``GET  /score/{symbol}?market=``     四维评分 + 估值指标 + PE 走势

数据来源
========
行情一律走 ``app.providers``（yahoo → akshare → 合成，永不抛错），
评分与指标公式见 ``app.analytics.valuation``。响应里的 ``source`` 如实回显
这次算分到底用的哪条数据链路；指标为**价格反推的代理值**
（``metricsBasis="price-derived-proxy"``），不是财报口径——前端需在 UI 上标注。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.common import utc_now_iso
from ..analytics.valuation import bucket_of, score_payload
from ..db import get_db
from ..models import WatchlistItem
from ..providers.base import get_bars, search_symbols

log = logging.getLogger("horizon.valuation")
router = APIRouter(prefix="/api/v1/valuation", tags=["valuation"])

MARKETS = ("us", "cn")
# 首次访问时的默认自选（每个市场一套；用户可随意删改）
DEFAULT_WATCHLIST: dict[str, list[str]] = {
    "us": ["AAPL", "MSFT", "NVDA", "KO", "XOM"],
    "cn": ["600519", "000858", "300750", "600036", "601899"],
}


class WatchIn(BaseModel):
    """加入自选请求体。"""

    symbol: str = Field(..., min_length=1, max_length=24)
    market: str = Field("us", max_length=8)


class ReorderIn(BaseModel):
    """重排请求体：ids 的顺序即新的 ``sort`` 顺序。"""

    ids: list[str] = Field(..., min_length=1, max_length=200)


def _market(market: str | None) -> str:
    m = (market or "us").strip().lower()
    if m not in MARKETS:
        raise HTTPException(status_code=400, detail=f"market 必须是 {MARKETS}，收到 {market!r}")
    return m


def _item_dict(row: WatchlistItem) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "name": row.name,
        "market": row.market,
        "bucket": row.bucket,
        "sort": int(row.sort or 0),
    }


def _seed_if_empty(db: Session, market: str) -> None:
    """首次访问时写入默认自选，避免前端空列表（可删改，仅市场维度一次性）。"""
    exists = db.scalar(select(func.count()).select_from(WatchlistItem).where(WatchlistItem.market == market))
    if exists:
        return
    for i, sym in enumerate(DEFAULT_WATCHLIST.get(market, [])):
        bucket, _reason = bucket_of(sym, market)
        quote = None
        try:
            from ..providers.base import get_quote

            quote = get_quote(sym, market)
        except Exception:  # noqa: BLE001 - provider 层保底不抛，这里再兜一层
            quote = None
        name = getattr(quote, "name", None) or sym
        db.add(
            WatchlistItem(
                market=market,
                symbol=sym.upper() if market == "us" else sym,
                name=name,
                bucket=bucket,
                sort=i,
            )
        )
    db.commit()


@router.get("/search")
def search(q: str = Query("", max_length=64), market: str = Query("us")) -> dict:
    """标的联想。``results`` 为 ```[{symbol,name,exchange,market}]``。"""
    m = _market(market)
    results = search_symbols((q or "").strip(), m)
    return {
        "asOf": utc_now_iso(),
        "q": q,
        "market": m,
        "results": results,
        "source": "provider:search",
    }


@router.get("/watchlist")
def watchlist(market: str = Query("us"), db: Session = Depends(get_db)) -> dict:
    """自选列表，按 ``sort`` 升序。首次调用会写入该市场的默认自选。"""
    m = _market(market)
    _seed_if_empty(db, m)
    rows = db.scalars(
        select(WatchlistItem).where(WatchlistItem.market == m).order_by(WatchlistItem.sort, WatchlistItem.created_at)
    ).all()
    return {"asOf": utc_now_iso(), "market": m, "items": [_item_dict(r) for r in rows], "source": "db:watchlist"}


@router.post("/watchlist")
def watchlist_add(body: WatchIn, db: Session = Depends(get_db)) -> dict:
    """加入自选。已存在则原样返回（幂等），``sort`` 追加到末尾。"""
    m = _market(body.market)
    symbol = body.symbol.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol 不能为空")
    symbol = symbol.upper() if m == "us" else symbol
    row = db.scalar(select(WatchlistItem).where(WatchlistItem.market == m, WatchlistItem.symbol == symbol))
    if row is not None:
        return {"asOf": utc_now_iso(), "item": _item_dict(row), "created": False, "source": "db:watchlist"}

    bucket, _reason = bucket_of(symbol, m)
    name = symbol
    try:
        from ..providers.base import get_quote

        quote = get_quote(symbol, m)
        name = getattr(quote, "name", None) or symbol
    except Exception:  # noqa: BLE001
        log.warning("watchlist add: quote lookup failed for %s/%s", m, symbol)
    top = db.scalar(select(func.max(WatchlistItem.sort)).where(WatchlistItem.market == m))
    row = WatchlistItem(
        market=m, symbol=symbol, name=name, bucket=bucket, sort=int(top) + 1 if top is not None else 0
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"asOf": utc_now_iso(), "item": _item_dict(row), "created": True, "source": "db:watchlist"}


@router.delete("/watchlist/{item_id}")
def watchlist_remove(item_id: str, db: Session = Depends(get_db)) -> dict:
    """按 id 移除自选；id 不存在返回 404。"""
    row = db.get(WatchlistItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"自选项 {item_id} 不存在")
    db.delete(row)
    db.commit()
    return {"asOf": utc_now_iso(), "ok": True}


@router.post("/watchlist/reorder")
def watchlist_reorder(body: ReorderIn, db: Session = Depends(get_db)) -> dict:
    """按传入 ids 顺序重写 ``sort``（未出现在 ids 里的项顺延编号）。"""
    ids = [i.strip() for i in body.ids if i and i.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    rows = {r.id: r for r in db.scalars(select(WatchlistItem).where(WatchlistItem.id.in_(ids))).all()}
    missing = [i for i in ids if i not in rows]
    if missing:
        raise HTTPException(status_code=400, detail=f"以下自选 id 不存在：{', '.join(missing[:5])}")
    for pos, wid in enumerate(ids):
        rows[wid].sort = pos
    # 未提及的项保持在后面，相对顺序不变
    rest = db.scalars(
        select(WatchlistItem).where(WatchlistItem.id.notin_(ids)).order_by(WatchlistItem.sort, WatchlistItem.created_at)
    ).all()
    for pos, r in enumerate(rest, start=len(ids)):
        r.sort = pos
    db.commit()
    return {"asOf": utc_now_iso(), "ok": True, "count": len(ids)}


@router.get("/score/{symbol}")
def score(symbol: str, market: str = Query("us")) -> dict:
    """四维评分 + 估值指标 + PE 走势（字段名与契约 §4 一致）。

    计算全部基于真实日线；数据缺失时降级为合成序列并在 ``source`` 标注
    ``synthetic``。``marketCap`` 因无股本/市值数据源恒为 ``null``（绝不编造），
    前端请按 "—" 渲染。
    """
    m = _market(market)
    sym = (symbol or "").strip()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol 不能为空")
    sym = sym.upper() if m == "us" else sym

    bar = get_bars(sym, m, days=800)
    closes = list(bar.closes or [])
    if len(closes) < 60:
        raise HTTPException(status_code=400, detail=f"{sym} 可用日线不足（{len(closes)} 条），无法评分")

    bench_symbol = "^GSPC" if m == "us" else "000300"
    try:
        bench = get_bars(bench_symbol, m, days=800)
        bench_closes = list(bench.closes or [])
    except Exception:  # noqa: BLE001
        log.warning("score: benchmark %s unavailable, corr falls back to 0", bench_symbol)
        bench_closes = None

    name = sym
    try:
        from ..providers.base import get_quote

        quote = get_quote(sym, m)
        name = getattr(quote, "name", None) or sym
    except Exception:  # noqa: BLE001
        pass

    payload = score_payload(
        symbol=sym,
        market=m,
        name=name,
        closes=closes,
        dates=list(bar.dates or []),
        bar_source=bar.source,
        bench_closes=bench_closes,
    )
    return payload