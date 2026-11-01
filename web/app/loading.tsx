/**
 * 首屏加载骨架：与真实布局同宽同位，避免出现布局跳动。
 */
export default function Loading() {
  return (
    <div className="mx-auto w-full max-w-[1180px] animate-pulse px-5 py-10">
      <div className="h-6 w-52 rounded-full bg-ink/[0.06]" />
      <div className="mt-4 h-4 w-80 rounded-full bg-ink/[0.04]" />
      <div className="mt-8 grid gap-4 lg:grid-cols-[300px_1fr]">
        <div className="h-[300px] rounded-card bg-ink/[0.04]" />
        <div className="h-[300px] rounded-card bg-ink/[0.04]" />
      </div>
      <div className="mt-4 h-[280px] rounded-card bg-ink/[0.04]" />
    </div>
  );
}
