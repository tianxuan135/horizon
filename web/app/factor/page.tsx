"use client";

import type { EChartsCoreOption } from "echarts";
import { useCallback, useEffect, useMemo, useState } from "react";
import { EChart, baseGrid, chartTheme, zoomX } from "@/components/echart";
import { ModuleHeader } from "@/components/module-header";
import { Card, Empty, ErrorBox, Loading, Segmented, Stat } from "@/components/ui";
import { apiSend, useApi } from "@/lib/api";
import { num, pct } from "@/lib/format";
import { useMarket } from "@/lib/market";
import type { BacktestResult, Benchmark, MinedFactor, Strategy } from "@/lib/types";

/**
 * 因子策略分析 = 因子策略（可视化回测）+ 因子挖取。
 * 回测指标口径：CAGR / 最大回撤 / 夏普（rf=0，√252 年化）/ 年化波动 / alpha / beta / 胜率。
 * 基准线：美股 标普500 / 道琼斯 / 纳指；A股 上证 / 沪深300 / 创业板指。
 */

const TABS = [
  { value: "strategy" as const, label: "因子策略" },
  { value: "mine" as const, label: "因子挖取" },
];

const RANGES = [
  { value: "1y", label: "近 1 年" },
  { value: "2y", label: "近 2 年" },
  { value: "3y", label: "近 3 年" },
];

function rangeToDates(r: string): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(end.getFullYear() - Number(r.replace("y", "")));
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { start: iso(start), end: iso(end) };
}

export default function FactorPage() {
  const { market, label } = useMarket();
  const [tab, setTab] = useState<"strategy" | "mine">("strategy");
  const [strategyId, setStrategyId] = useState<string>("");
  const [benchmark, setBenchmark] = useState<string>("");
  const [range, setRange] = useState("2y");
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const strategies = useApi<Strategy[]>("/factor/strategies", { market }, [market]);
  const benchmarks = useApi<Benchmark[]>("/factor/benchmarks", { market }, [market]);
  const mined = useApi<MinedFactor[]>("/factor/mine", { market, window: 252 }, [market]);

  useEffect(() => {
    if (strategies.data?.length && !strategies.data.some((s) => s.id === strategyId)) {
      setStrategyId(strategies.data[0].id);
    }
  }, [strategies.data, strategyId]);

  useEffect(() => {
    if (benchmarks.data?.length && !benchmarks.data.some((b) => b.id === benchmark)) {
      setBenchmark(benchmarks.data[0].id);
    }
  }, [benchmarks.data, benchmark]);

  const run = useCallback(async () => {
    if (!strategyId || !benchmark) return;
    setRunning(true);
    setErr(null);
    try {
      const { start, end } = rangeToDates(range);
      const res = await apiSend<BacktestResult>("POST", "/factor/backtest", { market, strategyId, benchmark, start, end });
      setResult(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "回测失败");
      setResult(null);
    } finally {
      setRunning(false);
    }
  }, [market, strategyId, benchmark, range]);

  const equity = result?.equity ?? [];

  const equityOption = useMemo<EChartsCoreOption>(() => {
    const dd = equity.map((r, i) => {
      const peak = Math.max(...equity.slice(0, i + 1).map((x) => x.nav));
      return peak > 0 ? (r.nav / peak - 1) * 100 : 0;
    });
    return {
      textStyle: chartTheme.textStyle,
      grid: [
        { left: 8, right: 14, top: 26, height: "52%", containLabel: true },
        { left: 8, right: 14, top: "70%", bottom: 8, containLabel: true },
      ],
      tooltip: { ...chartTheme.tooltip, trigger: "axis" },
      legend: { show: false },
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
    <div className="animate-fade-up">
      <ModuleHeader
        title="因子策略分析"
        asOf={result?.asOf ?? mined.data?.[0] ? result?.asOf : undefined}
        loading={running}
        right={<span className="pill bg-white/70 text-ink-mute shadow-[inset_0_0_0_1px_rgba(0,0,0,0.05)]">{label}</span>}
      />

      <div className="mb-5">
        <Segmented value={tab} options={TABS} onChange={setTab} ariaLabel="子功能" />
      </div>

      {tab === "strategy" ? (
        <div className="flex flex-col gap-5">
          <Card>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="因子策略">
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
              </Field>
              <Field label="基准线">
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
              </Field>
              <Field label="回测区间">
                <Segmented value={range} options={RANGES} onChange={setRange} size="sm" ariaLabel="回测区间" />
              </Field>
              <button
                type="button"
                onClick={() => void run()}
                disabled={running}
                className="ml-auto rounded-full bg-ink px-5 py-2.5 text-[13px] font-medium text-white transition-transform duration-300 ease-apple hover:scale-[1.02] disabled:opacity-50"
              >
                {running ? "回测中…" : "运行回测"}
              </button>
            </div>
            {strategies.data?.[0]?.desc ? (
              <p className="mt-3 text-[12px] text-ink-faint">
                当前策略：{(strategies.data ?? []).find((s) => s.id === strategyId)?.desc}
              </p>
            ) : null}
          </Card>

          {err ? <ErrorBox message={err} onRetry={() => void run()} /> : null}

          {result ? (
            <>
              <Card>
                <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
                  <Stat label="年化收益" value={pct(result.metrics.cagr)} tone={result.metrics.cagr >= 0 ? "accent" : "greed"} />
                  <Stat label="最大回撤" value={pct(result.metrics.mdd)} tone="greed" />
                  <Stat label="夏普比率" value={num(result.metrics.sharpe, 2)} />
                  <Stat label="年化波动" value={pct(result.metrics.vol)} />
                  <Stat label="Alpha" value={pct(result.metrics.alpha)} />
                  <Stat label="Beta" value={num(result.metrics.beta, 2)} />
                  <Stat label="胜率" value={pct(result.metrics.winRate)} />
                  <Stat label="基准" value={<span className="text-[18px]">{result.benchmark.name}</span>} />
                </div>
              </Card>

              <Card pad={false} className="p-5 sm:p-6">
                <div className="mb-1 flex items-center justify-between">
                  <h3 className="text-[15px] font-semibold tracking-tight text-ink">净值曲线 · 最大回撤</h3>
                  <span className="text-[12px] text-ink-faint">滚轮缩放</span>
                </div>
                <EChart option={equityOption} height={400} />
              </Card>
            </>
          ) : (
            <Card>
              <Empty>选择策略与基准线后点击「运行回测」</Empty>
            </Card>
          )}
        </div>
      ) : (
        <Card pad={false}>
          <div className="px-5 pt-5 sm:px-6">
            <h3 className="text-[15px] font-semibold tracking-tight text-ink">因子挖取</h3>
            <p className="mt-1 text-[12px] text-ink-faint">滚动 252 个交易日计算 Rank-IC / ICIR / t 值 / 换手率</p>
          </div>
          {mined.error ? (
            <div className="p-5">
              <ErrorBox message={mined.error} onRetry={mined.reload} />
            </div>
          ) : mined.loading && !mined.data ? (
            <Loading height={220} />
          ) : (
            <div className="mt-4 overflow-x-auto px-2 pb-3 sm:px-4">
              <table className="w-full min-w-[640px] border-collapse text-[13px]">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-[0.08em] text-ink-faint">
                    <th className="px-3 py-2 font-medium">因子</th>
                    <th className="px-3 py-2 text-right font-medium">IC</th>
                    <th className="px-3 py-2 text-right font-medium">ICIR</th>
                    <th className="px-3 py-2 text-right font-medium">t 值</th>
                    <th className="px-3 py-2 text-right font-medium">换手率</th>
                  </tr>
                </thead>
                <tbody>
                  {(mined.data ?? []).map((f) => (
                    <tr key={f.factor} className="border-t border-black/[0.05]">
                      <td className="px-3 py-2.5">
                        <div className="mono text-[12px] font-semibold text-ink">{f.factor}</div>
                        <div className="text-[11px] text-ink-faint">{f.desc}</div>
                      </td>
                      <td className="mono px-3 py-2.5 text-right" style={{ color: f.ic >= 0 ? "#0A84FF" : "#FF453A" }}>
                        {num(f.ic, 4)}
                      </td>
                      <td className="mono px-3 py-2.5 text-right">{num(f.icir, 2)}</td>
                      <td className="mono px-3 py-2.5 text-right">{num(f.tStat, 2)}</td>
                      <td className="mono px-3 py-2.5 text-right">{pct(f.turnover)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <p className="mt-5 text-[12px] leading-relaxed text-ink-faint">
        历史回测结果不代表未来表现，因子有效性会随市场结构变化而衰减。
      </p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="stat-label">{label}</span>
      {children}
    </label>
  );
}