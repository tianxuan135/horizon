"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useState } from "react";
import { ModuleHeader } from "@/components/module-header";
import { Card, Segmented } from "@/components/ui";
import { apiSend } from "@/lib/api";

/**
 * 账号页：邮箱注册 / 登录 + 验证码校验。
 * 开源部署默认关闭认证（AUTH_ENABLED=false）时，后端返回未开启提示，页面据此引导 `.env` 配置。
 * Token 仅存于浏览器 localStorage，不写入 Cookie，不含任何第三方身份信息。
 */

const TOKEN_KEY = "horizon.token";
const EMAIL_KEY = "horizon.email";

interface Me {
  id: string;
  email: string;
  market?: string;
}

type Mode = "login" | "register";

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [authOff, setAuthOff] = useState(false);

  const loadMe = useCallback(async () => {
    const token = window.localStorage.getItem(TOKEN_KEY);
    if (!token) return;
    try {
      const res = await fetch("/api/v1/auth/me", {
        headers: { authorization: `Bearer ${token}`, accept: "application/json" },
        cache: "no-store",
      });
      if (res.status === 401 || res.status === 403) {
        window.localStorage.removeItem(TOKEN_KEY);
        return;
      }
      if (!res.ok) return;
      setMe((await res.json()) as Me);
    } catch {
      /* 离线时不阻塞页面 */
    }
  }, []);

  useEffect(() => {
    const saved = window.localStorage.getItem(EMAIL_KEY);
    if (saved) setEmail(saved);
    void loadMe();
  }, [loadMe]);

  const emailOk = (v: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);

  const submit = async () => {
    setErr(null);
    setMsg(null);
    if (!emailOk(email)) {
      setErr("请输入有效邮箱地址");
      return;
    }
    if (password.length < 8) {
      setErr("密码至少 8 位");
      return;
    }
    setBusy(true);
    try {
      if (mode === "register") {
        const res = await apiSend<{ ok: boolean; requiresVerification: boolean }>("POST", "/auth/register", {
          email: email.trim(),
          password,
        });
        window.localStorage.setItem(EMAIL_KEY, email.trim());
        if (res.requiresVerification) {
          setNeedCode(true);
          setMsg("验证码已发送至邮箱，请填写后完成注册");
        } else {
          setMsg("注册成功，正在为你登录…");
          const login = await apiSend<{ token: string; user: Me }>("POST", "/auth/login", {
            email: email.trim(),
            password,
          });
          window.localStorage.setItem(TOKEN_KEY, login.token);
          setMe(login.user);
        }
      } else {
        const res = await apiSend<{ token: string; user: Me }>("POST", "/auth/login", {
          email: email.trim(),
          password,
        });
        window.localStorage.setItem(TOKEN_KEY, res.token);
        window.localStorage.setItem(EMAIL_KEY, email.trim());
        setMe(res.user);
        setMsg("登录成功");
      }
    } catch (e) {
      const text = e instanceof Error ? e.message : "请求失败";
      if (/未开启|disabled|AUTH_ENABLED/i.test(text)) setAuthOff(true);
      setErr(text);
    } finally {
      setBusy(false);
    }
  };
  const verify = async () => {
    setErr(null);
    setBusy(true);
    try {
      await apiSend<{ ok: boolean }>("POST", "/auth/verify", { email: email.trim(), code: code.trim() });
      setMsg("验证成功，正在登录…");
      const login = await apiSend<{ token: string; user: Me }>("POST", "/auth/login", {
        email: email.trim(),
        password,
      });
      window.localStorage.setItem(TOKEN_KEY, login.token);
      setMe(login.user);
      setNeedCode(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "验证失败");
    } finally {
      setBusy(false);
    }
  };

  const logout = () => {
    window.localStorage.removeItem(TOKEN_KEY);
    setMe(null);
    setMsg("已退出登录");
  };

  return (
    <div className="animate-fade-up mx-auto max-w-[520px]">
      <ModuleHeader title="账号登录" />

      {me ? (
        <Card>
          <h2 className="text-[18px] font-semibold tracking-tight text-ink">已登录</h2>
          <p className="mono mt-1 text-[13px] text-ink-mute">{me.email}</p>
          <p className="mt-3 text-[12px] leading-relaxed text-ink-faint">
            账号用于跨设备同步自选股与偏好设置，不涉及任何资金、交易或持仓信息。
          </p>
          <button
            type="button"
            onClick={logout}
            className="mt-5 rounded-full bg-canvas-alt px-4 py-2 text-[13px] font-medium text-ink-soft transition-colors hover:bg-black/[0.06]"
          >
            退出登录
          </button>
        </Card>
      ) : (
        <Card>
          <Segmented
            value={mode}
            options={[
              { value: "login", label: "登录" },
              { value: "register", label: "注册" },
            ]}
            onChange={(v) => {
              setMode(v);
              setErr(null);
              setMsg(null);
              setNeedCode(false);
            }}
            ariaLabel="登录或注册"
          />

          <AnimatePresence mode="wait">
            {needCode ? (
              <motion.div
                key="code"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                className="mt-5 flex flex-col gap-3"
              >
                <label className="flex flex-col gap-1.5">
                  <span className="stat-label">邮箱验证码</span>
                  <input
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    inputMode="numeric"
                    placeholder="6 位数字"
                    className="mono rounded-2xl border border-black/[0.07] bg-canvas-alt px-4 py-3 text-center text-[18px] tracking-[0.4em] text-ink outline-none focus:shadow-[0_0_0_3px_rgba(10,132,255,0.14)]"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void verify()}
                  disabled={busy || code.length < 4}
                  className="rounded-full bg-ink px-5 py-3 text-[13px] font-medium text-white transition-transform duration-300 ease-apple hover:scale-[1.01] disabled:opacity-50"
                >
                  {busy ? "验证中…" : "验证并登录"}
                </button>
              </motion.div>
            ) : (
              <motion.form
                key="form"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                onSubmit={(e) => {
                  e.preventDefault();
                  void submit();
                }}
                className="mt-5 flex flex-col gap-3"
              >
                <label className="flex flex-col gap-1.5">
                  <span className="stat-label">邮箱</span>
                  <input
                    type="email"
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="rounded-2xl border border-black/[0.07] bg-canvas-alt px-4 py-3 text-[14px] text-ink outline-none focus:shadow-[0_0_0_3px_rgba(10,132,255,0.14)]"
                  />
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="stat-label">密码</span>
                  <input
                    type="password"
                    autoComplete={mode === "login" ? "current-password" : "new-password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="至少 8 位"
                    className="rounded-2xl border border-black/[0.07] bg-canvas-alt px-4 py-3 text-[14px] text-ink outline-none focus:shadow-[0_0_0_3px_rgba(10,132,255,0.14)]"
                  />
                </label>
                <button
                  type="submit"
                  disabled={busy}
                  className="mt-1 rounded-full bg-ink px-5 py-3 text-[13px] font-medium text-white transition-transform duration-300 ease-apple hover:scale-[1.01] disabled:opacity-50"
                >
                  {busy ? "提交中…" : mode === "login" ? "登录" : "注册"}
                </button>
              </motion.form>
            )}
          </AnimatePresence>

          {err ? <p className="mt-3 text-[12px] text-warn">{err}</p> : null}
          {msg ? <p className="mt-3 text-[12px] text-panic">{msg}</p> : null}

          {authOff ? (
            <div className="mt-4 rounded-2xl bg-canvas-alt p-4 text-[12px] leading-relaxed text-ink-mute">
              本部署未开启认证。开源默认关闭账号体系：在 <span className="mono">.env</span> 中设置
              <span className="mono"> AUTH_ENABLED=true</span> 并配置自有 SMTP 后即可启用邮箱验证码。
              所有分析功能无需登录即可使用。
            </div>
          ) : null}
        </Card>
      )}

      <p className="mt-4 px-1 text-[11px] leading-relaxed text-ink-faint">
        密码经哈希存储于你自己的数据库；本项目不收集、不上传任何账号信息到第三方服务。
      </p>
    </div>
  );
}