"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { Market } from "./types";

/**
 * 市场上下文。
 * 产品规格要求：市场切换 **只出现在设置页**，其余模块继承该状态。
 */
const KEY = "horizon.market";

interface Ctx {
  market: Market;
  setMarket: (m: Market) => void;
  label: string;
  indexName: string;
}

const MarketCtx = createContext<Ctx>({
  market: "us",
  setMarket: () => {},
  label: "美股",
  indexName: "标普500",
});

export function MarketProvider({ children }: { children: React.ReactNode }) {
  const [market, setMarketState] = useState<Market>("us");

  useEffect(() => {
    const saved = window.localStorage.getItem(KEY);
    if (saved === "us" || saved === "cn") setMarketState(saved);
  }, []);

  const setMarket = useCallback((m: Market) => {
    setMarketState(m);
    window.localStorage.setItem(KEY, m);
  }, []);

  const value = useMemo<Ctx>(
    () => ({
      market,
      setMarket,
      label: market === "us" ? "美股" : "A 股",
      indexName: market === "us" ? "标普500" : "沪深300",
    }),
    [market, setMarket],
  );

  return <MarketCtx.Provider value={value}>{children}</MarketCtx.Provider>;
}

export const useMarket = () => useContext(MarketCtx);