import type { Metadata, Viewport } from "next";
import "./globals.css";
import { IslandNav } from "@/components/island-nav";
import { SiteFooter } from "@/components/site-footer";
import { MarketProvider } from "@/lib/market";

export const metadata: Metadata = {
  title: "极目楚天 · 市场分析",
  description: "开源的股票市场研究与分析工具（美股 / A 股）。数据仅供学习研究参考，不构成任何投资建议。",
  applicationName: "极目楚天",
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: "#FBFBFD",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-dvh font-sans">
        <MarketProvider>
          <IslandNav />
          <main className="mx-auto w-full max-w-[1180px] px-5 pb-16 pt-28 sm:px-8 sm:pt-32">{children}</main>
          <SiteFooter />
        </MarketProvider>
      </body>
    </html>
  );
}