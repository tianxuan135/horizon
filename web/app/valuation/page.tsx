"use client";

import type { EChartsCoreOption } from "echarts";
import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useState } from "react";
import { EChart, baseGrid, chartTheme, zoomX } from "@/components/echart";
import { ModuleHeader } from "@/components/module-header";
import { Card, Empty, ErrorBox, Loading } from "@/components/ui";
import { apiGet, apiSend, useApi } from "@/lib/api";
import { compactCap, num, pct } from "@/lib/format";
import { useMarket } from "@/lib/market";
import type { SearchHit, ValuationScore, WatchItem } from "@/lib/types";

/**
 * 估值分析。
 * 维度（评分口径由后端计算）：基本面 / 护城河 / 可替代性 / 资本开支。
 * 自选股：真实全市场检索 → 写入数据库 → 支持排序与删除。
 */

const BUCKETS: { key: WatchItem["bucket"]; label: string }[] = [
  { key: "consumer", label: "消费股" },
  { key: "cyclical", label: "周期股" },
  { key: "tech", label: "科技股" },
];

const DIMS: { key: keyof ValuationScore["dimensions"]; label: string; hint: string }[] = [
  { key: "fundamental", label: "基本面", hint: "盈利质量与增长" },
  { key: "moat", label: "护城河", hint: "定价权与壁垒" },
  { key: "substitutability", label: "可替代性", hint: "越低越好" },
  { key: "capex", label: "资本开支", hint: "投入强度" },
];

export default function ValuationPage() {
  const { market, label } = useMarket();
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const list = useApi<{ items: WatchItem[] }>("/valuation/watchlist", { market }, [market]);
  const items = list.data?.items ?? [];

  useEffect(() => {
    if (!selected && items.length) setSelected(items[0].symbol);
    if (selected && items.length && !items.some((i) => i.symbol === selected)) {
      setSelected(items[0]?.symbol ?? null);
    }
  }, [items, selected]);

  const score = useApi<ValuationScore>(selected ? `/valuation/score/${encodeURIComponent(selected)}` : null, { market }, [selected, market]);

  // 搜索防抖
  useEffect(() => {
    if (!query.trim()) {
      setHits([]);
      return;
    }
    const t = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await apiGet<{ results: SearchHit[] }>("/valuation/search", { q: query.trim(), market });
        setHits(res.results ?? []);
      } catch {
        setHits([]);
      } finally {
        setSearching(false);
      }
    }, 280);
    return () => clearTimeout(t);
  }, [query, market]);

  const add = useCallback(
    async (hit: SearchHit) => {
      setBusy(true);
      setNotice(null);
      try {
        await apiSend("POST", "/valuation/watchlist", { symbol: hit.symbol, market });
        setQuery("");
        setHits([]);
        await list.reload();
        setSelected(hit.symbol);
      } catch (e) {
        setNotice(e instanceof Error ? e.message : "添加失败");
      } finally {
        setBusy(false);
      }
    },
    [market, list],
  );

  const remove = useCallback(
    async (id: string) => {
      await apiSend("DELETE", `/valuation/watchlist/${id}`);
      await list.reload();
    },
    [list],
  );

  const move = useCallback(
    async (idx: number, dir: -1 | 1) => {
      const next = [...items];
      const target = idx + dir;
      if (target < 0 || target >= next.length) return;
      [next[idx], next[target]] = [next[target], next[idx]];
      await apiSend("POST", "/valuation/watchlist/reorder", { ids: next.map((i) => i.id) });
      await list.reload();
    },
    [items, list],
  );

  const peOption = useMemo<EChartsCoreOption>(() => {
    const rows = score.data?.series ?? [];
    return {
      textStyle: chartTheme.textStyle,
      grid: baseGrid({ top: 16, bottom: 6 }),
      tooltip: { ...chartTheme.tooltip, trigger: "axis" },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: rows.map((r) => r.t),
        axisLine: chartTheme.axisLine,
        axisTick: { show: false },
        axisLabel: { ...chartTheme.axisLabel, hideOverlap: true },
      },
      yAxis: { type: "value", scale: true, splitLine: chartTheme.splitLine, axisLabel: chartTheme.axisLabel },
      dataZoom: [...zoomX(30, 100)],
      series: [
        {
          type: "line",
          smooth: 0.3,
          showSymbol: false,
          data: rows.map((r) => r.pe),
          lineStyle: { width: 2, color: "#0A84FF" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(10,132,255,0.18)" },
                { offset: 1, color: "rgba(10,132,255,0)" },
              ],
            },
          },
        },
      ],
    };
  }, [score.data]);

  return (
    <div className="animate-fade-up">
      <ModuleHeader
        title="估值分析"
        asOf={score.data?.asOf ?? list.data ? score.data?.asOf : undefined}
        loading={score.loading || list.loading}
        right={<span className="pill bg-white/70 text-ink-mute shadow-[inset_0_0_0_1px_rgba(0,0,0,0.05)]">{label}</span>}
      />

      <div className="grid items-stretch gap-5 lg:grid-cols-[340px_1fr]">
        {/* 自选股 */}
        <Card pad={false} className="flex h-full flex-col">
          <div className="px-5 pt-5">
            <h2 className="text-[15px] font-semibold tracking-tight text-ink">自选股</h2>
            <div className="relative mt-3">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索代码或名称，如 AAPL / 茅台"
                className="w-full rounded-full border border-black/[0.07] bg-canvas-alt px-4 py-2.5 text-[13px] text-ink outline-none transition-shadow duration-300 placeholder:text-ink-faint focus:shadow-[0_0_0_3px_rgba(10,132,255,0.14)]"
              />
              <AnimatePresence>
                {(hits.length > 0 || (searching && query)) && (
                  <motion.div
                    initial={{ opacity: 0, y: -6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    className="absolute left-0 right-0 top-[46px] z-20 max-h-64 overflow-auto rounded-2xl border border-black/[0.06] bg-white p-1.5 shadow-card"
                  >
                    {searching && hits.length === 0 ? (
                      <p className="px-3 py-2 text-[12px] text-ink-faint">检索中…</p>
                    ) : (
                      hits.map((h) => (
                        <button
                          key={`${h.market}-${h.symbol}`}
                          type="button"
                          disabled={busy}
                          onClick={() => void add(h)}
                          className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left transition-colors hover:bg-canvas-alt"
                        >
                          <span className="flex items-center gap-2">
                            <span className="mono text-[12px] font-semibold text-ink">{h.symbol}</span>
                            <span className="text-[12px] text-ink-mute">{h.name}</span>
                          </span>
                          <span className="text-[11px] text-ink-faint">{h.exchange}</span>
                        </button>
                      ))
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
            {notice ? <p className="mt-2 text-[12px] text-warn">{notice}</p> : null}
          </div>

          <div className="mt-3 flex flex-col gap-1 px-3 pb-4">
            {list.error ? <ErrorBox message={list.error} onRetry={list.reload} /> : null}
            {list.loading && !list.data ? <Loading height={140} label="载入自选股" /> : null}
            {!list.loading && items.length === 0 ? (
              <div className="px-2 py-4">
                <Empty>暂无自选股，搜索后添加即可开始估值分析</Empty>
              </div>
            ) : null}
            {items.map((it, idx) => (
              <div
                key={it.id}
                className={clsx(
                  "group flex items-center gap-2 rounded-2xl px-3 py-2.5 transition-colors duration-300",
                  selected === it.symbol ? "bg-canvas-alt" : "hover:bg-canvas-alt/70",
                )}
              >
                <button type="button" onClick={() => setSelected(it.symbol)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                  <span className="mono text-[12px] font-semibold text-ink">{it.symbol}</span>
                  <span className="truncate text-[12px] text-ink-mute">{it.name}</span>
                </button>
                <div className="flex items-center gap-0.5 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
                  <IconBtn label="上移" onClick={() => void move(idx, -1)}>↑</IconBtn>
                  <IconBtn label="下移" onClick={() => void move(idx, 1)}>↓</IconBtn>
                  <IconBtn label="删除" onClick={() => void remove(it.id)}>×</IconBtn>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-auto px-5 pb-4 pt-2 text-[11.5px] text-ink-faint">
            共 {items.length} 只 · 悬停行可排序或删除
          </div>
        </Card>

        {/* 估值详情 */}
        <div className="flex h-full flex-col gap-5">
          {!selected ? (
            <Card>
              <Empty>请选择或添加一只股票</Empty>
            </Card>
          ) : score.error ? (
            <ErrorBox message={score.error} onRetry={score.reload} />
          ) : (
            <>
              <Card>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-[22px] font-semibold tracking-tight text-ink">{score.data?.name ?? selected}</h2>
                    <p className="mono mt-1 text-[12px] text-ink-faint">
                      {selected} · {BUCKETS.find((b) => b.key === score.data?.bucket)?.label ?? "—"} · 来源 {score.data?.source ?? "—"}
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-right sm:grid-cols-4">
                    <Metric label="P/E" value={num(score.data?.metrics?.pe)} />
                    <Metric label="P/B" value={num(score.data?.metrics?.pb)} />
                    <Metric label="P/S" value={num(score.data?.metrics?.ps)} />
                    <Metric label="FCF 收益率" value={pct(score.data?.metrics?.fcfYield)} />
                  </div>
                </div>

                <div className="mt-6 grid gap-3 sm:grid-cols-2">
                  {DIMS.map((d) => {
                    const v = score.data?.dimensions?.[d.key] ?? 0;
                    const invert = d.key === "substitutability";
                    const color = invert ? (v > 60 ? "#FF8A3D" : "#1F8A4C") : v >= 65 ? "#0A84FF" : v >= 45 ? "#FFB340" : "#8FD694";
                    return (
                      <div key={d.key} className="rounded-2xl bg-canvas-alt/70 px-4 py-3">
                        <div className="flex items-center justify-between">
                          <span className="text-[13px] font-medium text-ink-soft">{d.label}</span>
                          <span className="mono text-[14px] font-semibold" style={{ color }}>
                            {num(v, 0)}
                          </span>
                        </div>
                        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-black/[0.06]">
                          <motion.div
                            initial={{ width: 0 }}
                            animate={{ width: `${Math.min(100, v)}%` }}
                            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                            className="h-full rounded-full"
                            style={{ background: color }}
                          />
                        </div>
                        <p className="mt-1.5 text-[11px] text-ink-faint">{d.hint}</p>
                      </div>
                    );
                  })}
                </div>

                {score.data?.metrics?.marketCap ? (
                  <p className="mt-4 text-[12px] text-ink-faint">总市值 {compactCap(score.data.metrics.marketCap)}</p>
                ) : null}
              </Card>

              <Card pad={false} className="flex flex-1 flex-col justify-center p-5 sm:p-6">
                <div className="mb-1 flex items-center justify-between">
                  <h3 className="text-[15px] font-semibold tracking-tight text-ink">估值水平走势</h3>
                  <span className="text-[12px] text-ink-faint">滚轮缩放</span>
                </div>
                {score.loading && !score.data ? <Loading height={260} /> : <EChart option={peOption} height={260} />}
              </Card>
            </>
          )}
        </div>
      </div>

          </div>
  );
}

function IconBtn({ children, label, onClick }: { children: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="grid h-6 w-6 place-items-center rounded-full text-[12px] text-ink-faint transition-colors hover:bg-white hover:text-ink"
    >
      {children}
    </button>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="stat-label">{label}</div>
      <div className="mono text-[15px] font-semibold text-ink">{value}</div>
    </div>
  );
}