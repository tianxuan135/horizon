"""因子策略路由（API_CONTRACT §5）。

* ``GET  /strategies``        策略清单（裸数组）
* ``GET  /benchmarks``        基准清单（裸数组，按 market 过滤）
* ``POST /backtest``          多因子选股回测（月度调仓、含交易成本）
* ``GET  /mine``              因子挖掘：rank-IC / ICIR / t 值 / 换手率

实现细节（与引擎一一对应，公式见 ``app.backtest.engine`` 的 docstring）：

* 每月最后一个交易日调仓，按复合因子 z-score 取前 25% 等权持有，
  次日成交避免前视偏差，成本 = ``feeBps/1e4 × turnover``，
  ``turnover = 0.5 × Σ|w_new − w_old|``（单边换手）。
* rank-IC = 每期因子排名与**未来 21 日收益排名**的 Spearman 相关，
  IC = 均值，ICIR = IC / std(IC)，t 值 = ICIR × √n，换手率按前 25% 组合计算。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..analytics.common import utc_now_iso
from ..backtest.engine import mine_factors, run_backtest
from ..backtest.strategies import STRATEGY_BY_ID, benchmarks_for, strategies_payload

log = logging.getLogger("horizon.factor")
router = APIRouter(prefix="/api/v1/factor", tags=["factor"])

MARKETS = ("us", "cn")


class BacktestIn(BaseModel):
    """因子回测请求体（契约 §5）。"""

    market: str = Field("us", max_length=8)
    strategyId: str = Field("momentum", max_length=32)
    start: str | None = Field(None, max_length=10)
    end: str | None = Field(None, max_length=10)
    benchmark: str | None = Field(None, max_length=16)
    feeBps: float = Field(5.0, ge=0, le=100)
    topFrac: float = Field(0.25, gt=0, le=1)


def _market(market: str | None) -> str:
    m = (market or "us").strip().lower()
    if m not in MARKETS:
        raise HTTPException(status_code=400, detail=f"market 必须是 {MARKETS}，收到 {market!r}")
    return m


@router.get("/strategies")
def strategies() -> list[dict]:
    """策略清单：``[{id,name,factors,desc}]``。"""
    return strategies_payload()


@router.get("/benchmarks")
def benchmarks(market: str = Query("us")) -> list[dict]:
    """基准清单：``[{id,symbol,name,market}]``（market 非法时 400）。"""
    return benchmarks_for(_market(market))


@router.post("/backtest")
def backtest(body: BacktestIn) -> dict:
    """跑一次因子回测，返回 ``{equity:[{t,nav,bench}], metrics{...}, benchmark{id,name}}``。"""
    m = _market(body.market)
    sid = (body.strategyId or "momentum").strip().lower()
    if sid not in STRATEGY_BY_ID:
        raise HTTPException(
            status_code=400,
            detail=f"未知策略 strategyId={body.strategyId!r}，可选：{', '.join(STRATEGY_BY_ID)}",
        )
    try:
        return run_backtest(
            market=m,
            strategy_id=sid,
            start=body.start,
            end=body.end,
            benchmark_id=body.benchmark,
            fee_bps=float(body.feeBps),
            top_frac=float(body.topFrac),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 兜底：provider 异常不该变成 500 白屏
        log.exception("factor backtest failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"回测暂时不可用：{type(exc).__name__}: {exc}") from exc


@router.get("/mine")
def mine(
    market: str = Query("us"),
    window: int = Query(252, ge=60, le=1500),
    horizon: int = Query(21, ge=5, le=63),
    topFrac: float = Query(0.25, gt=0, le=1),
) -> list[dict]:
    """因子挖掘结果（裸数组，按 |ic| 降序）：``[{factor,ic,icir,tStat,turnover,desc,...}]``。"""
    m = _market(market)
    try:
        return mine_factors(market=m, window=int(window), horizon=int(horizon), top_frac=float(topFrac))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("factor mine failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"因子挖掘暂时不可用：{type(exc).__name__}: {exc}") from exc


@router.get("/mine/{factor}")
def mine_one(factor: str, market: str = Query("us"), window: int = Query(252, ge=60, le=1500)) -> dict:
    """单个因子的挖掘明细（从 /mine 结果里筛出来，便于前端做因子详情页）。"""
    m = _market(market)
    try:
        rows = mine_factors(market=m, window=int(window))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for row in rows:
        if str(row.get("factor", "")).lower() == factor.strip().lower():
            return {"asOf": utc_now_iso(), "market": m, "factor": row}
    raise HTTPException(status_code=404, detail=f"未找到因子 {factor!r}")