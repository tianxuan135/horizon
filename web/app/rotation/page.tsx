"use client";

import type { EChartsCoreOption } from "echarts";
import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import { EChart, baseGrid, chartTheme, zoomX } from "@/components/echart";
import { ModuleHeader } from "@/components/module-header";
import { Card, ErrorBox, Loading, Segmented } from "@/components/ui";
import { useApi } from "@/lib/api";
import { signed } from "@/lib/format";
import { useMarket } from "@/lib/market";
import type { RotationResult } from "@/lib/types";

/**
 * 风格轮动分析。
 * 评分由后端计算，前端只呈现结论与可视化（按规格：任何计算方式均不在前端暴露）。
 * 读数：负值偏向 B 组（小盘 / 消费），正值偏向 A 组（大盘 / 科技）。
 */

const GROUPS = [
  { value: "size" as const, label: "大盘 vs 小盘" },
  { value: "style" as const, label: "科技 vs 消费" },
];

const PAIRS: Record<string, Record<string, { a: string; b: string }>> = {
  us: { size: { a: "标普500", b: "罗素2000" }, style: { a: "纳指", b: "标普品质消费" } },
  cn: { size: { a: "沪深300", b: "中证2000" }, style: { a: "创业板指", b: "中证红利" } },
};

const H_CHART = 340;

export default function RotationPage() {
  const { market, label } = useMarket();
  const [group, setGroup] = useState<"size" | "style">("size");
  const { data, error, loading, reload } = useApi<RotationResult>("/rotation/score", { market, group, days: 365 }, [market, group]);

  const rows = data?.series ?? [];
  const last = rows[rows.length - 1];
  const pair = data?.pair ?? { a: "", b: "", aName: PAIRS[market][group].a, bName: PAIRS[market][group].b };
  const bias = last ? (last.score >= 0 ? `${pair.aName} 占优` : `${pair.bName} 占优`) : "—";
  const tone = last && last.score >= 0 ? "#0A84FF" : "#1F8A4C";
  /** 读数指针位置（-100 ~ +100 映射到 0% ~ 100%） */
  const pos = last ? Math.min(100, Math.max(0, ((last.score + 100) / 200) * 100)) : 50;

  const option = useMemo<EChartsCoreOption>(() => {
    return {
      textStyle: chartTheme.textStyle,
      grid: baseGrid({ top: 22, bottom: 8, right: 16 }),
      tooltip: {
        ...chartTheme.tooltip,
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: "rgba(0,0,0,0.18)" } },
        formatter: (ps: unknown) => {
          const arr = ps as { dataIndex: number }[];
          if (!arr?.length) return "";
          const r = rows[arr[0].dataIndex];
          if (!r) return "";
          return [
            `<div style="font-weight:600;margin-bottom:6px">${r.t}</div>`,
            `<div>轮动分数：<b style="color:${r.score >= 0 ? "#0A84FF" : "#1F8A4C"}">${r.score.toFixed(1)}</b></div>`,
            `<div>读数区间：${r.score >= 0 ? pair.aName : pair.bName} 占优</div>`,
          ].join("");
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
      yAxis: {
        type: "value",
        min: -100,
        max: 100,
        interval: 50,
        splitLine: chartTheme.splitLine,
        axisLabel: chartTheme.axisLabel,
      },
      dataZoom: [...zoomX(45, 100)],
      series: [
        {
          type: "line",
          name: "轮动分数",
          smooth: 0.3,
          showSymbol: false,
          data: rows.map((r) => r.score),
          lineStyle: { width: 2.2, color: "#0A84FF" },
          itemStyle: { color: "#0A84FF" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(10,132,255,0.16)" },
                { offset: 1, color: "rgba(10,132,255,0)" },
              ],
            },
          },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: "rgba(0,0,0,0.16)", type: "dashed" },
            label: { show: false },
            data: [{ yAxis: 0 }],
          },
          markArea: {
            silent: true,
            itemStyle: { color: "rgba(31,138,76,0.05)" },
            data: [[{ yAxis: -100 }, { yAxis: 0 }]],
          },
        },
      ],
    };
  }, [rows, pair.aName, pair.bName]);

  return (
    <div className="animate-fade-up">
      <ModuleHeader
        title="风格轮动分析"
        asOf={data?.asOf}
        loading={loading}
        right={<span className="pill bg-white/70 text-ink-mute shadow-[inset_0_0_0_1px_rgba(0,0,0,0.05)]">{label}</span>}
      />

      {error ? <ErrorBox message={error} onRetry={reload} /> : null}

      <Card pad={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5 sm:px-6">
          <Segmented value={group} options={GROUPS} onChange={setGroup} ariaLabel="分析组别" />
          <span className="mono text-[12px] text-ink-faint">
            {pair.aName} / {pair.bName}
          </span>
        </div>

        <div className="grid gap-4 px-3 pb-4 pt-2 sm:px-4 lg:grid-cols-[1fr_286px]">
          {/* 曲线（左） */}
          <div className="min-w-0">
            {loading && !data ? <Loading height={H_CHART} /> : <EChart option={option} height={H_CHART} />}
          </div>

          {/* 读数可视化（右，与图像等高并列） */}
          <div className="flex flex-col justify-between gap-4 rounded-2xl bg-canvas-alt/60 px-4 py-4">
            <div>
              <div className="stat-label">当前轮动分数</div>
              <motion.div
                key={last?.score ?? 0}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                className="mono mt-1 text-[44px] font-semibold leading-none tracking-[-0.03em]"
                style={{ color: tone }}
              >
                {last ? signed(last.score, 1) : "—"}
              </motion.div>
            </div>

            {/* 指针刻度：直观落位在 B 占优 ↔ A 占优 之间 */}
            <div>
              <div className="relative h-2 w-full rounded-full bg-[linear-gradient(90deg,#1F8A4C_0%,#8FD694_32%,#E9E9EC_50%,#5AC8FA_68%,#0A84FF_100%)]">
                <motion.span
                  className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-card"
                  style={{ background: tone }}
                  initial={false}
                  animate={{ left: `${pos}%` }}
                  transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                />
              </div>
              <div className="mt-2 flex items-center justify-between text-[11px] text-ink-faint">
                <span className="truncate">{pair.bName} 占优</span>
                <span className="truncate text-right">{pair.aName} 占优</span>
              </div>
            </div>

            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="stat-label">当前偏向</span>
                <span className="pill" style={{ color: tone, background: last && last.score >= 0 ? "rgba(10,132,255,0.10)" : "rgba(31,138,76,0.10)" }}>
                  {bias}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="stat-label">Z 值</span>
                <span className="mono text-[15px] font-semibold text-ink">{last ? last.z?.toFixed(2) ?? "—" : "—"}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="stat-label">样本区间</span>
                <span className="mono truncate text-[11px] text-ink-soft">
                  {rows.length ? `${rows[0].t} 至 ${rows[rows.length - 1].t}` : "—"}
                </span>
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}