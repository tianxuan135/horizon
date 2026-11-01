"use client";

import clsx from "clsx";
import { motion } from "framer-motion";
import Link from "next/link";
import { useState } from "react";
import { ModuleHeader } from "@/components/module-header";
import { Card, ErrorBox, Loading, Segmented } from "@/components/ui";
import { useApi } from "@/lib/api";
import { useMarket } from "@/lib/market";
import type { MetaStatus } from "@/lib/types";

/**
 * 设置页。
 * 规格：市场切换 **仅在此页出现**；含 问题反馈 / 免责声明 / 隐私说明 / 数据状态 / 关于网页。
 * 仓库地址与版本通过环境变量注入，避免把个人 fork 地址硬编码进开源代码。
 */

const REPO = process.env.NEXT_PUBLIC_REPO_URL ?? "https://github.com/your-org/horizon";
const VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? "0.1.0";

const SECTIONS = [
  { id: "market", label: "市场" },
  { id: "status", label: "数据状态" },
  { id: "legal", label: "免责与隐私" },
  { id: "about", label: "关于" },
] as const;

export default function SettingsPage() {
  const { market, setMarket } = useMarket();
  const [open, setOpen] = useState<string | null>("status");
  const meta = useApi<MetaStatus>("/meta/status", { market }, [market]);

  return (
    <div className="animate-fade-up">
      <ModuleHeader title="设置" asOf={meta.data?.asOf} loading={meta.loading} />

      <div className="flex flex-col gap-4">
        <Card>
          <h2 className="text-[15px] font-semibold tracking-tight text-ink">市场切换</h2>
          <div className="mt-3">
            <Segmented
              value={market}
              options={[
                { value: "us", label: "美股" },
                { value: "cn", label: "A 股" },
              ]}
              onChange={(v) => setMarket(v)}
              ariaLabel="市场切换"
            />
          </div>
        </Card>

        <Card pad={false}>
          <Accordion
            title="数据状态"
            desc="各数据源可用性、许可与新鲜度"
            open={open === "status"}
            onToggle={() => setOpen(open === "status" ? null : "status")}
          >
            {meta.error ? (
              <ErrorBox message={meta.error} onRetry={meta.reload} />
            ) : meta.loading && !meta.data ? (
              <Loading height={140} label="检测数据源" />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] border-collapse text-[13px]">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-[0.08em] text-ink-faint">
                      <th className="py-2 pr-4 font-medium">数据源</th>
                      <th className="py-2 pr-4 font-medium">类型</th>
                      <th className="py-2 pr-4 font-medium">状态</th>
                      <th className="py-2 pr-4 font-medium">延迟</th>
                      <th className="py-2 font-medium">许可</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(meta.data?.sources ?? []).map((s) => (
                      <tr key={s.id} className="border-t border-black/[0.05]">
                        <td className="py-2.5 pr-4">
                          <div className="text-ink">{s.name}</div>
                          {s.note ? <div className="text-[11px] text-ink-faint">{s.note}</div> : null}
                        </td>
                        <td className="py-2.5 pr-4 text-ink-mute">{s.kind}</td>
                        <td className="py-2.5 pr-4">
                          <span
                            className={clsx(
                              "inline-flex items-center gap-1.5 text-[12px]",
                              s.ok ? "text-panic" : "text-ink-faint",
                            )}
                          >
                            <span
                              className={clsx("h-1.5 w-1.5 rounded-full", s.ok ? "bg-panic" : "bg-black/25")}
                            />
                            {s.ok ? "可用" : "不可用"}
                          </span>
                        </td>
                        <td className="mono py-2.5 pr-4 text-ink-mute">
                          {s.latency_ms ? `${s.latency_ms} ms` : "—"}
                        </td>
                        <td className="py-2.5 text-[12px] text-ink-faint">{s.license}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-3 text-[11px] leading-relaxed text-ink-faint">
                  免费公开接口可能存在延迟或限流；无法取得合法免费数据时，系统使用公开代理指标，并在对应模块标注来源，不会以模拟数据冒充真实行情。
                </p>
              </div>
            )}
          </Accordion>

          <Accordion
            title="问题反馈"
            desc="通过 GitHub Issue / Discussion 反馈"
            open={open === "feedback"}
            onToggle={() => setOpen(open === "feedback" ? null : "feedback")}
          >
            <div className="flex flex-wrap gap-2">
              <a
                href={`${REPO}/issues/new?template=bug_report.md`}
                target="_blank"
                rel="noreferrer noopener"
                className="rounded-full bg-ink px-4 py-2 text-[12px] font-medium text-white transition-transform duration-300 ease-apple hover:scale-[1.02]"
              >
                报告 Bug
              </a>
              <a
                href={`${REPO}/issues/new?template=feature_request.md`}
                target="_blank"
                rel="noreferrer noopener"
                className="rounded-full bg-canvas-alt px-4 py-2 text-[12px] font-medium text-ink-soft transition-colors hover:bg-black/[0.06]"
              >
                功能请求
              </a>
              <a
                href={`${REPO}/discussions`}
                target="_blank"
                rel="noreferrer noopener"
                className="rounded-full bg-canvas-alt px-4 py-2 text-[12px] font-medium text-ink-soft transition-colors hover:bg-black/[0.06]"
              >
                讨论区
              </a>
            </div>
            <p className="mt-3 text-[11px] text-ink-faint">
              提交前请移除 API Key、Token、账户信息等敏感内容。
            </p>
          </Accordion>

          <Accordion
            title="免责声明"
            desc="本工具所有数据及分析结果仅供学习研究参考"
            open={open === "legal"}
            onToggle={() => setOpen(open === "legal" ? null : "legal")}
          >
            <div className="space-y-3 text-[13px] leading-relaxed text-ink-soft">
              <p className="font-medium text-ink">
                本工具所有数据及分析结果仅供学习研究参考，不构成任何投资建议。
              </p>
              <p>
                本项目为个人金融数据学习与研究工具，不提供荐股、代客理财、带单、自动交易或任何形式的收益承诺；
                不代客操作账户，不接触用户资金。
              </p>
              <p>
                数据来自公开可访问的免费接口，可能存在延迟、缺失或错误，请以交易所与券商披露的正式数据为准。
                软件按「现状（AS IS）」提供，不承担任何直接或间接责任。
              </p>
              <p className="text-ink-faint">
                投资有风险，决策需谨慎。使用者应自行独立判断，并对其投资行为及结果承担全部责任。
              </p>
            </div>
          </Accordion>

          <Accordion
            title="隐私说明"
            desc="数据存储位置与采集范围"
            open={open === "privacy"}
            onToggle={() => setOpen(open === "privacy" ? null : "privacy")}
          >
            <div className="space-y-3 text-[13px] leading-relaxed text-ink-soft">
              <p>自托管部署下，全部业务数据（自选股、账号、验证码）存储在你自己的 PostgreSQL / SQLite 中，不上传第三方。</p>
              <p>浏览器仅在 localStorage 保存市场偏好（key：<span className="mono">horizon.market</span>），不含任何身份信息。</p>
              <p>
                平台不接入第三方统计、广告或行为追踪脚本。若你自行接入，请同步更新本说明并遵守当地隐私法规。
              </p>
              <p className="text-ink-faint">邮箱仅用于注册登录与验证码，不用于营销推送。</p>
            </div>
          </Accordion>

          <Accordion
            title="关于网页"
            desc={`Horizon 极目楚天 · v${VERSION}`}
            open={open === "about"}
            onToggle={() => setOpen(open === "about" ? null : "about")}
            last
          >
            <dl className="grid grid-cols-1 gap-x-8 gap-y-2.5 text-[13px] sm:grid-cols-2">
              <Row k="项目" v="Horizon 极目楚天（开源）" />
              <Row k="版本" v={VERSION} />
              <Row k="前端 / BFF" v="Next.js · TailwindCSS · Framer Motion · ECharts" />
              <Row k="后端" v="FastAPI · Celery · APScheduler" />
              <Row k="存储" v="PostgreSQL · Redis · SQLite（默认轻量部署）" />
              <Row k="许可协议" v="MIT" />
              <Row k="定位" v="个人金融数据学习与研究工具" />
              <Row
                k="仓库"
                v={
                  <a href={REPO} target="_blank" rel="noreferrer noopener" className="text-accent hover:opacity-70">
                    查看源码
                  </a>
                }
              />
            </dl>
            <p className="mt-4 text-[11px] leading-relaxed text-ink-faint">
              指标计算方式属于项目实现细节，不在前端展示。开源协议只授予代码使用权，不构成任何数据授权或投资建议。
            </p>
          </Accordion>
        </Card>

        <div className="flex flex-wrap items-center justify-between gap-3 px-1">
          <p className="text-[12px] text-ink-faint">
            未登录也可使用全部分析功能；账号仅在需要跨设备保存自选股时使用。
          </p>
          <Link href="/login" className="text-[13px] font-medium text-accent transition-opacity hover:opacity-70">
            账号登录 →
          </Link>
        </div>
      </div>
    </div>
  );
}

function Accordion({
  title,
  desc,
  open,
  onToggle,
  children,
  last,
}: {
  title: string;
  desc?: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  last?: boolean;
}) {
  return (
    <div className={clsx("px-5 sm:px-6", !last && "border-b border-black/[0.05]")}>
      <button type="button" onClick={onToggle} className="flex w-full items-center justify-between py-4 text-left">
        <span>
          <span className="block text-[14px] font-medium text-ink">{title}</span>
          {desc ? <span className="mt-0.5 block text-[11px] text-ink-faint">{desc}</span> : null}
        </span>
        <motion.span
          animate={{ rotate: open ? 45 : 0 }}
          transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
          className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-canvas-alt text-[13px] text-ink-mute"
        >
          +
        </motion.span>
      </button>
      <motion.div
        initial={false}
        animate={{ height: open ? "auto" : 0, opacity: open ? 1 : 0 }}
        transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
        className="overflow-hidden"
      >
        <div className="pb-5">{children}</div>
      </motion.div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-black/[0.04] pb-2">
      <dt className="shrink-0 text-ink-faint">{k}</dt>
      <dd className="text-right text-ink-soft">{v}</dd>
    </div>
  );
}