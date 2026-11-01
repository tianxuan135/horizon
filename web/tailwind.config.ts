import type { Config } from "tailwindcss";

/**
 * Apple 极简设计令牌。
 * 主色：纯白 / 浅灰；点缀：科技蓝（进攻）/ 警示红（贪婪）/ 深绿（恐慌）。
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#0A0A0B", soft: "#1D1D1F", mute: "#6E6E73", faint: "#A1A1A6" },
        canvas: { DEFAULT: "#FBFBFD", alt: "#F5F5F7", card: "#FFFFFF" },
        accent: { DEFAULT: "#0A84FF", soft: "#5AC8FA" },
        warn: "#FF3B30",
        greed: "#FF453A",
        attack: "#FF8A3D",
        neutral: "#FFB340",
        defend: "#8FD694",
        panic: "#1F8A4C",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Text",
          "Segoe UI",
          "PingFang SC",
          "Hiragino Sans GB",
          "Microsoft YaHei",
          "Noto Sans SC",
          "system-ui",
          "sans-serif",
        ],
        mono: ["SF Mono", "ui-monospace", "Menlo", "Consolas", "monospace"],
      },
      borderRadius: { island: "999px", card: "22px" },
      boxShadow: {
        island: "0 12px 34px -12px rgba(15, 18, 25, 0.28), 0 2px 8px -4px rgba(15, 18, 25, 0.12)",
        card: "0 1px 2px rgba(15, 18, 25, 0.04), 0 12px 28px -18px rgba(15, 18, 25, 0.35)",
        glass: "inset 0 1px 0 rgba(255,255,255,0.65)",
      },
      backdropBlur: { island: "22px" },
      transitionTimingFunction: { apple: "cubic-bezier(0.22, 1, 0.36, 1)" },
      keyframes: {
        "fade-up": { "0%": { opacity: "0", transform: "translateY(8px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
        shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } },
      },
      animation: { "fade-up": "fade-up 520ms cubic-bezier(0.22,1,0.36,1) both", shimmer: "shimmer 1.6s linear infinite" },
    },
  },
  plugins: [],
};

export default config;