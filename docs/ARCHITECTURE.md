# 架构说明 · Architecture

> 本文描述 Horizon（极目楚天）的**目标架构**与当前实现的边界。
> 接口清单以 [`API_CONTRACT.md`](API_CONTRACT.md) 为准；数据授权以 [`DATA_SOURCES.md`](DATA_SOURCES.md) 为准。

---

## 1. 总览

```text
                    ┌──────────────────────────────────────────┐
   浏览器  ────────► │  nginx :80                                │
                    │  /      → web:3000                        │
                    │  /api/  → api:8000   (保留 /api/v1 前缀)   │
                    └───────────────┬──────────────┬───────────┘
                                    │              │
                     ┌──────────────▼───┐   ┌──────▼─────────────┐
                     │ web  (Next.js 15)│   │ api (FastAPI)      │
                     │ SSR / RSC 视图层  │   │ /api/v1/* + /health│
                     └──────────────┬───┘   └───┬────────────┬───┘
                                    │ rewrites  │            │
                                    └──────────►│  providers │
                                                └──┬──────┬──┘
                                        ┌──────────▼─┐ ┌──▼──────────┐
                                        │ cache 层    │ │ Postgres /  │
                                        │ 内存 + Redis│ │ TimescaleDB │
                                        └────────────┘ └─────────────┘
                                                │
                                     ┌──────────▼───────────────────────┐
                                     │ 外部公开数据源                      │
                                     │ yahoo / akshare / synthetic 兜底   │
                                     └──────────────────────────────────┘
```

三层职责：

| 层 | 位置 | 职责 | 不做的事 |
| --- | --- | --- | --- |
| 视图层 | `web/` | 路由、SSR/RSC、图表渲染、交互状态 | 不直接请求第三方数据源，不持有密钥 |
| 接口层 | `api/app/routers/` | HTTP 契约、参数校验、鉴权、组装响应 | 不写数据源细节，不做长耗时计算 |
| 数据层 | `api/app/providers/` + `cache.py` + `db.py` | 数据获取、降级、缓存、持久化 | 不感知 HTTP 语义（不知 routes） |

依赖方向严格单向：`routers → providers/cache/db`，反向依赖视为设计缺陷。

---

## 2. 为什么存在 BFF 代理层

`web/next.config.mjs` 把 `/api/v1/:path*` 重写到 `API_INTERNAL_URL`（默认 `http://127.0.0.1:8000`）。这层薄代理（Backend-For-Frontend）不是多余的转发，它解决四个具体问题：

1. **同源与凭据**
   浏览器侧所有请求都发往 `http://<host>/api/v1/...`，与页面同源。于是 Cookie（`SameSite=Lax`）可以直接承载会话，不需要 `credentials: "include"` + 后端 `CORS` 白名单 + `Access-Control-Allow-Credentials` 的三方配平，也不需要为每个部署域名改 `CORS_ORIGINS`。

2. **内部拓扑不暴露**
   前端代码里不出现 `http://api:8000` 之类的内部主机名。容器编排怎么变（服务名、端口、sidecar），只需改 `API_INTERNAL_URL` 一个环境变量。

3. **SSR 与浏览器共用一条路径**
   Server Component 与客户端组件都用相对路径 `/api/v1/...`。服务端的 `rewrites` 会走容器内网，浏览器侧走 nginx —— 同一份 URL 两种解析，代码无需 `typeof window` 分支。

4. **可选的边缘增强点**
   需要时可在 `next.config.mjs` 或 `middleware.ts` 里集中做：认证前置、请求追踪头注入、灰度分流，而不必改动后端每个 router。

补充说明：

- 生产环境浏览器实际命中路径是 `nginx /api/ → api:8000`，`rewrites` 主要服务 `next dev` 与 SSR 内部调用；两条路径都最终落到同一组 `/api/v1/*`。
- FastAPI 自带文档 `/docs` 与 `/health` 位于**根路径**，不在 `/api/` 之下，因此 nginx 只显式放行 `location = /api/health`（映射到 `/health`），`/docs` 默认不对外暴露（见 `infra/nginx.conf` 中被注释的块）。这是有意的：生产环境不应公开调试文档。

---

## 3. 缓存与降级链

### 3.1 缓存分层

| 层 | 实现 | 生效范围 | 失效方式 |
| --- | --- | --- | --- |
| L1 进程内 | `api/app/cache.py` 的 `_mem` 字典 | 单 worker 进程 | TTL 到期 / 进程重启 |
| L2 共享 | Redis（`REDIS_URL` 非空时启用） | 多 worker、多副本 | TTL 到期 |
| L3 持久化 | Postgres / TimescaleDB | 日线、基本面、用户数据 | 显式写入 + 保留策略 |

`redis` 包与 `REDIS_URL` 都是**可选**的：未配置时自动退化为纯进程内缓存，功能不变、命中率下降。这一条决定了「无 Redis 也能跑」。

### 3.2 TTL 约定

`api/app/cache.py` 中的固定表（改这里之前请先想清楚下游影响）：

| key 类别 | TTL | 覆盖数据 |
| --- | --- | --- |
| `quote` | 60 s | 实时/准实时报价 |
| `daily` | 900 s | 日线与日频序列 |
| `fundamental` | 6 h | 财务与基本面快照 |
| `synthetic` | 3600 s | 合成/代理数据（确定性生成，稳定长 TTL） |
| `default` | 300 s | 未分类 |

原则：**TTL 必须大于等于上游数据自身的更新频率**，否则缓存只是把压力原样转发出去；同时 TTL 不得超过界面上宣示的 `asOf` 允许滞后，否则会出现「图表说最新，数据却是旧的」这类诚实性问题。

### 3.3 降级链

`api/app/providers/base.py` 的 `_chain(market)` 定义了确定性的尝试顺序与最终兜底：

| 市场 | 顺序 | 最终兜底 |
| --- | --- | --- |
| A 股（`cn`） | `akshare` → `yahoo` → `synthetic` | `synthetic` |
| 美股（`us`） | `yahoo` → `akshare` → `synthetic` | `synthetic` |

不变量（改动 provider 层时必须保持）：

- `get_bars` / `get_quote` / `search_symbols` **永不抛异常**；任一环节失败都继续下一个数据源，全链失败返回合成数据。
- 每个响应都带 `asOf` 与 `source`；走兜底时 `source == "synthetic"`，并在 `warnings[]` 中说明原因。
- 合成数据是**确定性**的（同输入同输出），并在 `provider_status()` 里以 `license` 文案明示「内置合成代理数据」，绝不伪装成真实行情。

```text
请求 ──► L1 内存 ──命中──► 返回
            │未命中
            ▼
        L2 Redis ──命中──► 回填 L1 → 返回
            │未命中
            ▼
    provider 链（按市场顺序）
            │ 任一源成功
            ├──────────► 规范化(Quote/Bar) + 标 source → 写缓存 → 返回
            │ 全部失败
            ▼
    synthetic 确定性生成 + warnings[] → 写缓存 → 返回
```

上游故障时用户看到的是**标注过的旧数据或代理数据**，而不是白屏或 500。这是「研究工具」在数据不可得时的正确行为：先给可解释的输出，再给诚实的标注。

### 3.4 后台任务（可选）

缓存预热与过期验证码清理由**可选**的 Celery worker 承担（`api/app/tasks.py`）。它与前台请求路径完全解耦：**worker 不启动时前台功能不受影响**，缓存只是退化为 L1 进程内 TTL。

| 层 / 组件 | 作用 | 缺失时的行为 |
| --- | --- | --- |
| L1 进程内 TTL 缓存（`api/app/cache.py` 的 `_mem`） | 每个 api 进程内的短期缓存，命中即返回 | 始终存在，无外部依赖 |
| L2 Redis（`REDIS_URL`） | 跨进程 / 跨副本共享缓存，并充当 Celery 的 broker 与 result backend | `REDIS_URL` 为空 ⇒ 只有 L1，且后台任务不启用 |
| Beat（`celery beat`，worker 以 `-B` 内嵌） | 按 `beat_schedule` 定时触发任务 | 无 celery / redis 包 ⇒ 所有定时任务不运行 |

`beat_schedule` 的调度项（4 个调度项 / 3 个任务类型）：

| 键 | 任务 | 时间（crontab） | 作用 |
| --- | --- | --- | --- |
| `warm-quotes` | `horizon.warm_quotes` | `minute="*/15"`（每 15 分钟） | 预热报价缓存，降低上游抖动对首屏的影响 |
| `warm-bars-us` | `horizon.warm_bars` | `hour="22", minute="30"`（每日 22:30） | 预热美股日线（400 天窗口） |
| `warm-bars-cn` | `horizon.warm_bars` | `hour="9", minute="30"`（每日 09:30） | 预热 A 股日线（400 天窗口） |
| `purge-codes` | `horizon.purge_verification_codes` | `hour="3", minute="0"`（每日 03:00） | 清理过期验证码记录 |

约束与说明：

- **无 Redis 时任务不启用，前台功能不受影响。** `api/app/tasks.py` 中 `REDIS = settings.redis_url or "redis://127.0.0.1:6379/0"`，但 `celery` / `redis` 是可选依赖（`api/requirements.txt` 中为注释状态）；未安装时导入该模块会 `raise SystemExit` 并打印中文安装指引。前台 API 不导入此模块，因此不受影响。
- **Redis 逻辑库隔离**：compose 中 api 的缓存用 db0，worker 通过覆盖 `REDIS_URL` 使用 db1，避免 Celery 的 task 结果键污染缓存键空间。
- **beat 单实例**：`celerybeat-schedule` 调度文件写入容器 `/app`（属主 10001），单实例部署用 `-B` 内嵌即可；多副本部署应拆分独立 beat 服务，避免同一任务被重复触发。
- 任务只做**数据预热与清理**，不包含任何交易、下单或资金操作。

---

## 4. 时序数据存储规划

### 4.1 现状

- 开发默认 `DATABASE_URL=sqlite:///./horizon.db`，零依赖即可启动。
- `api/app/db.py` 使用 SQLAlchemy 2.x（`DeclarativeBase`、`pool_pre_ping=True`）。
- 业务表（`api/app/models.py`）：`WatchlistItem`、`User`（表名 `app_user`）、`VerificationCode`。

### 4.2 生产目标：Postgres 16 + TimescaleDB

`infra/docker-compose.yml` 使用镜像 `timescale/timescaledb:latest-pg16`。规划如下：

| 数据 | 存储形态 | 说明 |
| --- | --- | --- |
| 日线/分钟线 | hypertable，按 `time` 分区 | chunk interval 建议 7 天（日线）或 1 天（分钟线） |
| 拥挤度/轮动得分 | hypertable，`(time, scope)` 复合维度 | 便于按板块/指标聚合回看 |
| 基本面快照 | 普通表 + `(symbol, asof)` 唯一约束 | 变更频率低，无需分区 |
| 原始响应报文 | 可选对象存储 / 宽表，短保留期 | 用于审计与回溯，可只保留 7–30 天 |

配套策略：

- **保留策略**：`add_retention_policy` 对原始 tick/分钟级数据设 90–180 天；日线与指标得分长期保留。
- **连续聚合**：用 continuous aggregate 预计算日/周/月粒度指标，前端只查聚合表，避免实时扫大表。
- **压缩**：对历史 chunk 开启列式压缩（`compress_segmentby = 'symbol'`，`compress_orderby = 'time DESC'`）。
- **幂等写入**：所有入库语句使用 `ON CONFLICT (symbol, time) DO UPDATE`，保证重复拉取不产生脏数据。
- **迁移**：表结构变更通过迁移脚本管理，禁止手改生产库；迁移前必须可回滚。

### 4.3 为什么开发用 SQLite 而生产不用

SQLite 适合单机、单写者、低并发的研究场景，启动成本为零；但它没有时间分区、并行查询与压缩能力，多 worker 并发写会锁库。因此形态是「SQLite 起步，TimescaleDB 上量」，两者共用同一套 SQLAlchemy 模型，切换只改 `DATABASE_URL`。

---

## 5. 请求生命周期（以拥挤度为例）

```text
GET /api/v1/crowding/score?market=us
   │
   ├─ nginx  location /api/  → api:8000   （保留完整 /api/v1 前缀）
   ├─ FastAPI router  crowding.py：参数校验（market、板块列表、窗口长度）
   ├─ 鉴权（AUTH_ENABLED=true 时校验 JWT；关闭时匿名放行）
   ├─ cache.cached(key="crowding:us:score", ttl=default)
   ├─ providers：取量价序列 → 计算 funding / pullback / anxiety / social / spread
   │             （固定权重 0.33 / 0.22 / 0.18 / 0.15 / 0.12）
   ├─ 组装响应：{ asOf, source, warnings[], components{}, score }
   └─ 返回；前端用 echarts 渲染，页脚固定展示「分析数据仅供研究参考」
```

---

## 6. 部署形态

| 组件 | 端口 | 对外 | 说明 |
| --- | --- | --- | --- |
| `nginx` | 80 | 是 | 唯一入口，反代 + 静态缓存 + 安全响应头 |
| `web` | 3000 | 仅本机（默认） | Next.js，`next start` |
| `api` | 8000 | 仅本机（默认） | uvicorn，非 root 运行 |
| `worker` | — | 否 | Celery，`profile: full` 时启用 |
| `postgres` | 5432 | 否 | 不映射宿主端口 |
| `redis` | 6379 | 否 | 不映射宿主端口 |

要点：

- 数据库与缓存默认**不暴露宿主端口**，只在内部网络可达。
- api/web 的宿主端口绑定 `127.0.0.1`，避免把无鉴权实例直接暴露到局域网/公网。
- 所有配置来自 `.env`（compose 用 `${VAR:-default}` 插值，缺省也能起）。

---

## 7. 安全边界

- 认证：JWT（`TOKEN_TTL_HOURS` 默认 72），`JWT_SECRET` 为空时进程内随机生成 —— 单进程可用，多副本部署必须显式设置，否则各副本签发的 token 互不承认。
- 关闭态：`AUTH_ENABLED=false` 时全部接口匿名可读，仅应在完全可信的内网使用。
- 邮件验证：仅当 `SMTP_HOST` 非空时启用，否则注册流程跳过验证码。
- 响应头：`X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: strict-origin-when-cross-origin`（见 `infra/nginx.conf`）。
- 凭据卫生：仓库内不含任何真实密钥；`.env` 已被 `.gitignore` 排除。

---

## 8. 现状与已知限制

### 8.1 已实现模块划分

> 早前版本此处写的是「7 个 router 均为占位」——该表述已不成立。7 个 router（meta / crowding /
> rotation / valuation / factor / options / auth）全部实现并接线，端到端冒烟（`scripts/smoke.ps1`）全部通过。
> 当前分层如下：

| 目录 | 职责 | 边界 / 约束 |
| --- | --- | --- |
| `api/app/routers/` | 只做 HTTP 层：路由、参数校验、响应装配 | 不放业务计算；响应统一带 `asOf` 与 `source` |
| `api/app/providers/` | 数据源降级链：us `yahoo → akshare → synthetic`，cn `akshare → yahoo → synthetic` | **永不抛错**；降级后 `source` 如实标注 |
| `api/app/scoring/` | 拥挤度五维加权（funding .33 / pullback .22 / anxiety .18 / social .15 / spread .12）与风格轮动 Z 分数 | `composite.py` 是行业清单 / 权重 / 分数带的唯一真相来源，权重固定不可改写 |
| `api/app/analytics/` | 价格序列装载与按交易日对齐、滚动统计（μ252 / σ252 等）、估值四维评分 | 窗口参数显式传入，不隐式缩短 |
| `api/app/backtest/` | 月度调仓（`_month_end_indices`）的横截面因子回测、因子挖掘与绩效指标 | 不使用未来数据；手续费默认 5bp 在调仓次日扣除；不含下单 |
| `api/app/options/` | Black-Scholes 定价（`bs_price`）、到期损益（payoff）、策略滚动回测 | 期权链的 bid/ask/iv 由模型 + 标的已实现波动率推演，`source = model:blackscholes-realised-vol` |
| `api/app/auth/` | 口令散列（pbkdf2_sha256 / 200k 轮）、HMAC 自签名令牌、邮件验证码（仅标准库 `smtplib`） | 默认 `AUTH_ENABLED=false`；关闭时 register / login / verify 返回 403 中文说明，`GET /api/v1/auth/config` 返回 `authEnabled:false`，分析功能无需登录 |

### 8.2 已知限制

1. **worker 的 `celery` / `redis` 为可选依赖**：`api/app/tasks.py` 已实现（预热 + 过期验证码清理），但 `api/requirements.txt` 中 celery、redis 仍是注释状态，默认镜像不含这两个包；需 `pip install celery redis`（或调整镜像）后执行 `celery -A app.tasks worker -B -l info` 才能启动，否则该模块会打印中文安装指引并以非零码退出（compose 已设 `restart: "no"`，见 §3.4）。
2. **前端无 `output: "standalone"`**：镜像沿用完整 `node_modules`，体积较大；若后续切换为 standalone 输出，需同步调整 `web/Dockerfile` 的 runner 阶段。
3. **部分数据品类依赖代理指标**：无合法免费接口的品类（暗池、13F 明细、社媒情感、搜索热度）以公开代理指标呈现并显式标注，详见 [`DATA_SOURCES.md`](DATA_SOURCES.md)。