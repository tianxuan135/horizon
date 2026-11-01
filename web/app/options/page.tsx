"use client";

import type { EChartsCoreOption } from "echarts";
import clsx from "clsx";
import { useCallback, useEffect, useMemo, useState } from "react";
import { EChart, baseGrid, chartTheme, zoomX } from "@/components/echart";
import { ModuleHeader } from "@/components/module-header";
import { Card, Empty, ErrorBox, Loading, Segmented, Stat } from "@/components/ui";
import { apiSend, useApi } from "@/lib/api";
import { num, pct, signed } from "@/lib/format";
import { useMarket } from "@/lib/market";
import type { BacktestResult, Benchmark, OptionLeg, PayoffResult, WatchItem } from "@/lib/types";

/**
 * 期权策略分析 = 策略分析（可视化回测）+ 自选股期权策略计算器。
 * 计算器口径：权利金按每股报价，金额 = premium × qty × 100（1 张 = 100 股）；
 * 到期损益曲线由后端在 [spot×(1-rangePct), spot×(1+rangePct)] 上逐点求解。
 */

const TABS = [
  { value: "calc" as const, label: "期权策略计算器" },
  { value: "backtest" as const, label: "期权策略分析" },
];

const RANGES = [
  { value: "1y", label: "近 1 年" },
  { value: "2y", label: "近 2 年" },
  { value: "3y", label: "近 3 年" },
];

interface OptionStrategy {
  id: string;
  name: string;
  desc: string;
}

/** 预设模板：按现价生成初始腿，用户可继续微调行权价与权利金。 */
function preset(id: string, spot: number): OptionLeg[] {
  const atm = Math.round(spot);
  const step = Math.max(1, Math.round(spot * 0.05));
  const p = (k: number) => Math.max(0.01, Number((spot * 0.032 - Math.abs(k - spot) * 0.02).toFixed(2)));
  switch (id) {
    case "long_call":
      return [{ type: "call", side: "long", strike: atm, premium: p(atm), qty: 1 }];
    case "long_put":
      return [{ type: "put", side: "long", strike: atm, premium: p(atm), qty: 1 }];
    case "covered_call":
      return [{ type: "call", side: "short", strike: atm + step, premium: p(atm + step), qty: 1 }];
    case "protective_put":
      return [{ type: "put", side: "long", strike: atm - step, premium: p(atm - step), qty: 1 }];
    case "bull_call_spread":
      return [
        { type: "call", side: "long", strike: atm, premium: p(atm), qty: 1 },
        { type: "call", side: "short", strike: atm + step, premium: p(atm + step), qty: 1 },
      ];
    case "butterfly":
      return [
        { type: "call", side: "long", strike: atm - step, premium: p(atm - step), qty: 1 },
        { type: "call", side: "short", strike: atm, premium: p(atm), qty: 2 },
        { type: "call", side: "long", strike: atm + step, premium: p(atm + step), qty: 1 },
      ];
    case "straddle":
      return [
        { type: "call", side: "long", strike: atm, premium: p(atm), qty: 1 },
        { type: "put", side: "long", strike: atm, premium: p(atm), qty: 1 },
      ];
    case "strangle":
      return [
        { type: "call", side: "long", strike: atm + step, premium: p(atm + step), qty: 1 },
        { type: "put", side: "long", strike: atm - step, premium: p(atm - step), qty: 1 },
      ];
    case "collar":
      return [
        { type: "put", side: "long", strike: atm - step, premium: p(atm - step), qty: 1 },
        { type: "call", side: "short", strike: atm + step, premium: p(atm + step), qty: 1 },
      ];
    default:
      return [{ type: "call", side: "long", strike: atm, premium: p(atm), qty: 1 }];
  }
}

export default function OptionsPage() {
  const { market, label } = useMarket();
  const [tab, setTab] = useState<"calc" | "backtest">("calc");

  return (
    <div className="animate-fade-up">
      <ModuleHeader
        title="期权策略分析"
        loading={false}
        right={<span className="pill bg-white/70 text-ink-mute shadow-[inset_0_0_0_1px_rgba(0,0,0,0.05)]">{label}</span>}
      />
      <div className="mb-5">
        <Segmented value={tab} options={TABS} onChange={setTab} ariaLabel="子功能" />
      </div>
      {tab === "calc" ? <Calculator market={market} /> : <Backtest market={market} />}
      <p className="mt-5 text-[12px] leading-relaxed text-ink-faint">
        期权损益仅用于策略结构学习：不含保证金、手续费、提前行权与波动率变化的影响。
      </p>
    </div>
  );
}

/* ---------------------------------- 计算器 --------------------------------- */

function Calculator({ market }: { market: "us" | "cn" }) {
  const watch = useApi<{ items: WatchItem[] }>("/valuation/watchlist", { market }, [market]);
  const strategies = useApi<OptionStrategy[]>("/options/strategies");
  const [symbol, setSymbol] = useState<string>("");
  const [strategyId, setStrategyId] = useState("straddle");
  const [legs, setLegs] = useState<OptionLeg[]>([]);
  const [result, setResult] = useState<PayoffResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** 现价为前端展示用；实际计算以后端 quote 为准 */
  const [spotInput, setSpotInput] = useState<string>("");

  const items = watch.data?.items ?? [];
  const spot = useApi<{ spot: number; asOf: string; source: string }>(
    symbol ? `/options/spot/${encodeURIComponent(symbol)}` : null,
    { market },
    [symbol, market],
  );
  const liveSpot = spot.data?.spot ?? 0;

  useEffect(() => {
    if (!symbol && items.length) setSymbol(items[0].symbol);
  }, [items, symbol]);

  useEffect(() => {
    if (liveSpot > 0) {
      setSpotInput(String(Number(liveSpot.toFixed(2))));
      setLegs((prev) => (prev.length ? prev : preset(strategyId, liveSpot)));
      setResult(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveSpot]);

  const applyPreset = (id: string) => {
    setStrategyId(id);
    const base = Number(spotInput) || liveSpot;
    if (base > 0) setLegs(preset(id, base));
    setResult(null);
  };

  const patch = (i: number, key: keyof OptionLeg, value: string) => {
    setLegs((prev) =>
      prev.map((leg, idx) => {
        if (idx !== i) return leg;
        if (key === "type") return { ...leg, type: value as OptionLeg["type"] };
        if (key === "side") return { ...leg, side: value as OptionLeg["side"] };
        const n = Number(value);
        return { ...leg, [key]: Number.isFinite(n) ? n : 0 };
      }),
    );
    setResult(null);
  };

  const compute = async () => {
    const base = Number(spotInput) || liveSpot;
    if (!base) {
      setErr("请先选择标的并等待现价载入");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await apiSend<PayoffResult>("POST", "/options/payoff", {
        spot: base,
        strategy: strategyId,
        legs,
        rangePct: 0.25,
      });
      setResult(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "计算失败");
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  const option = useMemo<EChartsCoreOption>(() => {
    const curve = result?.curve ?? [];
    const base = Number(spotInput) || liveSpot;
    return {
      textStyle: chartTheme.textStyle,
      grid: baseGrid({ top: 24, bottom: 8 }),
      tooltip: {
        ...chartTheme.tooltip,
        trigger: "axis",
        valueFormatter: (v: unknown) => `$${Number(v).toFixed(2)}`,
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: curve.map((c) => Number(c.price.toFixed(1))),
        axisLine: chartTheme.axisLine,
        axisTick: { show: false },
        axisLabel: { ...chartTheme.axisLabel, hideOverlap: true },
      },
      yAxis: {
        type: "value",
        scale: true,
        splitLine: chartTheme.splitLine,
        axisLabel: { ...chartTheme.axisLabel, formatter: (v: number) => `$${v}` },
      },
      dataZoom: [...zoomX(0, 100)],
      series: [
        {
          name: "到期损益",
          type: "line",
          showSymbol: false,
          smooth: false,
          data: curve.map((c) => Number(c.pnl.toFixed(2))),
          lineStyle: { width: 2.2, color: "#0A84FF" },
          areaStyle: { color: "rgba(10,132,255,0.08)" },
          markLine: {
            silent: true,
            symbol: "none",
            label: { formatter: "盈亏平衡", fontSize: 10, color: "#8E8E93" },
            lineStyle: { type: "dashed", color: "rgba(0,0,0,0.3)", width: 1 },
            data: [{ yAxis: 0 }],
          },
          markPoint: {
            symbol: "pin",
            symbolSize: 34,
            label: { fontSize: 9, color: "#fff" },
            data: base > 0 ? [{ name: "现价", coord: [String(Number(base.toFixed(1))), 0], value: "现价" }] : [],
          },
        },
      ],
    };
  }, [result, spotInput, liveSpot]);

  return (
    <div className="grid items-stretch gap-5 lg:grid-cols-[380px_1fr]">
      <Card className="flex h-full flex-col gap-4">
        <div>
          <span className="stat-label">标的</span>
          <select
            value={symbol}
            onChange={(e) => {
              setSymbol(e.target.value);
              setResult(null);
            }}
            className="mt-1.5 w-full rounded-full border border-black/[0.07] bg-canvas-alt px-3.5 py-2 text-[13px] text-ink outline-none"
          >
            {items.length === 0 ? <option value="">（先在估值分析添加自选股）</option> : null}
            {items.map((it) => (
              <option key={it.id} value={it.symbol}>
                {it.symbol} · {it.name}
              </option>
            ))}
          </select>
          <p className="mt-1.5 text-[11px] text-ink-faint">
            {spot.loading
              ? "现价载入中…"
              : liveSpot > 0
                ? `现价 $${num(liveSpot, 2)} · 来源 ${spot.data?.source ?? "—"}`
                : "暂无现价，可手动填写"}
          </p>
        </div>

        <div>
          <span className="stat-label">当前股价（可修正）</span>
          <input
            value={spotInput}
            onChange={(e) => {
              setSpotInput(e.target.value);
              setResult(null);
            }}
            inputMode="decimal"
            className="mono mt-1.5 w-full rounded-full border border-black/[0.07] bg-canvas-alt px-3.5 py-2 text-[13px] text-ink outline-none"
          />
        </div>

        <div>
          <span className="stat-label">策略模板</span>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(strategies.data ?? []).map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => applyPreset(s.id)}
                className={clsx(
                  "rounded-full px-3 py-1.5 text-[12px] transition-colors duration-300",
                  strategyId === s.id ? "bg-ink text-white" : "bg-canvas-alt text-ink-soft hover:bg-black/[0.06]",
                )}
                title={s.desc}
              >
                {s.name}
              </button>
            ))}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between">
            <span className="stat-label">策略腿</span>
            <button
              type="button"
              onClick={() =>
                setLegs((prev) => [
                  ...prev,
                  { type: "call", side: "long", strike: Math.round(Number(spotInput) || liveSpot || 100), premium: 1, qty: 1 },
                ])
              }
              className="text-[12px] text-accent transition-opacity hover:opacity-70"
            >
              + 添加腿
            </button>
          </div>
          <div className="mt-2 flex flex-col gap-2">
            {legs.map((leg, i) => (
              <div key={i} className="rounded-2xl bg-canvas-alt/70 p-2.5">
                <div className="grid grid-cols-2 gap-2">
                  <select
                    value={leg.type}
                    onChange={(e) => patch(i, "type", e.target.value)}
                    className="rounded-lg border border-black/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none"
                  >
                    <option value="call">Call</option>
                    <option value="put">Put</option>
                  </select>
                  <select
                    value={leg.side}
                    onChange={(e) => patch(i, "side", e.target.value)}
                    className="rounded-lg border border-black/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none"
                  >
                    <option value="long">买入 Long</option>
                    <option value="short">卖出 Short</option>
                  </select>
                </div>
                <div className="mt-2 grid grid-cols-3 items-center gap-2">
                  <LegInput label="行权价" value={leg.strike} onChange={(v) => patch(i, "strike", v)} />
                  <LegInput label="权利金" value={leg.premium} onChange={(v) => patch(i, "premium", v)} step="0.01" />
                  <LegInput label="张数" value={leg.qty} onChange={(v) => patch(i, "qty", v)} step="1" />
                </div>
                {legs.length > 1 ? (
                  <button
                    type="button"
                    onClick={() => {
                      setLegs((prev) => prev.filter((_, idx) => idx !== i));
                      setResult(null);
                    }}
                    className="mt-2 text-[11px] text-ink-faint transition-colors hover:text-warn"
                  >
                    删除该腿
                  </button>
                ) : null}
              </div>
            ))}
            {legs.length === 0 ? <Empty>选择策略模板生成初始腿</Empty> : null}
          </div>
        </div>

        <button
          type="button"
          onClick={() => void compute()}
          disabled={busy || legs.length === 0}
          className="rounded-full bg-ink px-5 py-2.5 text-[13px] font-medium text-white transition-transform duration-300 ease-apple hover:scale-[1.02] disabled:opacity-50"
        >
          {busy ? "计算中…" : "计算最大收益 / 最大风险"}
        </button>
        {err ? <p className="text-[12px] text-warn">{err}</p> : null}
      </Card>

      <div className="flex h-full flex-col gap-5">
        {result ? (
          <Card>
            <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
              <Stat
                label="最大收益"
                value={result.maxProfit === null ? "理论无限" : `$${compactUsd(result.maxProfit)}`}
                tone="accent"
              />
              <Stat label="最大风险" value={`$${compactUsd(Math.abs(result.maxLoss))}`} tone="greed" />
              <Stat label="净权利金" value={`${result.netPremium > 0 ? "+" : "−"}$${compactUsd(Math.abs(result.netPremium))}`} />
              <Stat
                label="盈亏平衡"
                value={result.breakevens.length ? result.breakevens.map((b) => num(b, 2)).join(" / ") : "—"}
                tone="ink"
              />
            </div>
            <p className="mt-3 text-[11px] text-ink-faint">金额按 1 张 = 100 股折算（premium × qty × 100）</p>
          </Card>
        ) : null}

        <Card pad={false} className="flex flex-1 flex-col justify-center p-5 sm:p-6">
          <div className="mb-1 flex items-center justify-between">
            <h3 className="text-[15px] font-semibold tracking-tight text-ink">到期损益曲线</h3>
            <span className="text-[12px] text-ink-faint">滚轮缩放</span>
          </div>
          {result ? <EChart option={option} height={330} /> : <Empty>填写策略腿后点击计算</Empty>}
        </Card>
      </div>
    </div>
  );
}

function LegInput({
  label,
  value,
  onChange,
  step = "0.5",
}: {
  label: string;
  value: number;
  onChange: (v: string) => void;
  step?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-[0.06em] text-ink-faint">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode="decimal"
        step={step}
        type="number"
        className="mono w-full rounded-lg border border-black/[0.06] bg-white px-2 py-1.5 text-[12px] text-ink outline-none"
      />
    </label>
  );
}

function compactUsd(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}

/* --------------------------------- 回测分析 -------------------------------- */

function rangeToDates(r: string) {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(end.getFullYear() - Number(r.replace("y", "")));
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { start: iso(start), end: iso(end) };
}

function Backtest({ market }: { market: "us" | "cn" }) {
  const strategies = useApi<OptionStrategy[]>("/options/strategies");
  const benchmarks = useApi<Benchmark[]>("/factor/benchmarks", { market }, [market]);
  const [strategyId, setStrategyId] = useState("");
  const [benchmark, setBenchmark] = useState("");
  const [range, setRange] = useState("2y");
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (strategies.data?.length && !strategies.data.some((s) => s.id === strategyId)) setStrategyId(strategies.data[0].id);
  }, [strategies.data, strategyId]);

  useEffect(() => {
    if (benchmarks.data?.length && !benchmarks.data.some((b) => b.id === benchmark)) setBenchmark(benchmarks.data[0].id);
  }, [benchmarks.data, benchmark]);

  const run = useCallback(async () => {
    if (!strategyId || !benchmark) return;
    setRunning(true);
    setErr(null);
    try {
      const { start, end } = rangeToDates(range);
      const res = await apiSend<BacktestResult>("POST", "/options/backtest", {
        market,
        strategyId,
        benchmark,
        start,
        end,
      });
      setResult(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "回测失败");
      setResult(null);
    } finally {
      setRunning(false);
    }
  }, [market, strategyId, benchmark, range]);

  const equity = result?.equity ?? [];

  const option = useMemo<EChartsCoreOption>(() => {
    const dd = equity.map((r, i) => {
      const peak = Math.max(...equity.slice(0, i + 1).map((x) => x.nav));
      return peak > 0 ? (r.nav / peak - 1) * 100 : 0;
    });
    return {
      textStyle: chartTheme.textStyle,
      grid: [
        { left: 8, right: 14, top: 20, height: "54%", containLabel: true },
        { left: 8, right: 14, top: "72%", bottom: 8, containLabel: true },
      ],
      tooltip: { ...chartTheme.tooltip, trigger: "axis" },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      xAxis: [
        { type: "category", boundaryGap: false, data: equity.map((r) => r.t), gridIndex: 0, axisLine: chartTheme.axisLine, axisTick: { show: false }, axisLabel: { show: false } },
        { type: "category", boundaryGap: false, data: equity.map((r) => r.t), gridIndex: 1, axisLine: chartTheme.axisLine, axisTick: { show: false }, axisLabel: { ...chartTheme.axisLabel, hideOverlap: true } },
      ],
      yAxis: [
        { type: "value", scale: true, gridIndex: 0, splitLine: chartTheme.splitLine, axisLabel: chartTheme.axisLabel },
        { type: "value", gridIndex: 1, max: 0, splitLine: { show: false }, axisLabel: { ...chartTheme.axisLabel, formatter: "{value}%" } },
      ],
      dataZoom: [{ type: "inside", xAxisIndex: [0, 1], start: 0, end: 100, zoomOnMouseWheel: true }],
      series: [
        { name: "策略净值", type: "line", data: equity.map((r) => r.nav), smooth: 0.25, showSymbol: false, lineStyle: { width: 2.2, color: "#0A84FF" }, areaStyle: { color: "rgba(10,132,255,0.10)" } },
        { name: "基准", type: "line", data: equity.map((r) => r.bench), smooth: 0.25, showSymbol: false, lineStyle: { width: 1.3, color: "rgba(29,29,31,0.45)" } },
        { name: "回撤", type: "line", data: dd, xAxisIndex: 1, yAxisIndex: 1, smooth: 0.2, showSymbol: false, lineStyle: { width: 1.4, color: "#FF453A" }, areaStyle: { color: "rgba(255,69,58,0.12)" } },
      ],
    };
  }, [equity]);

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="stat-label">期权策略</span>
            <select
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
              className="w-[220px] rounded-full border border-black/[0.07] bg-canvas-alt px-3.5 py-2 text-[13px] text-ink outline-none"
            >
              {(strategies.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="stat-label">基准线</span>
            <select
              value={benchmark}
              onChange={(e) => setBenchmark(e.target.value)}
              className="w-[180px] rounded-full border border-black/[0.07] bg-canvas-alt px-3.5 py-2 text-[13px] text-ink outline-none"
            >
              {(benchmarks.data ?? []).map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="stat-label">回测区间</span>
            <Segmented value={range} options={RANGES} onChange={setRange} size="sm" ariaLabel="回测区间" />
          </label>
          <button
            type="button"
            onClick={() => void run()}
            disabled={running}
            className="ml-auto rounded-full bg-ink px-5 py-2.5 text-[13px] font-medium text-white transition-transform duration-300 ease-apple hover:scale-[1.02] disabled:opacity-50"
          >
            {running ? "回测中…" : "运行回测"}
          </button>
        </div>
      </Card>

      {err ? <ErrorBox message={err} onRetry={() => void run()} /> : null}

      {result ? (
        <>
          <Card>
            <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
              <Stat label="年化收益" value={signed(result.metrics.cagr)} tone={result.metrics.cagr >= 0 ? "accent" : "greed"} />
              <Stat label="最大回撤" value={pct(result.metrics.mdd)} tone="greed" />
              <Stat label="夏普比率" value={num(result.metrics.sharpe, 2)} />
              <Stat label="胜率" value={pct(result.metrics.winRate)} />
            </div>
          </Card>
          <Card pad={false} className="p-5 sm:p-6">
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-[15px] font-semibold tracking-tight text-ink">净值曲线 · 最大回撤</h3>
              <span className="text-[12px] text-ink-faint">滚轮缩放</span>
            </div>
            <EChart option={option} height={400} />
          </Card>
        </>
      ) : (
        <Card>{running ? <Loading height={200} label="回测中" /> : <Empty>选择策略与基准线后运行回测</Empty>}</Card>
      )}
    </div>
  );
}