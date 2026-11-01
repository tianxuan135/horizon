"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** BFF 前缀：由 next.config.mjs rewrite 转发到 FastAPI，浏览器永远看不到数据源密钥。 */
export const API_BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function apiGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  Object.entries(params ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  });
  const res = await fetch(url.toString(), { headers: { accept: "application/json" }, cache: "no-store" });
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* 保持默认文案 */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export async function apiSend<T>(method: "POST" | "DELETE" | "PATCH", path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "content-type": "application/json", accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const b = await res.json();
      if (b?.detail) detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {
      /* noop */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

/** 轻量数据钩子：不引入 SWR 依赖，保持开源仓库零冗余依赖。 */
export function useApi<T>(path: string | null, params?: Record<string, string | number | undefined>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!path) return;
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const json = await apiGet<T>(path, params);
      if (seq.current === id) setData(json);
    } catch (e) {
      if (seq.current === id) setError(e instanceof Error ? e.message : "未知错误");
    } finally {
      if (seq.current === id) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, JSON.stringify(params ?? {})]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, ...deps]);

  return { data, error, loading, reload: load };
}