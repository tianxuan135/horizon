# 贡献指南 · Contributing to Horizon 极目楚天

感谢你愿意参与 Horizon（极目楚天）。

Horizon 是一个**自托管的金融研究工具**，目标是让研究者在自己的机器上，用可审计的数据与公式，复现市场结构类指标（拥挤度、风格轮动、估值分位、因子与期权损益等）。

它不是交易系统，也不提供任何投资建议。这个定位决定了本项目的贡献边界：**凡是把研究工具变成荐股、带单或自动交易系统的改动，都不会被合并。**

---

## 目录

- [0. 三条红线（先读这一段）](#0-三条红线先读这一段)
- [1. 开发环境](#1-开发环境)
- [2. 目录约定](#2-目录约定)
- [3. 代码风格](#3-代码风格)
- [4. 分支模型与 PR 流程](#4-分支模型与-pr-流程)
- [5. Commit 约定](#5-commit-约定)
- [6. 新增数据源的特殊要求](#6-新增数据源的特殊要求)
- [7. 评审清单](#7-评审清单)
- [8. 文档与本地化](#8-文档与本地化)
- [9. 联系方式](#9-联系方式)

---

## 0. 三条红线（先读这一段）

以下三条是**硬性禁止项**。违反其中任何一条的 PR 会被直接关闭，已合并的会被回退。

### 0.1 禁止硬编码密钥

- 任何密钥、令牌、口令、私钥、cookie、session id **只能**通过环境变量注入。
- 前端代码里的密钥等同于公开密钥：`NEXT_PUBLIC_*` 前缀的变量会被打进浏览器包，**绝不允许**放置任何敏感值。
- 提交前自查：

  ```powershell
  git diff --cached | Select-String -Pattern "sk-|api[_-]?key|secret|token|password|BEGIN [A-Z ]*PRIVATE KEY"
  ```

- 误提交后请不要自行 `git commit --amend` 了事——按 [SECURITY.md](SECURITY.md) 的「密钥泄露处置流程」处理，因为一旦推送，值就已经泄露了。

### 0.2 禁止提交任何付费数据源凭据

- 不支持、也不接受把付费或授权受限的数据源凭据（Tushare Pro token、Wind/Choice 账号、各类商业行情 API key 等）写进仓库、示例配置、测试夹具或 Issue 附件。
- `.env.example` 里所有凭据位必须留空，只保留说明文字。
- 不要在测试中用真实 token 请求真实商业接口；请 mock，或使用内置 `synthetic` 合成数据源。
- 若某功能只有在付费数据源下才可用，请在 PR 描述中说明，并把默认路径保持为「公开数据源或 synthetic 降级」，**不允许**出现「没有 token 就无法启动」的情况。

### 0.3 禁止加入荐股、带单、自动交易功能

以下改动一律不接受：

- 个股买卖建议、目标价、评级、看好/看空结论；
- 模拟盘之外的自动下单、跟单、带单、信号推送群、交易 API 对接（券商/交易所下单接口）；
- 「买入信号」「抄底提示」类文案，以及任何以收益率承诺为目的的营销页面；
- 把研究指标包装成投资建议的话术（包括页脚、弹窗、报告导出模板里的表述）。

可以接受的相邻功能：指标计算、历史回测、组合风险统计、图表展示、数据导出。**产出是「事实与统计」，不是「该买什么」。**

---

## 1. 开发环境

| 组件 | 版本要求 | 说明 |
| --- | --- | --- |
| Node.js | **22 LTS 或更高** | 前端使用 Next.js 15 App Router |
| npm | 随 Node 提供 | 使用 `npm ci`，仓库内有 `package-lock.json` |
| Python | **3.12 或更高** | 后端 FastAPI，推荐 3.12 / 3.13 |
| Docker + Compose | 可选，推荐 | 一键起全栈（含 Postgres / Redis / nginx） |
| GNU make | 可选 | Windows 可用 `winget install ezwinports.make` |

### 后端

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # macOS / Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- 无 `.env` 也能启动：默认使用本地 SQLite + 内存缓存 + 数据源自动降级。
- 接口文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

### 前端

```powershell
cd web
npm ci
npm run dev        # http://localhost:3000
```

前端通过 `next.config.mjs` 的 `rewrites` 把 `/api/v1/*` 代理到 `API_INTERNAL_URL`（默认 `http://127.0.0.1:8000`），因此浏览器侧不需要额外的跨域配置。

### 全栈

```powershell
copy .env.example .env     # 然后按需填写，全部留空也可运行
make up                    # 等价于 docker compose --env-file .env -f infra/docker-compose.yml up -d --build
```

---

## 2. 目录约定

```text
horizon/
├─ api/                 FastAPI 后端（app/main.py、app/routers、app/providers）
├─ web/                 Next.js 15 前端（app/、components/、lib/）
├─ infra/               docker-compose.yml、nginx.conf
├─ docs/                API_CONTRACT.md、ARCHITECTURE.md、DATA_SOURCES.md
└─ .github/             Issue / PR 模板
```

- 前端页面放在 `web/app/<route>/page.tsx`，共享逻辑放 `web/lib/`，可复用 UI 放 `web/components/`。
- 后端每个业务域一个 router：`api/app/routers/<domain>.py`，路由前缀固定 `/api/v1/<domain>`。
- 外部数据访问**只允许**出现在 `api/app/providers/`；router 层不得直接 `httpx.get` 第三方接口。
- 任何新增/修改的接口，必须同步更新 `docs/API_CONTRACT.md`。

---

## 3. 代码风格

### 前端（TypeScript）

- `tsconfig.json` 已开启 `"strict": true`，**不要**为了过编译而加 `any` 逃逸；确需逃逸请用 `unknown` + 类型守卫，或写窄化的局部类型。
- 不关闭 `eslint` 规则来「让 CI 变绿」；如认为规则不合理，请单开 Issue 讨论。
- 组件默认 Server Component；需要 `useState` / `useEffect` / 事件处理时才加 `"use client"`，并把 `"use client"` 下沉到最小的叶子组件。
- 图表相关的第三方库（echarts / lightweight-charts）必须走动态导入或客户端组件，避免被打进首屏服务端包。
- 样式使用 Tailwind 的既有设计 token（`ink / canvas / accent / warn / greed / attack / neutral / defend / panic`、`rounded-island`、`rounded-card`），不要新造硬编码十六进制色值。
- 时间与数字格式化集中在 `web/lib/`，禁止在组件里散落 `toFixed(2)`。

### 后端（Python）

- 目标 Python 3.12+ 语法；**所有公开函数、方法、模块级常量都要有类型注解**。
- 遵循 PEP 8，行宽 100；字符串统一双引号；导入用 `from __future__ import annotations` 仅在确实需要时使用。
- 推荐本地安装 `ruff`：

  ```powershell
  python -m pip install ruff
  ruff check api
  ruff format --check api
  ```

- 数据返回一律用 Pydantic 模型或 `TypedDict`，不直接返回裸 `dict`。
- 任何外部请求都要有超时（`httpx` 的 `timeout=`），并且**不得让异常穿透到用户**：provider 层必须能降级。
- 每个响应的 `source` 与 `asOf` 字段必须如实填写。合成/代理数据必须标 `source: "synthetic"`，不得伪装成真实行情。

### 通用

- 文件编码 UTF-8，**不带 BOM**；换行统一 LF。
- 不提交生成物：`web/node_modules/`、`web/.next/`、`api/*.db`、日志、`.env`。
- 不引入与现有技术栈重叠的重型依赖（例如再引入一个图表库、再引入一个 ORM）；确有必要请在 PR 描述里说明取舍。

---

## 4. 分支模型与 PR 流程

### 分支

| 分支 | 用途 |
| --- | --- |
| `main` | 始终可运行、可部署；只接受 PR 合入 |
| `feat/<scope>-<short-desc>` | 新功能，例如 `feat/crowding-history-endpoint` |
| `fix/<scope>-<short-desc>` | 缺陷修复，例如 `fix/rotation-nan-guard` |
| `docs/<short-desc>` | 纯文档改动 |
| `chore/<short-desc>` | 依赖、构建、CI |

- 从 `main` 切出，保持短生命周期（建议 ≤ 5 个工作日）。
- 一个 PR 只做一件事；顺手的大规模重命名/格式化请单独开 PR。

### PR 流程

1. 先开 Issue（或认领已有 Issue），说明动机与影响范围；破坏性改动请先取得维护者认可。
2. Fork → 建分支 → 提交 → 推送到自己的 fork。
3. 发起 PR 到 `main`，填写 `.github/PULL_REQUEST_TEMPLATE.md` 的全部条目。
4. 保证本地自测通过，并在 PR 中粘贴关键验证输出（命令 + 结果）。
5. 至少 1 名维护者 review 通过后 squash 合并；合并信息遵循第 5 节的 commit 约定。
6. 涉及用户可见行为的改动，请同步更新 README / docs。

### PR 不应包含

- 与主题无关的格式化噪音、删除他人注释、调整无关文件的行尾；
- 调试用的 `console.log` / `print` / 临时定时任务；
- 注释掉的整段旧代码（用 git 历史即可）；
- 新的第三方凭据申请链接或邀请码。

---

## 5. Commit 约定

采用 [Conventional Commits](https://www.conventionalcommits.org/)，描述可用中文：

```text
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

`type` 取值：

| type | 含义 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 仅文档 |
| `refactor` | 重构（不改变外部行为） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `build` | 构建系统、镜像、依赖 |
| `ci` | CI 配置 |
| `chore` | 杂项 |

`scope` 建议：`api`、`web`、`providers`、`infra`、`docs`、`auth`、`charts`。

示例：

```text
feat(api): 新增 /api/v1/crowding/history 分页参数
fix(providers): 雅虎接口超时后回落到 synthetic 并写入 warnings
docs(data-sources): 补充 13F 代理指标的标注说明
```

规则：

- subject 不超过 72 字符，动词开头，句末不加句号；
- 一个 commit 一个逻辑变更；
- 破坏性改动在 footer 写 `BREAKING CHANGE: <说明>`。

---

## 6. 新增数据源的特殊要求

金融数据的授权风险高于普通依赖，因此新增数据源必须同时满足：

1. 在 PR 中提供**来源、许可/服务条款链接、是否允许程序化访问、是否允许再分发**四项说明；
2. 在 `docs/DATA_SOURCES.md` 的合规矩阵表中新增一行，并更新 `api/app/providers/base.py` 中 `provider_status()` 的 `license` 文案；
3. 提供**降级路径**：新数据源失败时，链路必须能退回已有数据源或 `synthetic`，不允许返回 500；
4. 不得绕过付费墙、登录态、验证码或 robots 限制；
5. 若涉及爬取，需说明频率限制与缓存策略（默认走 `api/app/cache.py` 的 TTL）。

没有合法免费来源的数据（暗池成交、13F 明细、社媒情感、搜索热度等），只允许以**代理指标**形式加入，且必须在 UI 与 API 中显式标注 `synthetic` / `proxy`。

---

## 7. 评审清单

维护者 review 时会逐条确认：

- [ ] 没有硬编码密钥、没有付费数据源凭据、没有真实个人邮箱写入仓库
- [ ] 没有荐股/带单/自动交易倾向的功能或文案
- [ ] 数据源可降级，`source` / `asOf` / `warnings` 如实填写
- [ ] 接口变更同步到 `docs/API_CONTRACT.md`
- [ ] TypeScript 无新增 `any`，Python 有类型注解
- [ ] 无新增未使用的依赖
- [ ] 本地能起、能跑、能测
- [ ] 文件为 UTF-8 无 BOM、LF 换行

---

## 8. 文档与本地化

- 主文档语言为**简体中文**，关键文档（README）顶部保留英文摘要。
- 术语保持一致：市场拥挤度 / 风格轮动 / 估值分位 / 因子 / 期权损益 / 数据源降级。
- 面向用户的文案避免「稳赚」「必涨」「精准预测」等表述。
- 截图请放在 `docs/screenshots/`，并更新 README 的截图占位表状态位。

---

## 9. 联系方式

- 缺陷与功能建议：GitHub Issues（请使用模板）
- 安全漏洞：见 [SECURITY.md](SECURITY.md)，**不要**开公开 Issue
- 行为准则问题：见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

提交贡献即表示你同意本项目 [MIT 许可证](LICENSE) 的授权条款。