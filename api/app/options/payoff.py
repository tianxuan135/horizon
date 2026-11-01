"""到期损益（payoff）计算器（API_CONTRACT §6 POST /payoff）。

口径约定（前后端必须一致，写在这里作为唯一事实源）
==================================================
1. ``premium`` 是**每股权利金**（如 4.20 表示每股 4.20 美元）。
2. 一张合约 = ``MULTIPLIER`` = **100 股**；``qty`` 为合约张数，默认 1。
3. 金额口径（美元）::

       pnl_total(S) = Σ_option  sign * qty * 100 * (内在价值(S) - premium)
                    + Σ_stock   sign * shares * (S - basis)

       sign = +1 (long) / -1 (short)
       内在价值: call -> max(S-K, 0)，put -> max(K-S, 0)

   ``netPremium = -Σ_option sign * qty * 100 * premium``
   → **负值 = 净支出（买入期权付钱）**，正值 = 净收取。契约示例
   （single long call @4.2）给出 ``netPremium=-420``，与此一致（`-420` 表示付出 420）。
4. ``curve[].pnl`` 是**每股**口径（= pnl_total / 100），与契约示例
   （premium 4.2 → price 180 处 pnl -4.2）一致；同时给出 ``pnlTotal``
   金额字段，前端**不要**再乘 100。``curveUnit="perShare"``。
5. ``maxProfit`` / ``maxLoss`` 是**金额**口径。``maxProfit=null`` 表示理论无限；
   ``maxLoss=null`` 表示理论无限亏损（如裸卖看涨），此时 ``lossUnbounded=true``。
   ``maxLoss`` 以**正数**表示亏损金额（契约示例 420.0），纯收权利金无下行风险时为 0。
6. 全部为**到期日**损益，不含到期前平仓的时间价值变化。
7. 股票腿（``type="stock"``）的 ``qty`` 单位是**股**（1 张备兑合约对应 100 股），
   ``basis`` 为持仓成本，缺省用请求里的 ``spot``。

合规：本模块只做损益推演，不接券商、不下单、不构成投资建议。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from ..analytics.common import rnd, utc_now_iso

MULTIPLIER = 100          # 每张合约的股数
MIN_POINTS = 241          # 损益曲线的点数下限（>=240）
MAX_RANGE_PCT = 1.0

SOURCE = "computed:expiry-payoff"

# 策略清单：id / 中文名 / 描述 / 旧别名。前端 GET /options/strategies 直接用这份。
STRATEGY_CATALOG: tuple[dict, ...] = (
    {
        "id": "long_call",
        "name": "单腿看涨",
        "aliases": ["single", "call"],
        "desc": "买入 1 张看涨期权并支付权利金。最大亏损=已付权利金；上行盈利理论无限。",
    },
    {
        "id": "long_put",
        "name": "单腿看跌",
        "aliases": ["put"],
        "desc": "买入 1 张看跌期权并支付权利金。最大亏损=已付权利金；最大盈利=行权价×100−权利金。",
    },
    {
        "id": "covered_call",
        "name": "备兑看涨",
        "aliases": [],
        "desc": "持有 100 股正股 + 卖出 1 张看涨收取权利金。上行收益被封顶，下行仍有股价风险。",
    },
    {
        "id": "protective_put",
        "name": "保护性看跌",
        "aliases": ["married_put"],
        "desc": "持有 100 股正股 + 买入 1 张看跌作为保险。最大亏损被行权价封住，需支付保险费。",
    },
    {
        "id": "bull_call_spread",
        "name": "牛市看涨价差",
        "aliases": [],
        "desc": "买入低行权价看涨 + 卖出高行权价看涨，净支出较低，盈利与亏损都被封顶。",
    },
    {
        "id": "butterfly",
        "name": "蝶式价差",
        "aliases": [],
        "desc": "1-2-1 等距三段看涨（或看跌）。押注到期价停留在中间行权价附近，亏损有限（净支出），收益封顶。",
    },
    {
        "id": "straddle",
        "name": "跨式",
        "aliases": [],
        "desc": "同一行权价同时买入看涨与看跌。押注大幅波动，双侧都可能盈利，最大亏损=净支出。",
    },
    {
        "id": "strangle",
        "name": "宽跨式",
        "aliases": [],
        "desc": "买入虚值看跌 + 买入虚值看涨，成本低于跨式，但需要更大波动才盈利。",
    },
    {
        "id": "collar",
        "name": "领口",
        "aliases": ["collar_default"],
        "desc": "持股 + 买入看跌保护 + 卖出看涨融资，把收益与亏损同时压缩到一个区间内。",
    },
)

STRATEGY_IDS: tuple[str, ...] = tuple(s["id"] for s in STRATEGY_CATALOG) + ("single",)

_ALIAS: dict[str, str] = {}
for _s in STRATEGY_CATALOG:
    _ALIAS[_s["id"]] = _s["id"]
    for _a in _s["aliases"]:
        _ALIAS[_a] = _s["id"]

_BY_ID: dict[str, dict] = {s["id"]: s for s in STRATEGY_CATALOG}

# 需要正股敞口的策略（未显式给 stock 腿时自动补 100 股/张）
_STOCK_STRATEGIES = {"covered_call", "protective_put", "collar"}


@dataclass
class Leg:
    """一条腿。``type``: call|put|stock；``side``: long|short。"""

    type: str
    side: str
    strike: float = 0.0
    premium: float = 0.0
    qty: float = 1.0
    basis: float | None = None

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1

    def as_dict(self) -> dict:
        out = {
            "type": self.type,
            "side": self.side,
            "qty": self.qty,
        }
        if self.type != "stock":
            out["strike"] = rnd(self.strike, 4)
            out["premium"] = rnd(self.premium, 4)
            # 该腿权利金金额：正 = 买入支付现金，负 = 卖出收取现金
            out["premiumTotal"] = rnd(self.sign * self.qty * MULTIPLIER * self.premium, 2)
        else:
            out["basis"] = rnd(self.basis, 4)
            out["shares"] = self.qty
        return out


def canonical_strategy(strategy_id: str | None) -> str:
    """把 id/别名归一；未知 id 抛 ValueError（路由层转 400）。"""
    sid = (strategy_id or "").strip().lower()
    if not sid:
        return "single"
    canon = _ALIAS.get(sid)
    if canon is None:
        raise ValueError(
            f"未知期权策略 strategy={strategy_id}，可选：{', '.join(STRATEGY_IDS)}"
        )
    return canon


def strategies_payload() -> list[dict]:
    """``GET /options/strategies`` 的响应体（契约：直接返回数组）。"""
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "desc": s["desc"],
            "aliases": list(s["aliases"]),
            "requiresStock": s["id"] in _STOCK_STRATEGIES,
            "legsHint": _legs_hint(s["id"]),
        }
        for s in STRATEGY_CATALOG
    ]


def _legs_hint(sid: str) -> str:
    return {
        "long_call": "1 腿：long call",
        "long_put": "1 腿：long put",
        "covered_call": "2 腿：long 100 股 + short call",
        "protective_put": "2 腿：long 100 股 + long put",
        "bull_call_spread": "2 腿：long 低行权 call + short 高行权 call",
        "butterfly": "4 腿：long K1 / short 2×K2 / long K3（等距）",
        "straddle": "2 腿：long call + long put（同行权价）",
        "strangle": "2 腿：long put 低行权 + long call 高行权",
        "collar": "3 腿：long 100 股 + long put + short call",
    }.get(sid, "")


def parse_legs(raw: Sequence[dict] | None) -> list[Leg]:
    """把请求里的 legs 转成 Leg 列表，做严格的基础校验。

    非法输入抛 ``ValueError``（路由层统一转 400 并回显原因）。
    """
    if not raw:
        raise ValueError("legs 不能为空：至少需要一条期权腿")
    if len(raw) > 12:
        raise ValueError("legs 最多 12 条（防止误传整条期权链）")
    out: list[Leg] = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"legs[{i}] 必须是对象")
        typ = str(item.get("type", "")).strip().lower()
        if typ not in ("call", "put", "stock"):
            raise ValueError(f"legs[{i}].type 必须是 call/put/stock，收到 {item.get('type')!r}")
        side = str(item.get("side", "")).strip().lower()
        if side not in ("long", "short"):
            raise ValueError(f"legs[{i}].side 必须是 long/short，收到 {item.get('side')!r}")
        try:
            qty = float(item.get("qty", 1) or 1)
        except (TypeError, ValueError):
            raise ValueError(f"legs[{i}].qty 必须是数字") from None
        if qty <= 0:
            raise ValueError(f"legs[{i}].qty 必须 > 0")
        if typ == "stock":
            basis = item.get("basis")
            try:
                basis_f = float(basis) if basis is not None else None
            except (TypeError, ValueError):
                raise ValueError(f"legs[{i}].basis 必须是数字") from None
            if basis_f is not None and basis_f <= 0:
                raise ValueError(f"legs[{i}].basis 必须 > 0")
            out.append(Leg(type="stock", side=side, qty=qty, basis=basis_f))
            continue
        try:
            strike = float(item.get("strike"))
        except (TypeError, ValueError):
            raise ValueError(f"legs[{i}].strike 必须是数字") from None
        if strike <= 0:
            raise ValueError(f"legs[{i}].strike 必须 > 0")
        try:
            premium = float(item.get("premium", 0.0))
        except (TypeError, ValueError):
            raise ValueError(f"legs[{i}].premium 必须是数字") from None
        if premium < 0:
            raise ValueError(f"legs[{i}].premium 不能为负（权利金是每股非负金额）")
        out.append(Leg(type=typ, side=side, strike=strike, premium=premium, qty=qty))
    return out


def inject_stock_leg(legs: list[Leg], sid: str, spot: float) -> tuple[list[Leg], list[str]]:
    """需要正股敞口的策略若没给 stock 腿，自动补 100 股/张，并给出说明。"""
    if sid not in _STOCK_STRATEGIES:
        return legs, []
    if any(l.type == "stock" for l in legs):
        return legs, []
    contracts = sum(l.qty for l in legs if l.type != "stock" and l.side == "short") or 1.0
    shares = MULTIPLIER * contracts
    note = (
        f"策略 {sid} 需要正股敞口：已按 {shares:g} 股（{contracts:g} 张合约）"
        f"、成本基准 = 现价 {spot:g} 自动补 stock 腿"
    )
    return legs + [Leg(type="stock", side="long", qty=shares, basis=spot)], [note]


def structure_warnings(legs: list[Leg], sid: str) -> list[str]:
    """结构一致性提示（不阻断计算，只提示，避免前端自定义腿被误拒）。"""
    opts = [l for l in legs if l.type != "stock"]
    w: list[str] = []
    if sid in ("long_call", "long_put", "single") and len(opts) != 1:
        w.append(f"策略 {sid} 通常只有 1 条期权腿，本次收到 {len(opts)} 条（按传入腿计算）")
    if sid == "butterfly":
        calls = [l for l in opts if l.type == "call"]
        if len(calls) != 4:
            w.append(f"标准蝶式为 4 条看涨腿（1-2-1），本次收到 {len(calls)} 条看涨腿")
        else:
            k = sorted({l.strike for l in calls})
            if len(k) == 3 and abs((k[1] - k[0]) - (k[2] - k[1])) > 1e-6:
                w.append("蝶式三条行权价不等距，收益/风险不再对称")
    if sid == "straddle":
        strikes = {l.strike for l in opts}
        if len(strikes) > 1:
            w.append("跨式要求同一行权价，本次行权价不一致（等价于宽跨式）")
    if sid == "strangle" and len({l.strike for l in opts}) < 2:
        w.append("宽跨式应对看涨/看跌使用不同行权价，本次相同（等价于跨式）")
    if sid == "bull_call_spread" and len(opts) != 2:
        w.append(f"牛市价差应为 2 条看涨腿，本次收到 {len(opts)} 条")
    if sid == "collar" and not any(l.type == "put" and l.side == "long" for l in opts):
        w.append("领口通常包含 1 条买入看跌作为保护，本次未检测到")
    return w


def _intrinsic(leg: Leg, prices: np.ndarray) -> np.ndarray:
    if leg.type == "call":
        return np.maximum(prices - leg.strike, 0.0)
    return np.maximum(leg.strike - prices, 0.0)


def pnl_total(legs: Sequence[Leg], prices: np.ndarray, default_basis: float) -> np.ndarray:
    """金额口径到期损益（美元），见模块 docstring 公式 3。"""
    p = np.asarray(prices, dtype=float)
    total = np.zeros_like(p)
    for leg in legs:
        if leg.type == "stock":
            basis = leg.basis if leg.basis is not None else default_basis
            total += leg.sign * leg.qty * (p - basis)
        else:
            total += leg.sign * leg.qty * MULTIPLIER * (_intrinsic(leg, p) - leg.premium)
    return total


def net_premium(legs: Sequence[Leg]) -> float:
    """净权利金（金额口径）：**负 = 净支出**，正 = 净收取。

    与契约示例对齐：single long call @4.2 → ``-420.0``（付出 420 美元）。
    """
    total = 0.0
    for leg in legs:
        if leg.type != "stock":
            total += leg.sign * leg.qty * MULTIPLIER * leg.premium
    return -total


def _grid(spot: float, range_pct: float, legs: Sequence[Leg]) -> np.ndarray:
    """损益网格：spot*(1±rangePct) 上等距 MIN_POINTS 点，并入落在区间内的行权价。"""
    lo = max(0.01, spot * (1.0 - range_pct))
    hi = spot * (1.0 + range_pct)
    base = np.linspace(lo, hi, MIN_POINTS)
    strikes = [l.strike for l in legs if l.type != "stock" and lo < l.strike < hi]
    if strikes:
        base = np.unique(np.concatenate([base, np.asarray(strikes, dtype=float)]))
    return base


def _breakevens(prices: np.ndarray, pnl: np.ndarray) -> list[float]:
    """线性插值求零交叉点（盈亏平衡价），去重后升序返回。"""
    out: list[float] = []
    for i in range(len(pnl) - 1):
        a, b = pnl[i], pnl[i + 1]
        if a == 0:
            out.append(float(prices[i]))
        if a * b < 0:
            x0, x1 = prices[i], prices[i + 1]
            t = abs(a) / (abs(a) + abs(b))
            out.append(float(x0 + (x1 - x0) * t))
    if len(pnl) and pnl[-1] == 0:
        out.append(float(prices[-1]))
    dedup: list[float] = []
    for x in sorted(out):
        if not dedup or abs(x - dedup[-1]) > 1e-4:
            dedup.append(x)
    return [rnd(x, 2) or 0.0 for x in dedup]


def compute_payoff(
    *,
    spot: float,
    strategy: str | None,
    raw_legs: Sequence[dict] | None,
    range_pct: float = 0.25,
    strict: bool = False,
) -> dict:
    """主入口：返回契约 §6 ``/payoff`` 的响应体。"""
    if spot is None or float(spot) <= 0:
        raise ValueError("spot 必须为正数（标的最新价）")
    spot = float(spot)
    if not (0.01 <= float(range_pct) <= MAX_RANGE_PCT):
        raise ValueError(f"rangePct 必须在 0.01~{MAX_RANGE_PCT} 之间，收到 {range_pct}")
    range_pct = float(range_pct)

    sid = canonical_strategy(strategy)
    legs = parse_legs(raw_legs)

    warnings = structure_warnings(legs, sid)
    if strict and warnings:
        raise ValueError("；".join(warnings))
    legs, inject_notes = inject_stock_leg(legs, sid, spot)
    warnings = inject_notes + warnings

    prices = _grid(spot, range_pct, legs)
    totals = pnl_total(legs, prices, spot)
    per_share = totals / MULTIPLIER

    # 下界 S=0 的精确值（股票/看跌腿在 S→0 处的极值，网格起点拿不到）
    zero_pnl = float(pnl_total(legs, np.asarray([0.0]), spot)[0])
    lo_pnl = min(float(totals.min()), zero_pnl)

    # 上界斜率判断是否理论无限
    slope_up = float(totals[-1] - totals[-2]) if len(totals) > 1 else 0.0
    eps = 1e-9 * max(1.0, abs(float(totals[-1])) + 1.0)
    profit_unbounded = slope_up > eps
    loss_unbounded = slope_up < -eps

    max_profit = None if profit_unbounded else rnd(float(totals.max()), 2)
    if loss_unbounded:
        max_loss = None
    else:
        max_loss = rnd(abs(min(0.0, lo_pnl)), 2)

    breakevens = _breakevens(prices, totals)
    np_amt = rnd(net_premium(legs), 2)

    curve = [
        {"price": rnd(float(prices[i]), 2), "pnl": rnd(float(per_share[i]), 4),
         "pnlTotal": rnd(float(totals[i]), 2)}
        for i in range(len(prices))
    ]

    warnings.append("损益为**到期日**口径，不含到期前平仓的时间价值变化")
    warnings.append("模型推演结果仅供研究参考，不构成投资建议；本工具不提供任何下单能力")

    meta = _BY_ID.get(sid, {})
    return {
        "asOf": utc_now_iso(),
        "strategy": sid,
        "strategyName": meta.get("name", sid),
        "spot": rnd(spot, 4),
        "rangePct": range_pct,
        "multiplier": MULTIPLIER,
        "curveUnit": "perShare",
        "curve": curve,
        "maxProfit": max_profit,
        "maxLoss": max_loss,
        "profitUnbounded": profit_unbounded,
        "lossUnbounded": loss_unbounded,
        "breakevens": breakevens,
        "netPremium": np_amt,
        "pnlAtSpot": rnd(float(pnl_total(legs, np.asarray([spot]), spot)[0]), 2),
        "legs": [l.as_dict() for l in legs],
        "summary": _summary(spot, np_amt, max_profit, max_loss, breakevens, profit_unbounded, loss_unbounded),
        "source": SOURCE,
        "warnings": warnings,
    }


def _summary(
    spot: float,
    net_premium_amt: float | None,
    max_profit: float | None,
    max_loss: float | None,
    breakevens: list[float],
    profit_unbounded: bool,
    loss_unbounded: bool,
) -> str:
    """一句人话摘要（前端 tooltip 用）。合规：不使用任何"保证/稳赚"表述。"""
    cash = "净支出" if (net_premium_amt or 0) < 0 else "净收取"
    parts = [f"现价 {spot:g}", f"{cash} {abs(net_premium_amt or 0):.0f} 美元"]
    parts.append("最大盈利 理论无限" if profit_unbounded else f"最大盈利 {max_profit:.0f} 美元")
    parts.append("最大亏损 理论无限" if loss_unbounded else f"最大亏损 {max_loss:.0f} 美元")
    if breakevens:
        parts.append("盈亏平衡 " + " / ".join(f"{b:g}" for b in breakevens))
    return "，".join(parts) + "（到期口径）"
