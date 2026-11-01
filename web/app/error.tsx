"use client";

import { useEffect } from "react";

/**
 * 全局错误边界：只展示可恢复的操作，不把技术堆栈暴露给使用者。
 * 详细错误写入浏览器控制台，便于自托管部署时排查。
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[horizon] 页面渲染失败：", error);
  }, [error]);

  return (
    <main className="mx-auto flex min-h-[62vh] w-full max-w-[620px] flex-col items-center justify-center gap-5 px-6 text-center">
      <span className="mono text-[12px] tracking-[0.22em] text-ink/35">ERROR</span>
      <h1 className="text-[22px] font-semibold tracking-tight text-ink">这一页没能加载</h1>
      <p className="max-w-[400px] text-[14px] leading-6 text-ink/55">
        通常是后端接口暂时不可用（例如 API 未启动或数据源超时）。可以重试，或稍后再打开。
      </p>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="rounded-full bg-ink px-5 py-2 text-[13px] font-medium text-white transition hover:opacity-85"
        >
          重试
        </button>
        <a
          href="/"
          className="rounded-full border border-ink/12 px-5 py-2 text-[13px] font-medium text-ink/70 transition hover:bg-ink/[0.04]"
        >
          回到首页
        </a>
      </div>
      {error.digest ? (
        <p className="mono text-[11px] text-ink/30">错误编号 {error.digest}</p>
      ) : null}
    </main>
  );
}
