# =============================================================================
# Horizon 极目楚天 · 前端镜像（Next.js 15 / App Router）
# 三阶段构建：deps（依赖）→ builder（构建）→ runner（运行，非 root）
# 构建：在 web/ 目录执行  docker build -t horizon-web:local .
# =============================================================================
# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------- deps -------
FROM node:22-alpine AS deps
WORKDIR /app
# libc6-compat：部分预编译原生依赖在 alpine(musl) 下的兼容层
RUN apk add --no-cache libc6-compat
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# --------------------------------------------------------------- builder -----
FROM node:22-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# next.config.mjs 未启用 output:"standalone"，因此运行阶段需要 node_modules；
# 同时 public/ 目录当前可能尚不存在，先确保其存在，下面的 COPY 才不会失败。
RUN mkdir -p public \
 && npm run build \
 && npm prune --omit=dev

# ---------------------------------------------------------------- runner -----
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    TZ=UTC

RUN addgroup -g 10001 -S nodejs \
 && adduser -u 10001 -S -G nodejs nextjs

COPY --from=builder --chown=10001:10001 /app/public      ./public
COPY --from=builder --chown=10001:10001 /app/.next       ./.next
COPY --from=builder --chown=10001:10001 /app/node_modules ./node_modules
COPY --from=builder --chown=10001:10001 /app/package.json ./package.json
COPY --from=builder --chown=10001:10001 /app/next.config.mjs ./next.config.mjs

USER 10001:10001

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))]

# package.json 的 start 脚本为 next start -p 3000
CMD ["npm", "run", "start"]