/** 展示层格式化：统一时间戳、百分比与数值口径。 */

const WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * 规格要求的时间戳文案：数据 YYYY-MM-DD（周x）HH:mm
 * 后端返回 UTC ISO，这里统一转本地时区展示。
 */
export function stamp(iso?: string | null): string {
  if (!iso) return "数据 —";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "数据 —";
  const ymd = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return `数据 ${ymd}（${WEEK[d.getDay()]}）${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function pct(v?: number | null, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function num(v?: number | null, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function signed(v?: number | null, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = v.toFixed(digits);
  return v > 0 ? `+${s}` : s;
}

export function compactCap(v?: number | null): string {
  if (!v) return "—";
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)} 万亿`;
  if (v >= 1e8) return `${(v / 1e8).toFixed(0)} 亿`;
  return v.toLocaleString("zh-CN");
}