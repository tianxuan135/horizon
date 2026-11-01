"""横截面因子回测与因子挖掘引擎（API_CONTRACT §5）。

数据
----
标的池 ``UNIVERSE`` 是内置的、公开可见的常用标的（仅用于研究演示，
不构成任何推荐）。全部收盘价由 ``app.providers.get_bars`` 的降级链提供，
响应里的 ``source`` 如实汇总实际命中的数据源（可能为 ``synthetic``）。

调仓与持仓
----------
- 每月最后一个交易日收盘计算因子，等权买入横截面得分最高的 ``topFrac``
  （默认 25%）标的，持有到下一个月末；
- 交易成本：按双边换手 ``turnover = 0.5*Σ|w_new - w_old|`` 计提
  ``feeBps``（默认 5bp），在调仓次日的组合收益里扣除；
- 全程不使用未来数据：调仓日 t 的因子只用 <= t 的收盘价，
  收益用 t+1 起的日收益。

因子定义全部见 ``strategies.FACTOR_DESC``，其中 ``value_proxy`` 依赖
``analytics/valuation.py`` 的代理 PE（非财报口径，已在该模块注明）。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np

from ..analytics.common import downsample, rnd, safe_div, spearman, utc_now_iso
from ..analytics.valuation import BUCKET_MAP, implied_multiples, price_stats
from ..cache import get as cache_get
from ..cache import set as cache_set
from ..providers import get_bars
from .metrics import performance_metrics
from .strategies import (
    FACTOR_DESC,
    FACTORS,
    STRATEGY_BY_ID,
    Strategy,
    benchmark_of,
)

TRADING_DAYS = 252

UNIVERSE: dict[str, tuple[str, ...]] = {
    "us": (
        "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META",
        "AMD", "AVGO", "XOM", "JPM", "KO", "PFE", "CAT",
    ),
    "cn": (
        "600519", "000858", "300750", "002594", "601318",
        "600036", "000001", "601899", "600276", "688981",
    ),
}


@dataclass
class Panel:
    """对齐后的收盘价面板：closes 形状 (T, N)，dates 长度 T，symbols 长度 N。"""

    dates: list[str]
    symbols: list[str]
    closes: np.ndarray
    sources: dict[str, str]

    @property
    def T(self) -> int:
        return len(self.dates)

    @property
    def N(self) -> int:
        return len(self.symbols)


def _needed_days(start: str | None) -> int:
    """估算需要多少根日线：从 start 到今天 + 300 根预热（因子需要 252 日历史）。"""
    today = date.today()
    s = today - timedelta(days=365 * 3)
    if start:
        try:
            s = date.fromisoformat(str(start)[:10])
        except ValueError:
            pass
    calendar = max(0, (today - s).days)
    return int(min(2600, max(420, calendar * TRADING_DAYS / 365 + 300)))


def build_panel(market: str = "us", start: str | None = None) -> Panel | None:
    """抓取并对齐标的池日线；样本不足时返回 None。结果进 TTL 缓存。"""
    key = f"bt:panel:{market}:{start or 'all'}"
    hit = cache_get(key)
    if hit:
        try:
            return Panel(
                dates=list(hit["dates"]),
                symbols=list(hit["symbols"]),
                closes=np.asarray(hit["closes"], dtype=float),
                sources=dict(hit["sources"]),
            )
        except (KeyError, TypeError):
            pass

    need = _needed_days(start)
    syms = UNIVERSE.get(market, UNIVERSE["us"])
    bars: dict[str, Any] = {}
    sources: dict[str, str] = {}

    # 并发抓取：单个标的首次取数约 1s（离线环境下 yahoo 会先超时再回落到合成），
    # 串行抓 14 个标的要 20s+，并发后冷启动约 2~3s。provider 层只做 HTTP/纯计算，
    # 结果写进各自 dict，不下单、不共享可变状态。
    def _fetch(sym: str) -> Any:
        try:
            return sym, get_bars(sym, market, need)
        except Exception:
            return sym, None

    with ThreadPoolExecutor(max_workers=min(8, len(syms))) as pool:
        for sym, bar in pool.map(_fetch, syms):
            if bar and len(bar) >= 60:
                bars[sym] = bar
                sources[sym] = bar.source

    if len(bars) < 4:
        return None

    common = sorted(set.intersection(*(set(b.dates) for b in bars.values())))
    if len(common) < 80:
        return None

    symbols = [s for s in syms if s in bars]
    idx_maps = {s: {d: i for i, d in enumerate(bars[s].dates)} for s in symbols}
    closes = np.asarray(
        [[float(bars[s].closes[idx_maps[s][d]]) for s in symbols] for d in common],
        dtype=float,
    )
    panel = Panel(dates=common, symbols=symbols, closes=closes, sources=sources)
    cache_set(
        key,
        {"dates": panel.dates, "symbols": panel.symbols,
         "closes": closes.tolist(), "sources": sources},
        900,
    )
    return panel


def _logret(seg: np.ndarray) -> np.ndarray:
    """单列的对数收益率（非正价格位置记 0）。"""
    prev, cur = seg[:-1], seg[1:]
    ok = (prev > 0) & (cur > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(ok, np.log(np.where(ok, cur, 1.0) / np.where(ok, prev, 1.0)), 0.0)
    return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)


def _simple_ret_matrix(px: np.ndarray) -> np.ndarray:
    """(T,N) 简单日收益矩阵，第 0 行为 0。"""
    r = np.zeros_like(px)
    prev, cur = px[:-1], px[1:]
    ok = prev > 0
    r[1:] = np.where(ok, cur / np.where(ok, prev, 1.0) - 1.0, 0.0)
    return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)


def _momentum(px: np.ndarray, i: int, lookback: int, skip: int = 21) -> np.ndarray | None:
    """(N,) 动量：px[i-skip] / px[i-lookback] - 1。历史不足返回 None。"""
    end = i - skip
    base = max(0, i - lookback)
    if end <= base:
        return None
    a = px[end]
    b = px[base]
    ok = b > 0
    return np.where(ok, a / np.where(ok, b, 1.0) - 1.0, 0.0)


def _realised_vol(px: np.ndarray, i: int, lookback: int = 60) -> np.ndarray | None:
    """(N,) 年化已实现波动率，取 [i-lookback, i] 的日对数收益。"""
    base = max(0, i - lookback)
    seg = px[base:i + 1]
    if seg.shape[0] < 12:
        return None
    r = np.stack([_logret(seg[:, j]) for j in range(seg.shape[1])], axis=1)  # (t-1, N)
    return np.std(r, axis=0, ddof=1) * math.sqrt(TRADING_DAYS)


def _value_proxy(px: np.ndarray, i: int, symbols: list[str]) -> np.ndarray | None:
    """(N,) 盈利收益率代理：1/pe_proxy，pe_proxy 由价格统计量推导。"""
    base = max(0, i - TRADING_DAYS)
    seg = px[base:i + 1]
    if seg.shape[0] < 60:
        return None
    out = np.zeros(seg.shape[1], dtype=float)
    for j in range(seg.shape[1]):
        st = price_stats(seg[:, j])
        bucket = BUCKET_MAP.get(symbols[j].upper(), "tech")
        pe = float(implied_multiples(st, bucket).get("pe") or 30.0)
        out[j] = safe_div(1.0, max(pe, 1e-6))
    return out


def factor_values(name: str, px: np.ndarray, i: int, symbols: list[str]) -> np.ndarray | None:
    """在调仓日索引 i 上计算单一因子的横截面值 (N,)，不可算时返回 None。"""
    if name == "mom_12_1":
        return _momentum(px, i, TRADING_DAYS)
    if name == "mom_6_1":
        return _momentum(px, i, 126)
    if name == "reversal_1m":
        m = _momentum(px, i, 21, skip=0)
        return -m if m is not None else None
    if name == "low_vol":
        v = _realised_vol(px, i, 60)
        return -v if v is not None else None
    if name == "value_proxy":
        return _value_proxy(px, i, symbols)
    if name == "quality":
        m = _momentum(px, i, TRADING_DAYS)
        v = _realised_vol(px, i, 120)
        if m is None or v is None:
            return None
        return np.where(v > 1e-6, m / np.where(v > 1e-6, v, 1.0), 0.0)
    return None


def _zscore(x: np.ndarray) -> np.ndarray:
    """横截面 z-score；标准差为 0 时返回全 0。"""
    mu = float(np.mean(x))
    sd = float(np.std(x, ddof=1)) if x.size > 1 else 0.0
    if sd <= 1e-12:
        return np.zeros_like(x)
    return (x - mu) / sd


def composite_score(strategy: Strategy, px: np.ndarray, i: int, symbols: list[str]) -> np.ndarray | None:
    """把策略的多个因子各自 z-score 后等权平均；全部不可算时返回 None。"""
    parts: list[np.ndarray] = []
    for f in strategy.factors:
        v = factor_values(f, px, i, symbols)
        if v is not None:
            parts.append(_zscore(v))
    if not parts:
        return None
    return np.mean(np.stack(parts, axis=0), axis=0)


def _month_end_indices(dates: list[str], lo: int, hi: int) -> list[int]:
    """[lo, hi] 区间内每个月最后一个交易日的索引。"""
    out: list[int] = []
    for i in range(max(0, lo), min(len(dates), hi + 1)):
        is_last = (i == len(dates) - 1) or dates[i][:7] != dates[i + 1][:7]
        if is_last:
            out.append(i)
    return out


def _bench_closes(panel: Panel, market: str, bench_symbol: str) -> np.ndarray | None:
    """把基准指数收盘价对齐到 panel 的交易日；缺失返回 None。"""
    try:
        bar = get_bars(bench_symbol, market, max(420, panel.T + 120))
    except Exception:
        return None
    if not bar or not bar.dates:
        return None
    m = {d: float(c) for d, c in zip(bar.dates, bar.closes)}
    if any(d not in m for d in panel.dates):
        # 用最近可得值前向填充，仍拿不到就放弃
        out = np.full(panel.T, np.nan)
        last = None
        for k, d in enumerate(panel.dates):
            if d in m:
                last = m[d]
            out[k] = last if last is not None else np.nan
        if np.isnan(out).all():
            return None
        first = float(out[~np.isnan(out)][0])
        out = np.where(np.isnan(out), first, out)
        return out
    return np.asarray([m[d] for d in panel.dates], dtype=float)


def run_backtest(
    *,
    market: str = "us",
    strategy_id: str = "momentum",
    start: str | None = None,
    end: str | None = None,
    benchmark_id: str | None = None,
    fee_bps: float = 5.0,
    top_frac: float = 0.25,
) -> dict:
    """执行一次横截面回测，返回契约 §5 的响应体。

    ``start``/``end`` 为 ISO 日期；服务端会额外抓取 start 之前 300 根日线
    作为因子预热，因此请求的区间不会被预热吃掉。
    """
    strat = STRATEGY_BY_ID.get(strategy_id)
    if strat is None:
        raise ValueError(
            f"未知策略 strategyId={strategy_id}，可选值：{', '.join(STRATEGY_BY_ID)}"
        )
    panel = build_panel(market, start)
    if panel is None:
        raise ValueError("标的池行情样本不足（<4 个标的或 <80 个共同交易日），无法回测")

    bench = benchmark_of(market, benchmark_id)
    i0 = 0
    if start:
        for k, d in enumerate(panel.dates):
            if d >= start:
                i0 = k
                break
    i1 = panel.T - 1
    if end:
        for k in range(panel.T - 1, -1, -1):
            if panel.dates[k] <= end:
                i1 = k
                break
    if i1 - i0 < 40:
        raise ValueError(f"回测区间过短（{i1 - i0} 个交易日），至少需要 40 个交易日")

    px = panel.closes
    ret = _simple_ret_matrix(px)
    # 因子预热：至少 252 根历史，且不能早于区间起点太多
    warm = min(TRADING_DAYS, max(60, i1 - i0))
    rebals = [i for i in _month_end_indices(panel.dates, i0 + warm, i1 - 1)]
    if not rebals:
        raise ValueError("区间内没有可用的调仓日（需要至少一个月）")

    k_top = max(1, int(round(panel.N * top_frac)))
    fee = max(0.0, float(fee_bps)) / 1e4

    W = np.zeros((panel.T, panel.N))
    cost = np.zeros(panel.T)
    prev_w = np.zeros(panel.N)
    used_rebals: list[int] = []
    period_rets: list[tuple[float, float]] = []
    bench_px = _bench_closes(panel, market, bench.symbol) if bench else None

    cur_w: np.ndarray | None = None
    reb_set = set(rebals)
    for j in range(panel.T):
        if j in reb_set:
            score = composite_score(strat, px, j, panel.symbols)
            if score is not None and np.isfinite(score).all():
                order = np.argsort(-score)
                w = np.zeros(panel.N)
                w[order[:k_top]] = 1.0 / k_top
                turnover = 0.5 * float(np.abs(w - prev_w).sum())
                cur_w = w
                prev_w = w
                used_rebals.append(j)
                if j + 1 < panel.T:
                    cost[j + 1] = fee * turnover
        if cur_w is not None:
            W[j] = cur_w

    if not used_rebals:
        raise ValueError("所有调仓日的因子都无法计算（历史长度不足 252 交易日）")

    d0 = used_rebals[0]
    port_ret: list[float] = []
    bench_ret: list[float] = []
    navs: list[float] = [1.0]
    bnavs: list[float] = [1.0]
    dates_out: list[str] = [panel.dates[d0]]
    for j in range(d0 + 1, i1 + 1):
        r = float(np.dot(W[j], ret[j])) - float(cost[j])
        port_ret.append(r)
        navs.append(navs[-1] * (1.0 + r))
        if bench_px is not None and bench_px[j - 1] > 0:
            br = float(bench_px[j] / bench_px[j - 1] - 1.0)
        else:
            br = 0.0
        bench_ret.append(br)
        bnavs.append(bnavs[-1] * (1.0 + br))
        dates_out.append(panel.dates[j])

    # 每个调仓周期的区间收益（用于 winRate：策略跑赢基准的周期占比）
    for a, b in zip(used_rebals, used_rebals[1:] + [i1]):
        if b <= a:
            continue
        sr = float(navs[b - d0] / navs[a - d0] - 1.0)
        if bench_px is not None and bench_px[a] > 0:
            br = float(bench_px[b] / bench_px[a] - 1.0)
        else:
            br = 0.0
        period_rets.append((sr, br))

    metrics = performance_metrics(
        nav=navs,
        bench_nav=bnavs,
        strat_ret=port_ret,
        bench_ret=bench_ret,
        period_returns=period_rets,
    )
    metrics["rebalances"] = len(used_rebals)
    metrics["universe"] = panel.N
    metrics["holdings"] = k_top
    metrics["feeBps"] = rnd(fee * 1e4, 2)
    metrics["avgTurnover"] = rnd(
        float(np.mean([abs(c) / fee for c in cost[cost > 0]])) if fee > 0 and (cost > 0).any() else 0.0,
        4,
    )

    equity = [
        {"t": dates_out[k], "nav": rnd(navs[k], 4), "bench": rnd(bnavs[k], 4)}
        for k in range(len(dates_out))
    ]
    srcs = sorted(set(panel.sources.values()))
    source = "+".join(srcs) if srcs else "synthetic"
    warnings = [
        "回测为横截面等权组合的**研究性**模拟，含交易成本假设，不代表未来收益，不构成投资建议",
        f"标的池为内置公开标的（{panel.N} 只），存在幸存者偏差与样本选择偏差",
    ]
    if "synthetic" in srcs:
        warnings.insert(0, "部分/全部行情来自内置合成代理数据（synthetic），结论仅用于离线演示")
    if bench_px is None:
        warnings.append(f"基准 {bench.symbol if bench else '?'} 行情不可用，beta/alpha/winRate 已按基准 0 处理")

    return {
        "asOf": utc_now_iso(),
        "market": market,
        "equity": downsample(equity, 600),
        "metrics": metrics,
        "benchmark": {"id": bench.id, "symbol": bench.symbol, "name": bench.name} if bench else None,
        "strategy": {"id": strat.id, "name": strat.name, "factors": list(strat.factors)},
        "start": dates_out[0],
        "end": dates_out[-1],
        "source": source,
        "sources": panel.sources,
        "warnings": warnings,
    }


def mine_factors(*, market: str = "us", window: int = 252, horizon: int = 21, top_frac: float = 0.25) -> list[dict]:
    """因子挖掘：逐调仓日计算 rank-IC / ICIR / t 值 / 换手率。

    方法（全部按因子独立计算，不是常数桩）::

        rankIC_t = spearman( factor_i,t , fwd_ret_i,t→t+21 )      # 横截面秩相关
        IC       = mean(rankIC_t)
        ICIR     = mean(rankIC_t) / std(rankIC_t)
        tStat    = ICIR * sqrt(期数)                              # IC 序列的 t 检验
        turnover = mean_t( 0.5 * Σ_i |w_i,t - w_i,t-1| )           # top 分位等权组合换手

    ``window`` 为参与统计的交易日数（前 252 日仅作因子预热）。
    """
    window = int(max(60, min(900, window)))
    panel = build_panel(market, None)
    if panel is None:
        raise ValueError("标的池行情样本不足，无法计算因子 IC")
    px = panel.closes
    if panel.T < 300:
        raise ValueError(f"可用历史仅 {panel.T} 个交易日，至少需要 300 个交易日")

    horizon = int(max(5, min(60, horizon)))
    lo = max(TRADING_DAYS, panel.T - window)
    hi = panel.T - horizon - 1
    rebals = _month_end_indices(panel.dates, lo, hi)
    if len(rebals) < 3:
        raise ValueError(f"区间内调仓日不足（{len(rebals)} 个），请增大 window")

    k_top = max(1, int(round(panel.N * top_frac)))
    rows: list[dict] = []
    for factor in FACTORS:
        ics: list[float] = []
        w_prev = np.zeros(panel.N)
        turnovers: list[float] = []
        for i in rebals:
            f = factor_values(factor, px, i, panel.symbols)
            if f is None:
                continue
            base, fwd_px = px[i], px[i + horizon]
            ok = (base > 0)
            fwd = np.where(ok, fwd_px / np.where(ok, base, 1.0) - 1.0, 0.0)
            ic = spearman(f, fwd)
            if ic is None:
                continue
            ics.append(float(ic))
            order = np.argsort(-f)
            w = np.zeros(panel.N)
            w[order[:k_top]] = 1.0 / k_top
            turnovers.append(0.5 * float(np.abs(w - w_prev).sum()))
            w_prev = w
        if len(ics) < 3:
            rows.append(
                {
                    "factor": factor, "ic": None, "icir": None, "tStat": None,
                    "turnover": None, "samples": len(ics),
                    "desc": FACTOR_DESC.get(factor, ""),
                    "note": "有效调仓日不足 3 个，无法统计",
                }
            )
            continue
        arr = np.asarray(ics, dtype=float)
        mean_ic = float(np.mean(arr))
        sd = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
        icir = safe_div(mean_ic, sd)
        tstat = icir * math.sqrt(arr.size)
        rows.append(
            {
                "factor": factor,
                "ic": rnd(mean_ic, 4),
                "icir": rnd(icir, 4),
                "tStat": rnd(tstat, 4),
                "turnover": rnd(float(np.mean(turnovers)) if turnovers else 0.0, 4),
                "samples": int(arr.size),
                "icStd": rnd(sd, 4),
                "icPosRatio": rnd(float(np.mean(arr > 0)), 4),
                "desc": FACTOR_DESC.get(factor, ""),
            }
        )

    rows.sort(key=lambda r: -abs(r["ic"] or 0.0))
    return rows