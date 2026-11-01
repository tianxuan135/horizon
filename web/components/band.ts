import type { BandKey } from "@/lib/types";

/** 综合评分色阶（规格固定）：极度贪婪(红) → 极度恐慌(深绿)。 */
export const BAND: Record<BandKey, { color: string; soft: string; label: string }> = {
  greed: { color: "#FF453A", soft: "rgba(255,69,58,0.12)", label: "极度贪婪" },
  attack: { color: "#FF8A3D", soft: "rgba(255,138,61,0.12)", label: "偏进攻" },
  neutral: { color: "#FFB340", soft: "rgba(255,179,64,0.12)", label: "中立" },
  defend: { color: "#8FD694", soft: "rgba(143,214,148,0.14)", label: "偏保守" },
  panic: { color: "#1F8A4C", soft: "rgba(31,138,76,0.12)", label: "极度恐慌" },
};

export const BAND_ORDER: BandKey[] = ["panic", "defend", "neutral", "attack", "greed"];

export function bandOf(score: number): BandKey {
  if (score >= 80) return "greed";
  if (score >= 65) return "attack";
  if (score >= 45) return "neutral";
  if (score >= 30) return "defend";
  return "panic";
}

export function bandColor(key?: string): string {
  return BAND[(key as BandKey) in BAND ? (key as BandKey) : "neutral"].color;
}