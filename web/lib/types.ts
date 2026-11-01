/** 与 docs/API_CONTRACT.md 一一对应的类型定义。 */

export type Market = "us" | "cn";
export type Period = "1d" | "3d" | "5d" | "10d" | "30d" | "90d" | "250d";
export type BandKey = "greed" | "attack" | "neutral" | "defend" | "panic";

export interface SourceStatus {
  id: string;
  name: string;
  kind: string;
  ok: boolean;
  latencySec?: number;
  latency_ms?: number;
  license: string;
  freshness?: string;
  note?: string;
}

export interface MetaStatus {
  asOf: string;
  app: string;
  version: string;
  sources: SourceStatus[];
  disclaimer: string;
}

export interface Industry {
  key: string;
  name: string;
  nameEn: string;
}

export interface IndustryScore extends Industry {
  score: number;
  label: string;
  color: BandKey;
  /** 相对 5 根 K 线的评分变化（后端额外字段，用于热度箭头） */
  change?: number;
  /** 该行业使用的代理标的（ETF / 指数） */
  proxy?: string;
  /** 行业级五维分（下钻面板用） */
  dims?: Record<string, number>;
}

export interface DimensionScore {
  key: string;
  name: string;
  weight: number;
  score: number;
  series: { t: string; v: number }[];
}

export interface CompositeScore {
  score: number;
  label: string;
  color: BandKey;
  index: { symbol: string; name: string; value: number };
}

export interface CrowdingScore {
  asOf: string;
  source: string;
  market: Market;
  period: Period;
  industries: IndustryScore[];
  composite: CompositeScore;
  dimensions: DimensionScore[];
  mainSeries: { t: string; score: number; label: string; indexValue: number }[];
  /** 数据实际截止交易日（与 asOf 计算时间可能不同，上游滞后时以它为准） */
  dataThrough?: string;
  warnings?: string[];
}

export interface CrowdingHistory {
  asOf: string;
  series: { t: string; score: number; indexValue: number }[];
}

export interface RotationPoint {
  t: string;
  r: number;
  m10: number;
  z: number;
  score: number;
}

export interface RotationResult {
  asOf: string;
  group: "size" | "style";
  pair: { a: string; b: string; aName: string; bName: string };
  series: RotationPoint[];
  formula: string;
  current?: RotationPoint & { mu252?: number; sigma252?: number; bias?: string };
  warnings?: string[];
}

export interface SearchHit {
  symbol: string;
  name: string;
  exchange: string;
  market: Market;
}

export interface WatchItem {
  id: string;
  symbol: string;
  name: string;
  bucket: "consumer" | "cyclical" | "tech";
  sort: number;
}

export interface ValuationScore {
  asOf: string;
  symbol: string;
  name: string;
  bucket: string;
  metrics: { pe?: number; pb?: number; ps?: number; fcfYield?: number; marketCap?: number };
  dimensions: { fundamental: number; moat: number; substitutability: number; capex: number };
  series: { t: string; pe: number }[];
  source: string;
}

export interface Benchmark {
  id: string;
  symbol: string;
  name: string;
}

export interface Strategy {
  id: string;
  name: string;
  factors: string[];
  desc: string;
}

export interface BacktestResult {
  asOf: string;
  equity: { t: string; nav: number; bench: number }[];
  metrics: {
    cagr: number;
    mdd: number;
    sharpe: number;
    vol: number;
    alpha: number;
    beta: number;
    winRate: number;
  };
  benchmark: { id: string; name: string };
  warnings?: string[];
}

export interface MinedFactor {
  factor: string;
  ic: number;
  icir: number;
  tStat: number;
  turnover: number;
  desc: string;
}

export interface OptionLeg {
  type: "call" | "put";
  side: "long" | "short";
  strike: number;
  premium: number;
  qty: number;
}

export interface PayoffResult {
  curve: { price: number; pnl: number }[];
  maxProfit: number | null;
  maxLoss: number;
  breakevens: number[];
  netPremium: number;
}