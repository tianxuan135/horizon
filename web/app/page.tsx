"use client";

import type { EChartsCoreOption } from "echarts";
import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import { BAND, BAND_ORDER } from "@/components/band";
import { EChart, baseGrid, chartTheme, zoomX } from "@/components/echart";
import { ModuleHeader } from "@/components/module-header";
import { Sparkline } from "@/components/sparkline";
import { Card, ErrorBox, Loading, Segmented } from "@/components/ui";
import { useApi } from "@/lib/api";
import { num, pct } from "@/lib/format";
import { useMarket } from "@/lib/market";
import type { BandKey, CrowdingHistory, CrowdingScore, Period } from "@/lib/types";

/**
 * 市场拥挤度。
 * 数据来源：后端 /api/v1/crowding/*，五维加权 33/22/18/15/12（权重由后端固定，前端只展示）。
 * 版式（用户指定顺序）：综合评分 + 五维小图 → 五维结构图 → 综合拥挤度叠加指数 → 行业拥挤度 → 历史曲线。
 * 合规：本页仅为研究参考，不构成任何投资建议。
 */

const PERIODS: { value: Period; label: string }[] = [
  { value: "1d", label: "1日" },
  { value: "3d", label: "3日" },
  { value: "5d", label: "5日" },
  { value: "10d", label: "10日" },
  { value: "30d", label: "30日" },
  { value: "90d", label: "90日" },
  { value: "250d", label: "250日" },
];

const HISTORY_DAYS = [
  { value: "90", label: "90天" },
  { value: "180", label: "180天" },
  { value: "365", label: "365天" },
] as const;

const DIM_COLOR = ["#0A84FF", "#5AC8FA", "#FFB340", "#FF8A3D", "#8FD694"];

/** 模块统一高度，保证左右两栏、上下模块视觉齐平。 */
const H_MAIN = 300;
const H_RADAR = 300;
const H_HISTORY = 280;

export default function CrowdingPage() {
  const { market, label, indexName } = useMarket();
  const [period, setPeriod] = useState<Period>("5d");
  const [days, setDays] = useState<(typeof HISTORY_DAYS)[number]["value"]>("365");

  const score = useApi<CrowdingScore>("/crowding/score", { market, period }, [market, period]);
  const history = useApi<CrowdingHistory>("/crowding/history", { market, days, period }, [market, days, period]);

  const composite = score.data?.composite;
  const band = BAND[(composite?.color as BandKey) ?? "neutral"] ?? BAND.neutral;
  const dims = score.data?.dimensions ?? [];

  /** 主图：综合拥挤度（重点区域放大）叠加基准指数；悬停显示 判定 / 评分 / 指数值。 */
  const mainOption = useMemo<EChartsCoreOption>(() => {
    const rows = score.data?.mainSeries ?? [];
    return {
      textStyle: chartTheme.textStyle,
      grid: baseGrid({ top: 18, bottom: 8 }),
      tooltip: {
        ...chartTheme.tooltip,
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: "rgba(0,0,0,0.18)", width: 1 } },
        formatter: (ps: unknown) => {
          const arr = ps as { dataIndex: number }[];
          if (!arr?.length) return "";
          const row = rows[arr[0].dataIndex];
          if (!row) return "";
          const b = BAND[(row.label as BandKey) ?? "neutral"] ?? BAND.neutral;
          return [
            `<div style="font-weight:600;margin-bottom:6px">${row.t}</div>`,
            `<div>判定：<span style="color:${b.color};font-weight:600">${row.label}</span></div>`,
            `<div>评分：<b>${row.score?.toFixed(1)}</b></div>`,
            `<div>${indexName}：<b>${row.indexValue?.toFixed(2)}</b></div>`,
          ].join("");
        },
      },
      legend: { show: false },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: rows.map((r) => r.t),
        axisLine: chartTheme.axisLine,
        axisTick: { show: false },
        axisLabel: { ...chartTheme.axisLabel, hideOverlap: true },
      },
      yAxis: [
        {
          type: "value",
          name: "拥挤度",
          nameTextStyle: { color: "#A1A1A6", fontSize: 11, padding: [0, 0, 0, 8] },
          min: 0,
          max: 100,
          splitLine: chartTheme.splitLine,
          axisLabel: chartTheme.axisLabel,
        },
        {
          type: "value",
          name: indexName,
          nameTextStyle: { color: "#A1A1A6", fontSize: 11 },
          scale: true,
          splitLine: { show: false },
          axisLabel: chartTheme.axisLabel,
        },
      ],
      dataZoom: [...zoomX(60, 100)],
      series: [
        {
          name: "综合拥挤度",
          type: "line",
          smooth: 0.32,
          showSymbol: false,
          data: rows.map((r) => r.score),
          lineStyle: { width: 2.4, color: band.color },
          itemStyle: { color: band.color },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: `${band.color}2E` },
                { offset: 1, color: `${band.color}00` },
              ],
            },
          },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: "rgba(0,0,0,0.12)", type: "dashed" },
            label: { show: false },
            data: [{ yAxis: 65 }, { yAxis: 45 }, { yAxis: 30 }, { yAxis: 80 }],
          },
        },
        {
          name: indexName,
          type: "line",
          yAxisIndex: 1,
          smooth: 0.3,
          showSymbol: false,
          data: rows.map((r) => r.indexValue),
          lineStyle: { width: 1.3, color: "#1D1D1F", opacity: 0.45 },
        },
      ],
    };
  }, [score.data, band.color, indexName]);

  /** 独立历史拥挤度曲线（最多 365 天）。 */
  const historyOption = useMemo<EChartsCoreOption>(() => {
    const rows = history.data?.series ?? [];
    return {
      textStyle: chartTheme.textStyle,
      grid: baseGrid({ top: 20, bottom: 6 }),
      tooltip: {
        ...chartTheme.tooltip,
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: "rgba(0,0,0,0.18)" } },
        formatter: (ps: unknown) => {
          const arr = ps as { dataIndex: number }[];
          if (!arr?.length) return "";
          const row = rows[arr[0].dataIndex];
          if (!row) return "";
          const b = BAND[bandColorToKey(row.score)] ?? BAND.neutral;
          return `<div style="font-weight:600;margin-bottom:4px">${row.t}</div><div>拥挤度 <b>${row.score.toFixed(1)}</b> <span style="color:${b.color}">${b.label}</span></div><div>${indexName} <b>${row.indexValue?.toFixed(2)}</b></div>`;
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: rows.map((r) => r.t),
        axisLine: chartTheme.axisLine,
        axisTick: { show: false },
        axisLabel: { ...chartTheme.axisLabel, hideOverlap: true },
      },
      yAxis: [
        { type: "value", min: 0, max: 100, splitLine: chartTheme.splitLine, axisLabel: chartTheme.axisLabel },
        { type: "value", scale: true, splitLine: { show: false }, axisLabel: chartTheme.axisLabel },
      ],
      dataZoom: [...zoomX(0, 100)],
      series: [
        {
          type: "line",
          smooth: 0.28,
          showSymbol: false,
          data: rows.map((r) => r.score),
          lineStyle: { width: 2, color: "#0A84FF" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(10,132,255,0.20)" },
                { offset: 1, color: "rgba(10,132,255,0)" },
              ],
            },
          },
        },
        {
          type: "line",
          yAxisIndex: 1,
          smooth: 0.3,
          showSymbol: false,
          data: rows.map((r) => r.indexValue),
          lineStyle: { width: 1.2, color: "rgba(29,29,31,0.4)" },
        },
      ],
    };
  }, [history.data, indexName]);

  /** 五维结构图（雷达）：直观呈现五个分项的相对强弱。 */
  const radarOption = useMemo<EChartsCoreOption>(() => {
    return {
      textStyle: chartTheme.textStyle,
      tooltip: { ...chartTheme.tooltip, trigger: "item" },
      radar: {
        center: ["50%", "54%"],
        radius: "66%",
        indicator: dims.map((d) => ({ name: d.name, max: 100 })),
        axisName: { color: "#6E6E73", fontSize: 11 },
        splitLine: { lineStyle: { color: "rgba(0,0,0,0.07)" } },
        axisLine: { lineStyle: { color: "rgba(0,0,0,0.07)" } },
        splitArea: { show: false },
      },
      series: [
        {
          type: "radar",
          symbolSize: 4,
          data: [
            {
              value: dims.map((d) => Number(d.score.toFixed(1))),
              name: "五维结构",
              lineStyle: { width: 2, color: band.color },
              itemStyle: { color: band.color },
              areaStyle: { color: `${band.color}26` },
            },
          ],
        },
      ],
    };
  }, [dims, band.color]);

  return (
    <div className="animate-fade-up">
      <ModuleHeader
        title="市场拥挤度"
        asOf={score.data?.asOf}
        note={score.data?.dataThrough ? `数据截止 ${score.data.dataThrough}` : undefined}
        loading={score.loading}
        right={
          <div className="flex items-center gap-2">
            <Segmented value={period} options={PERIODS} onChange={setPeriod} size="sm" ariaLabel="时间周期" />
            <span className="pill bg-white/70 text-ink-mute shadow-[inset_0_0_0_1px_rgba(0,0,0,0.05)]">{label}</span>
          </div>
        }
      />

      {score.error ? <ErrorBox message={score.error} onRetry={score.reload} /> : null}

      {/* ① 综合拥挤度评分 + 五个分模块小图（左右齐平） */}
      <div className="grid items-stretch gap-5 lg:grid-cols-[300px_1fr]">
        <Card className="flex h-full flex-col justify-between">
          <div>
            <div className="stat-label">综合拥挤度</div>
            <div className="mt-3 flex items-end gap-3">
              <motion.span
                key={composite?.score ?? 0}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                className="mono text-[52px] font-semibold leading-none tracking-[-0.03em]"
                style={{ color: band.color }}
              >
                {composite ? composite.score.toFixed(1) : "—"}
              </motion.span>
              <span className="pill mb-2" style={{ color: band.color, background: band.soft }}>
                {composite?.label ?? "—"}
              </span>
            </div>
            <div className="mt-5 space-y-1.5 text-[13px] text-ink-mute">
              <div className="flex items-center justify-between">
                <span>{indexName}</span>
                <span className="mono text-ink">{composite?.index?.value?.toFixed(2) ?? "—"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span>数据来源</span>
                <span className="mono text-[12px] text-ink-soft">{score.data?.source ?? "—"}</span>
              </div>
            </div>
          </div>

          {/* 色阶图例（仅图例，不放置刻度仪表） */}
          <div className="mt-6 flex items-center gap-1">
            {BAND_ORDER.map((k) => (
              <div key={k} className="h-1.5 flex-1 rounded-full" style={{ background: BAND[k].color, opacity: composite?.color === k ? 1 : 0.28 }} />
            ))}
          </div>
        </Card>

        <Card className="flex h-full flex-col">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-[15px] font-semibold tracking-tight text-ink">五维结构图</h2>
            <span className="text-[11.5px] text-ink-faint">面积越大，整体拥挤度越高</span>
          </div>
          <div className="grid flex-1 items-center gap-2 sm:grid-cols-[1fr_180px]">
            {score.loading && !score.data ? <Loading height={264} /> : <EChart option={radarOption} height={264} />}
            <div className="flex flex-col justify-center gap-2">
              {dims.map((d, i) => {
                const c = DIM_COLOR[i % DIM_COLOR.length];
                return (
                  <div key={d.key}>
                    <div className="flex items-baseline justify-between text-[12px]">
                      <span className="text-ink-soft">{d.name}</span>
                      <span className="mono font-semibold" style={{ color: c }}>
                        {num(d.score, 1)}
                      </span>
                    </div>
                    <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-black/[0.06]">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${Math.min(100, Math.max(2, d.score))}%` }}
                        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                        className="h-full rounded-full"
                        style={{ background: c }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </Card>
      </div>

      {/* ② 五维评分（五个分项等宽排列） */}
      <Card className="mt-5" pad={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5 sm:px-6">
          <h2 className="text-[15px] font-semibold tracking-tight text-ink">五维评分</h2>
          <span className="text-[11.5px] text-ink-faint">加权 33 / 22 / 18 / 15 / 12</span>
        </div>
        <div className="grid gap-3 px-4 pb-5 pt-3 sm:grid-cols-2 sm:px-5 lg:grid-cols-5">
          {dims.length
            ? dims.map((d, i) => {
                const c = DIM_COLOR[i % DIM_COLOR.length];
                return (
                  <div key={d.key} className="flex h-full flex-col justify-between rounded-2xl border border-black/[0.05] bg-white px-3.5 py-3">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-[13px] font-medium text-ink-soft">{d.name}</span>
                      <span className="mono text-[15px] font-semibold" style={{ color: c }}>
                        {num(d.score, 1)}
                      </span>
                    </div>
                    <div className="mt-2">
                      <Sparkline points={d.series ?? []} color={c} height={40} />
                    </div>
                    <div className="mono mt-1 text-[10.5px] text-ink-faint">权重 {pct(d.weight, 0)}</div>
                  </div>
                );
              })
            : Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-[128px] animate-pulse rounded-2xl bg-black/[0.035]" />)}
        </div>
      </Card>

      {/* ③ 综合拥挤度 · 指数叠加 */}
      <Card className="mt-5" pad={false}>
        <div className="flex items-center justify-between px-5 pt-5 sm:px-6">
          <h2 className="text-[15px] font-semibold tracking-tight text-ink">综合拥挤度 · {indexName}叠加</h2>
          <span className="text-[11.5px] text-ink-faint">滚轮缩放 · 悬停查看</span>
        </div>
        <div className="px-2 pb-3 pt-1 sm:px-3">
          {score.loading && !score.data ? <Loading height={H_MAIN} /> : <EChart option={mainOption} height={H_MAIN} />}
        </div>
      </Card>

      {/* ④ 行业拥挤度（13 个固定行业） */}
      <Card className="mt-5" pad={false}>
        <div className="flex items-center justify-between px-5 pb-2 pt-5 sm:px-6">
          <h2 className="text-[15px] font-semibold tracking-tight text-ink">行业拥挤度</h2>
          <span className="text-[11.5px] text-ink-faint">共 13 个固定行业</span>
        </div>
        <div className="grid grid-cols-2 gap-2 px-4 pb-5 pt-2 sm:grid-cols-3 sm:px-5 lg:grid-cols-5">
          {(score.data?.industries ?? []).map((it) => {
            const b = BAND[(it.color as BandKey) ?? "neutral"] ?? BAND.neutral;
            return (
              <motion.div
                key={it.key}
                layout
                className="flex h-full flex-col justify-between rounded-2xl border border-black/[0.05] bg-white px-3.5 py-3 transition-shadow duration-300 hover:shadow-card"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium text-ink-soft">{it.name}</span>
                  <span className="flex items-baseline gap-1">
                    {typeof it.change === "number" && Math.abs(it.change) >= 1 ? (
                      <span
                        className="text-[10px]"
                        style={{ color: it.change > 0 ? "#FF453A" : "#1F8A4C" }}
                        aria-label={it.change > 0 ? "评分上行" : "评分下行"}
                      >
                        {it.change > 0 ? "▲" : "▼"}
                      </span>
                    ) : null}
                    <span className="mono text-[13px] font-semibold" style={{ color: b.color }}>
                      {it.score.toFixed(0)}
                    </span>
                  </span>
                </div>
                <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-black/[0.06]">
                  <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.max(2, it.score))}%`, background: b.color }} />
                </div>
                <div className="mt-1.5 text-[11px] text-ink-faint">{it.label}</div>
              </motion.div>
            );
          })}
          {score.loading && !score.data
            ? Array.from({ length: 10 }).map((_, i) => <div key={i} className="h-[76px] animate-pulse rounded-2xl bg-black/[0.035]" />)
            : null}
        </div>
      </Card>

      {/* ⑤ 历史拥挤度（独立图表） */}
      <Card className="mt-5" pad={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 pb-2 pt-5 sm:px-6">
          <h2 className="text-[15px] font-semibold tracking-tight text-ink">历史拥挤度曲线</h2>
          <Segmented value={days} options={HISTORY_DAYS.map((d) => ({ value: d.value, label: d.label }))} onChange={setDays} size="sm" ariaLabel="历史区间" />
        </div>
        {history.error ? (
          <div className="px-5 pb-5">
            <ErrorBox message={history.error} onRetry={history.reload} />
          </div>
        ) : history.loading && !history.data ? (
          <Loading height={H_HISTORY} />
        ) : (
          <div className="px-2 pb-3 pt-1 sm:px-3">
            <EChart option={historyOption} height={H_HISTORY} />
          </div>
        )}
      </Card>

      {/* 合规要求（用户规格 §4）：首页末尾强制展示完整免责声明。
          页脚按 UI 规格只保留单句短提示，完整声明放在正文末尾，二者不冲突。 */}
      <p className="mt-10 text-center text-[11.5px] leading-relaxed text-ink-faint">
        本工具所有数据及分析结果仅供学习研究参考，不构成任何投资建议。
      </p>
    </div>
  );
}

function bandColorToKey(score: number): BandKey {
  if (score >= 80) return "greed";
  if (score >= 65) return "attack";
  if (score >= 45) return "neutral";
  if (score >= 30) return "defend";
  return "panic";
}