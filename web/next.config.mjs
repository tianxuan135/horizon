/** @type {import("next").NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // BFF 代理目标：前端只与 /api/v1/* 通信，由 Next 转发到 FastAPI，密钥永不出服务端。
  async rewrites() {
    const target = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";
    return [{ source: "/api/v1/:path*", destination: `${target}/api/v1/:path*` }];
  },
};

export default nextConfig;