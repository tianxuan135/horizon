"""期权策略路由（API_CONTRACT §6）。

* ``GET  /strategies``              策略清单（裸数组，前端计算器下拉框）
* ``GET  /spot/{symbol}``           标的现价（计算器基准价）
* ``GET  /expiries/{symbol}``       可选到期日
* ``GET  /chain/{symbol}``          期权链（模型推演报价）
* ``POST /payoff``                  到期损益、最大盈亏、盈亏平衡
* ``POST /backtest``                期权策略月度滚动回测

合规红线（写在这里，避免后人改动时忘掉）：
**期权研究工具，不含任何下单/持仓/券商对接能力，不使用任何"保证收益"表述。**
所有权利金均由 Black-Scholes + 已实现波动率模型推导（见 ``app/options/pricing.py``），
不是可交易报价，响应里 ``source``/``model``/``warnings`` 如实标注。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..analytics.common import utc_now_iso
from ..options.payoff import STRATEGY_IDS, compute_payoff, strategies_payload
from ..options.pricing import build_chain, expiries as list_expiries, quote_spot
from ..options.strategy_backtest import OPTION_STRATEGIES, run_option_backtest

log = logging.getLogger("horizon.options")
router = APIRouter(prefix="/api/v1/options", tags=["options"])

MARKETS = ("us", "cn")
DEFAULT_UNDERLYING = {"us": "^GSPC", "cn": "000300"}


class LegIn(BaseModel):
    """单条期权腿。``premium`` 为**每股**权利金。股票腿用 ``type="stock"`` + ``basis``。"""

    type: str = Field(..., max_length=8, description="call | put | stock")
    side: str = Field(..., max_length=8, description="long | short")
    strike: float | None = Field(None, description="行权价（股票腿忽略）")
    premium: float | None = Field(0.0, description="每股权利金（股票腿忽略）")
    qty: float | None = Field(1.0, description="合约张数；股票腿为股数")
    basis: float | None = Field(None, description="股票腿持仓成本，缺省用 spot")


class PayoffIn(BaseModel):
    """``POST /payoff`` 请求体（契约 §6）。"""

    spot: float = Field(..., gt=0, description="标的现价")
    strategy: str = Field("single", max_length=32)
    legs: list[LegIn] = Field(default_factory=list)
    rangePct: float = Field(0.25, gt=0, le=1.0)


class OptionBacktestIn(BaseModel):
    """``POST /options/backtest`` 请求体（与因子回测同形 + 可选标的）。"""

    market: str = Field("us", max_length=8)
    strategyId: str = Field("covered_call", max_length=32)
    symbol: str | None = Field(None, max_length=24, description="标的，缺省用该市场基准指数")
    start: str | None = Field(None, max_length=10)
    end: str | None = Field(None, max_length=10)
    benchmark: str | None = Field(None, max_length=16, description="占位，期权回测基准固定为买入持有")


def _market(market: str | None) -> str:
    m = (market or "us").strip().lower()
    if m not in MARKETS:
        raise HTTPException(status_code=400, detail=f"market 必须是 {MARKETS}，收到 {market!r}")
    return m


@router.get("/strategies")
def strategies() -> list[dict]:
    """期权策略清单：``[{id,name,desc,requiresStock,legsHint,aliases}]``。"""
    return strategies_payload()


@router.get("/spot/{symbol}")
def spot(symbol: str, market: str = Query("us")) -> dict:
    """标的现价（计算器基准价），走 provider 降级链，永不抛错。"""
    m = _market(market)
    info = quote_spot(symbol, m)
    if not info or not info.get("spot"):
        raise HTTPException(status_code=400, detail=f"无法取得 {symbol} 的现价（数据源不可用）")
    info["market"] = m
    return info


@router.get("/expiries/{symbol}")
def expiries(symbol: str, market: str = Query("us"), count: int = Query(8, ge=1, le=24)) -> dict:
    """可选到期日列表（按交易所日历规则推算）。"""
    m = _market(market)
    exps = list_expiries(m, count)
    info = quote_spot(symbol, m)
    return {
        "asOf": utc_now_iso(),
        "symbol": (symbol or "").upper(),
        "market": m,
        "expiries": exps,
        "spot": info.get("spot"),
        "source": "calendar:exchange-rule",
        "quoteSource": info.get("source"),
    }


@router.get("/chain/{symbol}")
def chain(symbol: str, market: str = Query("us"), expiry: str | None = Query(None, max_length=10)) -> dict:
    """期权链（模型推演报价），未给 expiry 时取最近一个到期日。"""
    m = _market(market)
    try:
        return build_chain(symbol, m, expiry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("chain failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"期权链暂不可用：{type(exc).__name__}: {exc}") from exc


@router.post("/payoff")
def payoff(body: PayoffIn) -> dict:
    """到期损益推演：``curve`` 为每股口径，``maxProfit``/``maxLoss``/``netPremium`` 为金额口径。

    ``maxProfit=null`` 表示理论无限；``maxLoss=null`` 表示理论无限亏损。
    """
    try:
        return compute_payoff(
            spot=float(body.spot),
            strategy=body.strategy,
            raw_legs=[l.model_dump() for l in body.legs],
            range_pct=float(body.rangePct),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backtest")
def backtest(body: OptionBacktestIn) -> dict:
    """期权策略月度滚动回测（权利金为模型价，响应 ``optionPricing`` 字段标注）。"""
    m = _market(body.market)
    sid = (body.strategyId or "covered_call").strip().lower()
    if sid not in OPTION_STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail=f"未知期权策略 strategyId={body.strategyId!r}，可选：{', '.join(OPTION_STRATEGIES)}",
        )
    symbol = (body.symbol or DEFAULT_UNDERLYING[m]).strip()
    try:
        return run_option_backtest(
            symbol=symbol, market=m, strategy_id=sid, start=body.start, end=body.end
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("option backtest failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"期权回测暂时不可用：{type(exc).__name__}: {exc}") from exc