import clsx from "clsx";
import { stamp } from "@/lib/format";

/**
 * 模块头部：左侧标题，右上角固定时间戳（规格要求）。
 * 严格减法：不添加任何标题下方的小字解释。
 */
export function ModuleHeader({
  title,
  sub,
  asOf,
  note,
  right,
  loading,
}: {
  title: string;
  /** 英文主标题旁的中文备注（规格：网页标题以英文为主，中文备注）。 */
  sub?: string;
  asOf?: string | null;
  /** 时间戳旁的补充说明（例如数据实际截止日） */
  note?: React.ReactNode;
  right?: React.ReactNode;
  loading?: boolean;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <h1 className="flex items-baseline gap-2.5 text-[30px] font-semibold leading-tight tracking-[-0.02em] text-ink sm:text-[34px]">
        {title}
        {sub ? <span className="text-[14px] font-medium tracking-normal text-ink-faint">{sub}</span> : null}
      </h1>
      <div className="flex items-center gap-3">
        {right}
        <span
          className={clsx(
            "mono rounded-full bg-white/70 px-3 py-1 text-[12px] text-ink-mute shadow-[inset_0_0_0_1px_rgba(0,0,0,0.05)] transition-opacity",
            loading && "animate-pulse",
          )}
        >
          {loading ? "数据刷新中…" : stamp(asOf)}
        </span>
        {note ? <span className="text-[11px] text-ink-faint">{note}</span> : null}
      </div>
    </div>
  );
}