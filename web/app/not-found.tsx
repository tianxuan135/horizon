import Link from "next/link";

/**
 * 404 页面：保持与全站一致的 Apple 极简风格（大留白 + 单一主按钮）。
 */
export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-[62vh] w-full max-w-[620px] flex-col items-center justify-center gap-5 px-6 text-center">
      <span className="mono text-[12px] tracking-[0.22em] text-ink/35">404</span>
      <h1 className="text-[22px] font-semibold tracking-tight text-ink">页面不存在</h1>
      <p className="max-w-[380px] text-[14px] leading-6 text-ink/55">
        这个地址可能已被移动或从未存在。所有分析模块都在顶部悬浮岛导航里。
      </p>
      <Link
        href="/"
        className="rounded-full bg-ink px-5 py-2 text-[13px] font-medium text-white transition hover:opacity-85"
      >
        返回市场拥挤度
      </Link>
    </main>
  );
}
