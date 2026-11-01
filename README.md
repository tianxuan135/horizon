# Horizon · 极目楚天

> **English abstract.** Horizon is a self-hosted, open-source **financial research** web app for the
> US and China A-share markets. It bundles five analysis workbenches — market crowding, style rotation,
> valuation, factor strategies and options strategies — on a Next.js 15 frontend and a FastAPI backend,
> with a layered provider fallback chain (Yahoo / AKShare / deterministic synthetic data) and honest
> `source` labelling on every response. It is **research tooling only**: it ships **no** trading, order
> routing, signal-broadcasting or recommendation features, and nothing it outputs is investment advice.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB.svg)](api/requirements.txt)
[![Node](https://img.shields.io/badge/Node-22-339933.svg)](web/package.json)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000.svg)](web/package.json)
[![CI](https://github.com/tianxuan135/horizon/actions/workflows/ci.yml/badge.svg)](https://github.com/tianxuan135/horizon/actions/workflows/ci.yml)

---

## 目录

- [1. 项目简介](#1-项目简介)
- [2. 功能模块](#2-功能模块)
- [3. 架构图](#3-架构图)
- [4. 目录结构](#4-目录结构)
- [5. 快速开始](#5-快速开始)
  - [5.5 部署到公网](#55-部署到公网)
- [6. 环境变量](#6-环境变量)
- [7. 数据源与合规说明](#7-数据源与合规说明)
- [8. 界面预览：截图待补充](#8-界面预览截图待补充)
- [9. 贡献方式](#9-贡献方式)
- [10. 许可证](#10-许可证)
- [变更日志](https://github.com/tianxuan135/horizon/blob/main/CHANGELOG.md)
- [免责声明](#免责声明)

---

## 1. 项目简介

**Horizon（极目楚天）** 是一个可完全自托管的**金融研究**工具。它把散落在各处的公开行情与基本面数据，
整理成五个可交互的分析工作台，帮助你**观察市场结构**，而不是替你做交易决策。

设计取向：

| 取向 | 具体做法 |
| --- | --- |
| **研究优先** | 只提供分析视角与可视化，不提供下单、跟单、自动交易、荐股、喊单能力，且永不加入 |
| **数据诚实** | 每个响应都带 `asOf` 与 `source`；拿不到数据时回落到合成数据并显式标注 `source: "synthetic"`，**绝不伪装成真实行情** |
| **合规内建** | 不内置任何针对受保护站点的爬虫；凭据只来自环境变量；免费数据源有限频缓存，避免滥用 |
| **自有数据** | 自选股、账号、配置都存在你自己的数据库里；不向第三方回传，无遥测 |
| **开箱即用** | 不填任何密钥也能跑：无网络时以确定性合成数据演示全部界面 |

适用场景：个人投研、量化因子验证、教学演示、量化团队内部研究环境。
**不适用场景**：任何形式的实盘交易执行、投资顾问服务、面向公众的荐股内容生产。

技术栈：

- 前端 `web/` — Next.js 15（App Router）· React 19 · TypeScript（strict）· Tailwind CSS · ECharts / lightweight-charts
- 后端 `api/` — FastAPI · Pydantic v2 · SQLAlchemy 2 · NumPy / Pandas
- 存储 — SQLite（默认）/ PostgreSQL 16 + TimescaleDB（时序）/ Redis（可选缓存）
- 部署 — Docker Compose + nginx

---

## 2. 功能模块

前端为顶部悬浮岛式导航，路由与模块一一对应：

| # | 模块 | 前端路由 | 后端 API 前缀 | 一句话说明 |
| --- | --- | --- | --- | --- |
| 1 | **市场拥挤度** | `/` | `/api/v1/crowding` | 五维加权合成 0–100 拥挤度，识别资金拥挤与反转风险 |
| 2 | **风格轮动分析** | `/rotation` | `/api/v1/rotation` | 大小盘 / 价值成长相对强弱，Z-Score 标准化后映射为轮动分值 |
| 3 | **估值分析** | `/valuation` | `/api/v1/valuation` | 自选股估值指标 + 四维定性打分（基本面 / 护城河 / 可替代性 / 资本开支） |
| 4 | **因子策略分析** | `/factor` | `/api/v1/factor` | 因子回测（NAV / 基准 / 回撤 / Sharpe）与因子挖掘（IC / ICIR / t 值） |
| 5 | **期权策略分析** | `/options` | `/api/v1/options` | 期权链查询与策略损益曲线（单腿 / 蝶式 / 跨式 / 宽跨 / 备兑 / 领口） |
| — | **设置** | `/settings` | `/api/v1/meta` | 数据源状态、缓存与刷新、市场切换、界面偏好 |
| — | **账号** | `/login` | `/api/v1/auth` | 注册 / 登录 / 邮箱验证（邮件验证默认关闭） |

### 各模块要点

**市场拥挤度** 五维权重固定（`api/` 侧不可通过请求覆盖，保证口径可比）：

| 维度 | key | 权重 | 含义 |
| --- | --- | --- | --- |
| 资金拥挤度 | `funding` | 0.33 | 成交额 / 换手相对历史的拥挤程度 |
| 回撤压力 | `pullback` | 0.22 | 距近期高点的回撤与修复速度 |
| 恐慌程度 | `anxiety` | 0.18 | 波动率类指标（VIX 等）的抬升幅度 |
| 社媒情绪 | `social` | 0.15 | **代理指标**，公开情绪数据缺失时使用成交结构代理，并标注 proxy |
| 利差/价差 | `spread` | 0.12 | **代理指标**，暗池与真实买卖价差无合法免费来源，使用公开可得代理 |

输出标签：`attack`（偏进攻）/ `neutral`（中立）/ `defend`（偏防守）/ `panic`（恐慌），并始终附
`composite.index`（基准指数点位）便于对照。

**风格轮动** 公式在 API 响应中以 `formula` 字段原文回传，便于核对口径：

```
R(t)   = ln(A / B)                     相对净值
M10(t) = R(t) - R(t-10)                10 日动量
Z(t)   = (M10 - μ252) / σ252           252 日窗口标准化
score  = 100 * tanh(Z / 2)             压缩到 -100 ~ +100
```

**估值分析** 支持代码检索、自选股增删与拖拽排序；估值四维分为**模型给出的相对分**（0–100），
用于横向比较，**不代表目标价，也不构成买卖建议**。

**因子策略** 回测输出 `cagr / mdd / sharpe / vol / alpha / beta / winRate`；
因子挖掘输出 `ic / icir / tStat / turnover`。回测基于历史数据，**过去的统计结果不代表未来收益**。

**期权策略** 支持 `single / butterfly / straddle / strangle / covered_call / collar`；
损益曲线、最大盈亏、盈亏平衡点由腿组合推导，`maxProfit: null` 表示理论无限。

---

## 3. 架构图

### 3.1 运行时拓扑

```
                     ┌──────────────────────────────────────┐
                     │  浏览器（React 客户端组件，lang=zh-CN） │
                     └──────────────────┬───────────────────┘
                                        │ HTTP :80（唯一对外端口）
                     ┌──────────────────▼───────────────────┐
                     │  nginx   infra/nginx.conf             │
                     │    /            → web:3000            │
                     │    /_next/static → web:3000（长缓存）  │
                     │    /api/        → api:8000            │
                     │  gzip · 安全响应头 · 静态缓存          │
                     └───────┬──────────────────────┬────────┘
                             │                      │
            ┌────────────────▼───────┐   ┌──────────▼──────────────────┐
            │ web   :3000            │   │ api   :8000                 │
            │ Next.js 15 App Router  │   │ FastAPI + uvicorn           │
            │ SSR / 客户端组件       │   │ routers/（7 个路由模块）    │
            │ BFF：/api/v1/* rewrite │   │ cache.py  两级 TTL 缓存     │
            └────────────┬───────────┘   │ providers/ 数据源降级链     │
                         │ /api/v1/*     │ db.py     SQLAlchemy 2      │
                         └──────────────▶│ auth.py JWT+可选邮件验证    │
                                         └───┬─────────────────┬───────┘
                                             │                 │
                                  ┌──────────▼──────┐  ┌───────▼────────┐
                                  │ postgres :5432  │  │ redis :6379    │
                                  │ TimescaleDB(PG16│  │ 可选共享缓存   │
                                  └─────────────────┘  └────────────────┘
                                             ▲
                                  ┌──────────┴──────────┐
                                  │ worker(profile:full)│
                                  │ Celery 预热/清理    │
                                  └─────────────────────┘
```

### 3.2 数据源降级链

任何取数请求都沿链查找，**永不抛错**，最终必定返回可渲染的数据并如实标注来源：

```
  market = "us"                          market = "cn"
  ┌──────────────┐                       ┌──────────────────┐
  │ Yahoo Finance│                       │ AKShare（MIT）    │
  └──────┬───────┘                       └────────┬─────────┘
         │ 失败/未启用                             │ 失败/未安装
  ┌──────▼───────┐                       ┌────────▼─────────┐
  │ AKShare      │                       │ Yahoo Finance     │
  └──────┬───────┘                       └────────┬─────────┘
         │ 失败/未安装                             │ 失败/未启用
         └───────────────┬───────────────────────┘
                         ▼
              ┌────────────────────────┐
              │ synthetic 确定性合成数据 │  ← source: "synthetic" + warnings[]
              │ （仅供演示，非真实行情） │
              └────────────────────────┘
```

两级缓存：进程内 TTL（默认）+ 可选 Redis（`REDIS_URL`）。缓存既提速，也是**合规手段**——
对免费数据源做限频，避免被判定为滥用。详见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

---

## 4. 目录结构

```
horizon/
├── LICENSE                      # MIT
├── README.md                    # 本文件
├── CONTRIBUTING.md              # 贡献指南（含禁止事项）
├── SECURITY.md                  # 漏洞上报与密钥泄露处置
├── CODE_OF_CONDUCT.md           # 行为准则
├── .env.example                 # 环境变量模板（唯一可提交的 env 文件）
├── .gitignore
├── Makefile                     # Windows 亦可用的常用目标
│
├── api/                         # FastAPI 后端
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py              # 应用入口、CORS、路由挂载、/health
│       ├── config.py            # pydantic-settings，全部配置来自环境变量
│       ├── db.py                # SQLAlchemy 引擎 / Session / 建表
│       ├── models.py            # watchlist_item / app_user / verification_code
│       ├── cache.py             # 进程内 TTL + 可选 Redis
│       ├── providers/           # 数据源适配层
│       │   ├── base.py          # Provider 协议 + 降级链 + provider_status()
│       │   ├── yahoo.py         # Yahoo 公开图表接口
│       │   ├── akshare_provider.py
│       │   └── synthetic.py     # 确定性合成兜底（恒标注 synthetic）
│       └── routers/             # meta / crowding / rotation / valuation
│                                # factor / options / auth
│
├── web/                         # Next.js 15 前端
│   ├── Dockerfile
│   ├── package.json
│   ├── next.config.mjs          # BFF rewrite → API_INTERNAL_URL
│   ├── tailwind.config.ts
│   ├── tsconfig.json            # strict: true
│   ├── app/                     # App Router 页面
│   ├── components/              # island-nav / site-footer 等
│   └── lib/                     # 客户端工具与数据 hooks
│
├── infra/
│   ├── docker-compose.yml       # web / api / worker / postgres / redis / nginx
│   └── nginx.conf               # 反代 + gzip + 静态缓存 + 安全头
│
└── docs/
    ├── API_CONTRACT.md          # v1 接口契约（唯一事实来源）
    ├── ARCHITECTURE.md          # 分层、BFF、缓存与降级、时序存储规划
    ├── DATA_SOURCES.md          # 数据源合规矩阵
    └── screenshots/             # 界面截图（见 §8，待补）
```

---

## 5. 快速开始

### 前置条件

| 方式 | 需要 |
| --- | --- |
| Docker Compose | Docker Engine 24+ / Docker Desktop（含 compose v2） |
| 本地开发 | Python **3.12+**、Node.js **22+**、npm |

### 5.1 方式一：Docker Compose 一键启动（推荐）

```bash
# 1) 准备环境变量
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
# 编辑 .env，至少修改 POSTGRES_PASSWORD 与 JWT_SECRET（见 §5.3）

# 2) 启动（在仓库根目录执行；--env-file 让 compose 读取根目录的 .env）
docker compose --env-file .env -f infra/docker-compose.yml up -d --build

# 3) 查看状态与日志
docker compose -f infra/docker-compose.yml ps
docker compose -f infra/docker-compose.yml logs -f api

# 4) 访问
#    界面     http://localhost
#    健康检查 http://localhost/api/health   （nginx 自身存活：/healthz）
#    API 文档 默认不经 nginx 暴露；本机直连 http://127.0.0.1:8000/docs
#             （如需对外，取消 infra/nginx.conf 末尾 /docs 两行 location 的注释）
```

可选：启用 Celery worker（数据预热 / 过期验证码清理）

`worker` 使用 compose 的 `full` profile，默认**不**启动；它只做**数据预热**与**过期验证码清理**，
不含任何交易 / 下单逻辑。

```bash
# 1) 只单独拉起 worker（api / web / nginx 已在运行时）
docker compose -f infra/docker-compose.yml --profile full up -d worker

# 2) 或一次性带 worker 启动整套
docker compose --env-file .env -f infra/docker-compose.yml --profile full up -d --build
```

本地开发（不经 Docker，需先装可选依赖）：

```bash
cd api
pip install celery redis        # 可选依赖，不在 requirements.txt 默认安装范围内
celery -A app.tasks worker -B -l info
```

- `-B` 表示内嵌 beat，按 `api/app/tasks.py` 的 `beat_schedule` 定时触发：报价每 15 分钟、
  美股日线 22:30、A 股日线 09:30、过期验证码清理 03:00。
- 未安装 `celery` / `redis` 时，`app/tasks.py` 会打印中文安装指引并退出，前台 API 不受影响。
- 无 `REDIS_URL` 时后台任务不启用，前台功能照常（缓存退化为进程内 TTL）。

停止与清理：

```bash
docker compose -f infra/docker-compose.yml down            # 停止，保留数据卷
docker compose -f infra/docker-compose.yml down -v         # 停止并删除数据卷（会丢数据）
```

### 5.2 方式二：本地开发（不经 Docker）

两个终端，或直接用 `make dev-api` / `make dev-web`。

**终端 A — 后端**

```bash
cd api
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
# 仅当使用 PostgreSQL 时需要：
# pip install "psycopg[binary]"

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

后端起来后：`http://127.0.0.1:8000/health`、`http://127.0.0.1:8000/docs`。

**终端 B — 前端**

```bash
cd web
npm ci
npm run dev
```

界面：`http://localhost:3000`。前端的 `/api/v1/*` 由 `next.config.mjs` 的 rewrite 转发到
`API_INTERNAL_URL`（默认 `http://127.0.0.1:8000`），因此**浏览器只与 3000 端口同源通信**。

**不填任何密钥也能跑**：`DATABASE_URL` 默认 SQLite，数据源开关默认开启但不可用时自动降级为
`synthetic` 合成数据，界面与图表全部可交互——响应中的 `source` 字段会如实告诉你当前是演示数据。

### 5.3 部署前检查清单

| # | 检查项 | 命令 / 做法 |
| --- | --- | --- |
| 1 | `JWT_SECRET` 已设置且足够随机 | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| 2 | `POSTGRES_PASSWORD` 已改为强随机值 | 不要保留 `.env.example` 里的默认占位值 |
| 3 | `ENV=production` | 关闭开发期行为 |
| 4 | 公网必须显式设 `AUTH_ENABLED=true` | 默认值为 `false`（匿名只读），公网实例不要沿用默认值 |
| 5 | `CORS_ORIGINS` 只列可信来源 | 不要用 `*` 搭配 `allow_credentials` |
| 6 | 只暴露 nginx 的 80/443 | 不要对公网映射 8000 / 5432 / 6379 |
| 7 | `.env` 未被跟踪 | `git check-ignore -v .env` 应有输出 |
| 8 | 已读 [`SECURITY.md`](SECURITY.md) | 了解密钥泄露处置流程 |
| 9 | 端到端冒烟通过 | `powershell -ExecutionPolicy Bypass -File scripts/smoke.ps1`，末行应为 `ALL PASS`（见 §5.4） |

### 5.4 端到端验证（冒烟测试）

仓库自带只读冒烟脚本 `scripts/smoke.ps1`，按固定顺序逐项调用本项目自己的 API：
[1] meta / 健康检查 → [2] 市场拥挤度 → [3] 风格轮动 → [4] 估值 → [5] 因子 → [6] 期权 → [7] 账号。
**它只调用本项目自己的 API，不访问任何第三方付费接口**，因此可放心在本地与 CI 中执行。

```powershell
# 终端 1：启动后端
cd api
uvicorn app.main:app --port 8000

# 终端 2：启动前端（生产构建，监听 3000）
cd web
npm run start

# 终端 3：跑冒烟
powershell -ExecutionPolicy Bypass -File scripts/smoke.ps1
```

- 默认目标 `http://127.0.0.1:8000`；换端口用 `-Base`：
  `powershell -ExecutionPolicy Bypass -File scripts/smoke.ps1 -Base http://127.0.0.1:8010`
- 正常输出末尾为 `共 41 项检查：PASS 41 / FAIL 0` 与 `ALL PASS`；`-WriteTests` 会多加 2 项写操作（会改动本地 `api/horizon.db`），即 43 项。任一项失败即以非 0 退出码结束，可直接作为 CI 判定条件。
- 脚本校验的是 HTTP 契约（状态码 + 关键字段是否存在），不评价数值的投资含义。

---

### 5.5 部署到公网

自托管（Docker + Nginx）与托管平台都能跑，下面是以「前端 Vercel + 后端 Render / Fly.io + 托管 PostgreSQL / Redis」为例的公网方案，全程免费额度即可试用。

| 组件 | 推荐托管 | 说明 |
| --- | --- | --- |
| 前端 Web | Vercel | 直接连 GitHub 仓库，自动构建；Root Directory 设为 `web` |
| 后端 API | Render / Fly.io | 用 `api/Dockerfile` 构建（镜像已内置 `psycopg` / `celery` / `redis`） |
| PostgreSQL | Neon / Supabase / Render PG | 免费额度足够个人研究使用，务必启用 SSL |
| Redis | Upstash | 可选：仅用于跨副本缓存与后台任务 |
| 后台任务 | Render Background Worker | 可选：`celery -A app.tasks worker -B -l info`，未启用不影响前台 |

#### ⚠️ 公网部署三条硬红线

1. **必须显式设 `AUTH_ENABLED=true`**（默认 `false` 是给「只在本机看数据」的开源默认值）。开启后 `/api/v1/auth/*` 才会真正注册与签发令牌。
2. **必须显式设 `JWT_SECRET`**（≥32 字节随机串）。不设时进程会自动生成并写入 `.horizon_secret`，**多副本之间签名不一致、重启后旧令牌立即失效**。
3. **`CORS_ORIGINS` 必须填前端真实域名**（如 `https://horizon.example.com`），不要保留默认的 `http://localhost:3000`。

生成随机密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

#### 步骤 1 · 准备数据库

在 Neon / Supabase 建库后拿到连接串，把 `sslmode=require` 补齐：

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DBNAME?sslmode=require
```

表结构在 API 启动时自动创建（`api/app/main.py` 的 lifespan 调用 `init_db()`），首次启动无需手工迁移。

#### 步骤 2 · 准备 Redis（可选）

```dotenv
REDIS_URL=rediss://default:PASSWORD@HOST:6379
```

Redis 同时承担 L2 缓存与 Celery broker（`db1`）；不配置时自动退回进程内缓存，功能不受影响，只是每个副本各存一份。

#### 步骤 3 · 部署 API（Render 示例）

1. New → **Web Service** → 选择本仓库 → Runtime 选 **Docker**，Dockerfile Path 填 `api/Dockerfile`。
2. Health Check Path 填 `/health`。
3. 环境变量（Environment）：

```dotenv
ENV=production
DATABASE_URL=postgresql+psycopg://...
REDIS_URL=rediss://...
CORS_ORIGINS=https://<你的前端域名>
AUTH_ENABLED=true
JWT_SECRET=<上一步生成的 48 字节随机串>
TOKEN_TTL_HOURS=72
# 数据源：不填则自动降级为 synthetic；A 股可选安装 akshare
YAHOO_ENABLED=true
AKSHARE_ENABLED=false
# 需要邮件验证码时再配（不配则注册即生效）
# SMTP_HOST=  SMTP_PORT=587  SMTP_USER=  SMTP_PASSWORD=  SMTP_FROM=
```

4. 部署完成后访问 `https://<api 域名>/health`，应返回 `{"ok": true, ...}`。
5. **`/docs` 不对公网开放**：托管平台上不会经过 `infra/nginx.conf`，若不想暴露 Swagger，请设 `ENV=production` 并在平台层做访问限制（或加 IP 白名单）。排查问题时再临时开放。

> Fly.io 等价做法：`fly launch --dockerfile api/Dockerfile`，用 `fly secrets set` 注入上面的变量；`fly.toml` 的 `[http_service]` 里把 health check 指向 `/health`。

#### 步骤 4 · 部署 Web（Vercel 示例）

1. Vercel → Add New Project → 导入同一仓库 → **Root Directory 选择 `web`**，Framework 自动识别为 Next.js。
2. 环境变量：

```dotenv
# 服务端 BFF 代理目标，必须是 Vercel 能访问到的 API 公网地址（不要填 127.0.0.1）
API_INTERNAL_URL=https://<api 域名>
# 设置页「问题反馈」要用到的仓库地址
NEXT_PUBLIC_REPO_URL=https://github.com/<你的用户名>/horizon
NEXT_PUBLIC_APP_VERSION=0.1.0
```

3. 部署完成后打开首页：浏览器只与同域的 `/api/v1/*` 通信，由 Next 的 rewrite 转发到 API，**任何密钥都不会进入前端**。

> 如果你希望前端直连 API（不走 BFF），需要额外把 `CORS_ORIGINS` 加上前端域名，并在 `web/lib/api.ts` 里改基地址——默认配置不需要这一步。

#### 步骤 5 · 上线自检清单

- [ ] `GET https://<api>/health` 返回 `ok: true`
- [ ] 首页各模块右上角显示「数据 YYYY-MM-DD（周x）HH:MM」，且 `source` 不是 `synthetic`（否则说明数据源没通，页面会如实在「数据状态」里标注）
- [ ] 设置页「数据状态」表格能打开，代理指标有来源说明
- [ ] 注册 → 登录 → 刷新后仍保持登录（令牌存于 `localStorage["horizon.token"]`）
- [ ] 期权计算器能算出最大收益/最大风险，金额标注为「1 张 = 100 股」
- [ ] 页脚与设置页的免责声明完整显示
- [ ] `/docs`、`/openapi.json` 未对公网裸露（或已加访问限制）

#### 成本与合规提醒

- 免费额度：Vercel Hobby + Render Free + Neon Free + Upstash Free 足以支撑个人研究；Render 免费实例会休眠，首次请求有冷启动延迟。
- yfinance 是公开但非官方承诺的接口，AKShare 依赖各站点结构；**公网高频访问前请自行评估各数据源的使用条款**，并依赖后端内置的 TTL 缓存（行情 60s / 日线 900s / 基本面 6h）与并发上限控制请求量。
- 本项目的定位是「个人金融数据学习与研究工具」：**不要**在此基础上增加荐股、带单、自动交易或收益承诺类功能，也不要删除免责声明。

---
## 6. 环境变量

所有配置均通过环境变量注入，代码中**没有任何硬编码密钥**。变量名与
`api/app/config.py` 的字段同名大写，**无额外前缀**。

### 6.1 后端（`api/`）

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `ENV` | 否 | `development` | 运行模式：`development` / `production` |
| `API_HOST` | 否 | `0.0.0.0` | 监听地址（容器内须为 `0.0.0.0`） |
| `API_PORT` | 否 | `8000` | 监听端口 |
| `CORS_ORIGINS` | 否 | `http://localhost:3000,http://127.0.0.1:3000` | 允许跨域的来源，英文逗号分隔 |
| `DATABASE_URL` | 否 | `sqlite:///./horizon.db` | SQLAlchemy 连接串；生产建议 `postgresql+psycopg://…`。默认落盘到 `api/horizon.db`（自选股与账号），已写入 `.gitignore`，**绝不可提交** |
| `REDIS_URL` | 否 | *（空）* | 留空 = 仅进程内缓存、后台任务不启用；多副本或启用 worker 时填写 |
| `YAHOO_ENABLED` | 否 | `true` | 启用 Yahoo 公开图表接口 |
| `AKSHARE_ENABLED` | 否 | `true` | 启用 AKShare（未安装库则自动不可用） |
| `TUSHARE_TOKEN` | 否 | *（空）* | Tushare 凭据，留空即不启用；**严禁提交** |
| `FINNHUB_KEY` | 否 | *（空）* | Finnhub 凭据，留空即不启用；**严禁提交** |
| `AUTH_ENABLED` | 否 | `false` | 是否启用账号体系；**默认关闭**（开源自托管默认匿名只读），由部署者显式设 `true` |
| `TOKEN_TTL_HOURS` | 否 | `72` | 登录 Token 有效期（小时） |
| `JWT_SECRET` | **生产必填** | *（空 → 自动生成持久化密钥）* | 留空时首次启动自动生成并写入 `api/.horizon_secret`（已写入 `.gitignore`，**绝不可提交**），重启后已签发令牌仍有效；**多副本 / 容器化部署必须显式设置**，否则各副本密钥不同、令牌无法互认 |
| `SMTP_HOST` | 否 | *（空）* | 空 = 关闭邮件验证；非空则注册要求验证码 |
| `SMTP_PORT` | 否 | `587` | SMTP 端口 |
| `SMTP_USER` | 否 | *（空）* | SMTP 用户名 |
| `SMTP_PASSWORD` | 否 | *（空）* | SMTP 口令；**严禁提交** |
| `SMTP_FROM` | 否 | `no-reply@horizon.local` | 发件人地址（占位值可直接用） |

> ⚠️ **两个运行时产物绝不能进仓库**（`.gitignore` 已覆盖）：`api/.horizon_secret`（未设 `JWT_SECRET` 时
> 自动生成的持久化令牌签名密钥）与 `api/horizon.db`（本地 SQLite 业务库，含自选股与账号）。
> 密钥一旦泄露，按 [`SECURITY.md`](SECURITY.md) 的处置流程处理：先吊销、再换新、最后才清理历史。

### 6.2 前端（`web/`）

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `API_INTERNAL_URL` | 否 | `http://127.0.0.1:8000` | BFF rewrite 目标。Docker 内为 `http://api:8000` |

### 6.3 Docker Compose 附加变量（`infra/docker-compose.yml`）

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `POSTGRES_DB` | 否 | `horizon` | 初始数据库名 |
| `POSTGRES_USER` | 否 | `horizon` | 数据库用户 |
| `POSTGRES_PASSWORD` | **是** | *（占位）* | 数据库口令，请务必修改 |
| `NGINX_PORT` | 否 | `80` | nginx 对外端口（唯一对外入口） |
| `API_PUBLISHED_PORT` | 否 | `8000` | api 在宿主机的绑定端口，**仅绑定 127.0.0.1**，供本机调试 |
| `WEB_PUBLISHED_PORT` | 否 | `3000` | web 在宿主机的绑定端口，**仅绑定 127.0.0.1**，供本机调试 |

> `worker`（`profile: full`）的 broker / result backend 取自 `REDIS_URL`；compose 内已把它指向
> `redis://redis:6379/1`，与 api 的缓存库（db0）隔离。

> ⚠️ **切勿把 .env 提交到公开仓库。** 仓库只提交 `.env.example`，且其中所有值均为空或安全默认。

---

## 7. 数据源与合规说明

完整矩阵（来源 / 类型 / 是否免费 / 授权与条款风险 / 用途 / 降级替代）见
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md)。

### 7.1 默认数据源

| 数据源 | 类型 | 费用 | 主要用途 | 降级 |
| --- | --- | --- | --- | --- |
| Yahoo Finance 公开图表接口 | 公开接口 | 免费 | 美股/指数日线与报价 | → AKShare → synthetic |
| AKShare（MIT 开源） | 开源库 | 免费 | A 股日线与列表检索 | → Yahoo → synthetic |
| Tushare（可选） | 需注册 | 免费额度受限 | 补充 A 股基本面 | 未配置则不启用 |
| Finnhub（可选） | 需注册 | 免费额度受限 | 补充美股基本面/新闻 | 未配置则不启用 |
| 内置 synthetic | 确定性生成 | 免费 | 离线演示与兜底 | —（链末） |

### 7.2 合规原则（硬约束）

1. **不做受保护站点的爬虫。** 只接入公开接口与开源库，不绕过任何访问控制、不破解验证码。
2. **代理指标必须显式标注。** 暗池成交、13F 明细、Reddit / 雪球社媒情感、Google Trends 等
   **没有合法免费接口**的数据，本项目一律使用**公开代理指标**，并在响应中标注
   `source`（含 `synthetic` / `proxy`）与 `warnings[]`，**绝不伪装为真实数据**。
3. **凭据只在服务端。** 任何数据源密钥只存在于后端环境变量，前端代码与构建产物中不出现。
4. **限频即合规。** 缓存 TTL 与请求节流是使用免费数据源的必要条件，不是可选项。
5. **不构成投资建议。** 所有指标、分值、回测与损益曲线均为研究参考。
6. **付费数据源凭据禁止入库。** 详见 [`CONTRIBUTING.md`](CONTRIBUTING.md) 的禁止事项。

### 7.3 数据时效与可信度

每个响应都包含：

- `asOf` — 本次计算所用数据的时间（UTC，ISO 8601）
- `source` — 实际生效的数据来源标识；`synthetic` 表示演示数据
- `warnings[]` — 例如「数据源不可达，已降级为合成数据」

在「设置」页可以查看各数据源的实时可用性与延迟，**请在使用任何分析结论前先确认 `source`**。

---

## 8. 界面预览：截图待补充

> 📌 **截图待补充**（`docs/screenshots/` 为占位路径，本地启动后截图即可，勿提交含个人持仓/账户的截图）。
>
> 下表列出的是**约定的目录与文件名**，目前 `docs/screenshots/` 内只提交了 `.gitkeep`——
> 路径是纯文本约定而非图片链接，因此不存在失效（坏链）问题，图片会在后续提交中补入。
>
> 截图规格建议：1280×800 以上、浅色主题、**不含任何真实账号 / 邮箱 / 持仓 / 付费数据**。

| 模块 | 截图路径 | 状态 |
| --- | --- | --- |
| 市场拥挤度（首页总览） | `docs/screenshots/01-crowding.png` | 待补充 |
| 市场拥挤度（五维分解） | `docs/screenshots/02-crowding-dimensions.png` | 待补充 |
| 风格轮动分析 | `docs/screenshots/03-rotation.png` | 待补充 |
| 估值分析（自选股 + 四维评分） | `docs/screenshots/04-valuation.png` | 待补充 |
| 因子策略（回测净值曲线） | `docs/screenshots/05-factor-backtest.png` | 待补充 |
| 期权策略（损益曲线） | `docs/screenshots/06-options-payoff.png` | 待补充 |
| 设置 / 数据源状态 | `docs/screenshots/07-settings.png` | 待补充 |
| 账号登录 | `docs/screenshots/08-login.png` | 待补充 |
| 移动端布局 | `docs/screenshots/09-mobile.png` | 待补充 |

---

## 9. 贡献方式

欢迎 Issue 与 Pull Request。开始之前请阅读：

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — 开发环境、代码风格、分支与 PR 流程、**禁止事项**
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — 行为准则
- [`SECURITY.md`](SECURITY.md) — 漏洞请**私下**上报，不要公开 Issue

快速路径：

```bash
git checkout -b feat/your-feature
# … 开发，保持 TS strict 与 Python 类型注解 …
git commit -m "feat(crowding): 增加五维分解图"
git push origin feat/your-feature
```

提交前请确认：无硬编码密钥、无真实数据源凭据、**未加入任何荐股 / 带单 / 自动交易功能**。

---

提交前请同步更新 [`CHANGELOG.md`](https://github.com/tianxuan135/horizon/blob/main/CHANGELOG.md) 的 `[未发布]` 小节。

## 10. 许可证

本项目基于 [MIT License](LICENSE) 发布。
Copyright (c) 2025 Horizon (极目楚天) contributors。

第三方组件遵循各自许可：Next.js（MIT）、FastAPI（MIT）、AKShare（MIT）、
以及 `web/package.json`、`api/requirements.txt` 中列出的全部依赖。
接入任何数据源前，请自行核对其**服务条款**与再分发限制，详见
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md)。

---

## 免责声明

> **本工具所有数据及分析结果仅供学习研究参考，不构成任何投资建议。**

本项目为开源研究工具，不提供投资咨询、不代客理财、不推荐任何具体证券，
亦不构成任何形式的要约或承诺。数据可能延迟、缺失或由合成代理数据代替（以响应中的
`source` 字段为准），据此作出的任何决策及其后果由使用者自行承担。
投资有风险，决策需谨慎；如需投资建议，请咨询具备相应资质的持牌机构。
