"use client";

import * as echarts from "echarts";
import { useEffect, useRef } from "react";

/**
 * ECharts 薄封装。
 * 全局交互规范：所有图表支持悬停查看数据、滚轮横轴缩放（见 zoomX()）。
 */
export function EChart({
  option,
  height = 320,
  className = "",
  onClick,
}: {
  option: echarts.EChartsCoreOption;
  height?: number;
  className?: string;
  onClick?: (params: unknown) => void;
}) {
  const host = useRef<HTMLDivElement | null>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const inst = echarts.init(host.current, undefined, { renderer: "canvas" });
    chart.current = inst;
    const ro = new ResizeObserver(() => inst.resize());
    ro.observe(host.current);
    if (onClick) inst.on("click", onClick);
    return () => {
      ro.disconnect();
      inst.dispose();
      chart.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, true);
  }, [option]);

  return <div ref={host} className={className} style={{ height, width: "100%" }} />;
}

/** 横轴缩放：滚轮 + 拖拽，隐藏滑块以保持极简。 */
export function zoomX(start = 55, end = 100) {
  return [
    { type: "inside", start, end, zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false },
  ] as const;
}

const FONT = "-apple-system, BlinkMacSystemFont, SF Pro Text, PingFang SC, Microsoft YaHei, sans-serif";

export const chartTheme = {
  textStyle: { fontFamily: FONT, color: "#6E6E73", fontSize: 12 },
  tooltip: {
    backgroundColor: "rgba(255,255,255,0.94)",
    borderColor: "rgba(0,0,0,0.06)",
    borderWidth: 1,
    padding: [10, 12] as [number, number],
    textStyle: { color: "#1D1D1F", fontSize: 12, fontFamily: FONT },
    extraCssText: "border-radius:14px;box-shadow:0 12px 32px -16px rgba(0,0,0,0.35);backdrop-filter:blur(14px);",
  },
  axisLine: { lineStyle: { color: "rgba(0,0,0,0.08)" } },
  splitLine: { lineStyle: { color: "rgba(0,0,0,0.05)", type: "dashed" as const } },
  axisLabel: { color: "#A1A1A6", fontSize: 11, fontFamily: FONT },
};

export function baseGrid(extra?: { top?: number; bottom?: number; left?: number; right?: number }) {
  return { left: extra?.left ?? 8, right: extra?.right ?? 14, top: extra?.top ?? 24, bottom: extra?.bottom ?? 22, containLabel: true };
}