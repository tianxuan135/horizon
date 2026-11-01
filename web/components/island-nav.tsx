"use client";

import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

/** 顶部悬浮岛导航：收纳全部分析模块与设置、登录。 */

const ITEMS: { href: string; label: string }[] = [
  { href: "/", label: "市场拥挤度" },
  { href: "/rotation", label: "风格轮动分析" },
  { href: "/valuation", label: "估值分析" },
  { href: "/factor", label: "因子策略分析" },
  { href: "/options", label: "期权策略分析" },
];

export function IslandNav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <header className="pointer-events-none fixed inset-x-0 top-0 z-50 flex justify-center px-4 pt-4 sm:pt-6">
      <motion.nav
        initial={{ y: -18, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
        className="glass pointer-events-auto flex w-full max-w-[1120px] items-center gap-2 rounded-island px-2.5 py-2"
      >
        <Link href="/" className="flex shrink-0 items-center gap-2 rounded-full pl-2 pr-3" aria-label="极目楚天 首页">
          {/* 黑色 H 圆形 logo：保持原样，仅旁侧标题改为中文 */}
          <span className="grid h-7 w-7 place-items-center rounded-full bg-ink text-[13px] font-semibold text-white">H</span>
          <span className="hidden text-[14px] font-semibold tracking-tight text-ink sm:block">极目楚天</span>
        </Link>

        <div className="hidden items-center gap-0.5 md:flex">
          {ITEMS.map((it) => (
            <Link
              key={it.href}
              href={it.href}
              className={clsx(
                "relative rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors duration-300 ease-apple",
                isActive(it.href) ? "text-ink" : "text-ink-mute hover:text-ink-soft",
              )}
            >
              {isActive(it.href) && (
                <motion.span
                  layoutId="island-active"
                  className="absolute inset-0 rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.06),0_10px_22px_-14px_rgba(0,0,0,0.5)]"
                  transition={{ type: "spring", stiffness: 420, damping: 34 }}
                />
              )}
              <span className="relative">{it.label}</span>
            </Link>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-1.5">
          <Link
            href="/settings"
            className={clsx(
              "rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors duration-300 ease-apple",
              pathname.startsWith("/settings") ? "bg-white text-ink shadow-sm" : "text-ink-mute hover:text-ink-soft",
            )}
          >
            设置
          </Link>
          <Link
            href="/login"
            className="rounded-full bg-ink px-3.5 py-1.5 text-[13px] font-medium text-white transition-transform duration-300 ease-apple hover:scale-[1.03] active:scale-[0.98]"
          >
            账号登录
          </Link>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-label="展开导航"
            className="grid h-8 w-8 place-items-center rounded-full text-ink-mute hover:bg-white/70 md:hidden"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M2 4.5h12M2 8h12M2 11.5h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </motion.nav>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
            className="glass pointer-events-auto absolute inset-x-4 top-[72px] grid gap-1 rounded-card p-2 md:hidden"
          >
            {ITEMS.map((it) => (
              <Link
                key={it.href}
                href={it.href}
                onClick={() => setOpen(false)}
                className={clsx(
                  "rounded-2xl px-4 py-2.5 text-[14px] font-medium",
                  isActive(it.href) ? "bg-white text-ink shadow-sm" : "text-ink-mute",
                )}
              >
                {it.label}
              </Link>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}