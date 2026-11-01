"use client";

import type { EChartsCoreOption } from "echarts";
import { useMemo } from "react";
import { EChart } from "./echart";

/** 迷你趋势图：用于五维评分与估值维度的历史曲线。 */
export function Sparkline({
  points,
  color = "#0A84FF",
  height = 64,
  heightClass = "",
}: {
  points: { t: string; v: number }[];
  color?: string;
  height?: number;
  heightClass?: string;
}) {
  const option = useMemo<EChartsCoreOption>(() => {
    const data = points.map((p) => [p.t, p.v]);
    return {
      animationDuration: 420,
      grid: { left: 0, right: 0, top: 6, bottom: 4 },
      xAxis: { type: "category", show: false, boundaryGap: false, data: points.map((p) => p.t) },
      yAxis: { type: "value", show: false, scale: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(255,255,255,0.95)",
        borderColor: "rgba(0,0,0,0.06)",
        textStyle: { color: "#1D1D1F", fontSize: 11 },
        extraCssText: "border-radius:10px;box-shadow:0 8px 24px -14px rgba(0,0,0,0.4);",
        formatter: (ps: unknown) => {
          const arr = ps as { data: [string, number] }[];
          if (!arr?.length) return "";
          const [t, v] = arr[0].data;
          return `${t}<br/><b>${Number(v).toFixed(1)}</b>`;
        },
      },
      series: [
        {
          type: "line",
          data,
          smooth: 0.35,
          showSymbol: false,
          lineStyle: { width: 1.6, color },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: `${color}33` },
                { offset: 1, color: `${color}00` },
              ],
            },
          },
        },
      ],
    };
  }, [points, color]);

  return <EChart option={option} height={height} className={heightClass} />;
}