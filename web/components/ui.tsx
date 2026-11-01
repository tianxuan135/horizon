"use client";

import clsx from "clsx";
import type { ReactNode } from "react";

/** 通用：卡片 / 分段控件 / 指标块 / 状态占位。保持 Apple 极简，无多余装饰。 */

export function Card({
  children,
  className,
  pad = true,
}: {
  children: ReactNode;
  className?: string;
  pad?: boolean;
}) {
  return <section className={clsx("card", pad && "card-pad", className)}>{children}</section>;
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = "md",
  ariaLabel,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  size?: "sm" | "md";
  ariaLabel?: string;
}) {
  return (
    <div className="segmented" role="tablist" aria-label={ariaLabel}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "segmented-item",
            size === "sm" && "px-2.5 py-1 text-[12px]",
            value === o.value && "segmented-item-active",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "ink",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "ink" | "greed" | "panic" | "accent";
}) {
  const toneCls =
    tone === "greed" ? "text-greed" : tone === "panic" ? "text-panic" : tone === "accent" ? "text-accent" : "text-ink";
  return (
    <div className="flex flex-col gap-1">
      <span className="stat-label">{label}</span>
      <span className={clsx("stat-value", toneCls)}>{value}</span>
      {hint ? <span className="text-[12px] text-ink-faint">{hint}</span> : null}
    </div>
  );
}

export function Badge({ children, color, soft }: { children: ReactNode; color: string; soft: string }) {
  return (
    <span className="pill" style={{ color, background: soft }}>
      {children}
    </span>
  );
}

export function Loading({ label = "载入中", height = 240 }: { label?: string; height?: number }) {
  return (
    <div className="flex w-full items-center justify-center" style={{ height }}>
      <div className="flex items-center gap-2.5 text-[13px] text-ink-faint">
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-ink-faint/30 border-t-ink-faint" />
        {label}
      </div>
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-2xl bg-warn/[0.06] p-4 text-[13px] text-ink-soft">
      <p className="text-warn">{message}</p>
      <p className="text-ink-mute">
        请确认后端服务已启动（默认 <span className="mono">http://127.0.0.1:8000</span>），或在设置页查看「数据状态」。
      </p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-full bg-white px-3 py-1.5 text-[12px] font-medium text-ink shadow-sm transition-transform duration-300 ease-apple hover:scale-[1.02]"
        >
          重新获取
        </button>
      ) : null}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-black/10 px-4 py-8 text-center text-[13px] text-ink-faint">
      {children}
    </div>
  );
}