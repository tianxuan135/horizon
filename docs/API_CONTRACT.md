# Horizon API Contract (v1)

所有前端请求统一走 `web/next.config.mjs` 的 rewrite → FastAPI `http://127.0.0.1:8000`。
前端只调用 `GET/POST /api/v1/...`，**任何数据源密钥只存在于后端环境变量**。

通用约定
- `market`: `"us"` | `"cn"`。
- 所有时间戳 ISO 8601 UTC（`2025-01-03T14:30:00Z`），前端负责转本地时间与 `周x` 文案。
- 所有响应含 `asOf`（本次计算数据时间，UTC）与 `source`（数据来源标识，用于「数据状态」页与合规标注）。
- 数据不可得时后端必须返回 `source: "synthetic"` 并在 `warnings[]` 说明，**不得编造成真实来源**。

## 1. Meta
`GET /api/v1/meta/status?market=us` →
```json
{ "asOf": "...", "app": "Horizon", "version": "0.1.0",
  "sources": [ { "id":"yahoo", "name":"Yahoo Finance", "kind":"free-public", "ok": true, "latencySec": 12, "license":"Public/non-commercial", "freshness":"..." } ],
  "disclaimer": "本工具所有数据及分析结果仅供学习研究参考，不构成任何投资建议。" }
```

## 2. 市场拥挤度
- `GET /api/v1/crowding/industries` → `{ "industries": [ {"key":"chips","name":"芯片","nameEn":"Chips"}, ... 13 个固定项 ] }`
- `GET /api/v1/crowding/score?market=us&period=1d` →
```json
{ "asOf":"...", "source":"...", "market":"us", "period":"1d",
  "industries":[{"key":"chips","name":"芯片","score":72.4,"label":"偏进攻","color":"attack"}],
  "composite":{"score":64.1,"label":"中立","color":"neutral","index":{"symbol":"^GSPC","name":"标普500","value":5942.1}},
  "dimensions":[{"key":"funding","name":"资金拥挤度","weight":0.33,"score":70.2,"series":[{"t":"2024-12-01","v":61.2}]}],
  "mainSeries":[{"t":"2025-01-03","score":64.1,"label":"中立","indexValue":5942.1}] }
```
- `GET /api/v1/crowding/history?market=us&days=365&period=5d` →
```json
{ "asOf":"...", "series":[{"t":"2025-01-03","score":64.1,"indexValue":5942.1}] }
```
五维权重固定：funding 0.33 / pullback 0.22 / anxiety 0.18 / social 0.15 / spread 0.12。

## 3. 风格轮动
- `GET /api/v1/rotation/score?market=us&group=size|style&days=365` →
```json
{ "asOf":"...", "group":"size", "pair":{"a":"^GSPC","b":"^RUT","aName":"标普500","bName":"罗素2000"},
  "series":[{"t":"2025-01-03","r":0.12,"m10":0.03,"z":0.4,"score":19.7}],
  "formula":"R(t)=ln(A/B); M10(t)=R(t)-R(t-10); Z(t)=(M10-μ252)/σ252; score=100*tanh(Z/2)" }
```

## 4. 估值分析
- `GET /api/v1/valuation/search?q=apple&market=us` → `{ "results":[{"symbol":"AAPL","name":"Apple Inc.","exchange":"NASDAQ","market":"us"}] }`
- `GET /api/v1/valuation/watchlist?market=us` → `{ "items":[{"id":"...","symbol":"AAPL","name":"Apple Inc.","bucket":"tech","sort":0}] }`
- `POST /api/v1/valuation/watchlist` body `{ "symbol":"AAPL", "market":"us" }` → `{ "item": {...} }`
- `DELETE /api/v1/valuation/watchlist/{id}` → `{ "ok": true }`
- `POST /api/v1/valuation/watchlist/reorder` body `{ "ids": ["a","b"] }` → `{ "ok": true }`
- `GET /api/v1/valuation/score/{symbol}?market=us` →
```json
{ "asOf":"...", "symbol":"AAPL", "name":"Apple Inc.", "bucket":"tech",
  "metrics":{"pe":31.2,"pb":48.1,"ps":8.0,"fcfYield":0.031,"marketCap":3.4e12},
  "dimensions":{"fundamental":78,"moat":92,"substitutability":30,"capex":55},
  "series":[{"t":"2024-12-01","pe":30.1}], "source":"..." }
```

## 5. 因子策略
- `GET /api/v1/factor/strategies` → `[{"id":"momentum","name":"动量因子","factors":["mom_12_1"],"desc":"..."}]`
- `GET /api/v1/factor/benchmarks?market=us` → `[{"id":"spx","symbol":"^GSPC","name":"标普500"}]`
- `POST /api/v1/factor/backtest` body `{ "market":"us", "strategyId":"momentum", "start":"2023-01-01","end":"2024-12-31","benchmark":"spx" }` →
```json
{ "asOf":"...", "equity":[{"t":"2023-01-03","nav":1.0,"bench":1.0}],
  "metrics":{"cagr":0.184,"mdd":-0.21,"sharpe":1.12,"vol":0.19,"alpha":0.03,"beta":0.92,"winRate":0.56},
  "benchmark":{"id":"spx","name":"标普500"} }
```
- `GET /api/v1/factor/mine?market=us&window=252` → `[{"factor":"pe_inv","ic":0.031,"icir":0.42,"tStat":2.1,"turnover":0.18,"desc":"..."}]`

## 6. 期权策略
- `GET /api/v1/options/expiries/{symbol}?market=us` → `{"expiries":["2025-02-21", ...]}`
- `GET /api/v1/options/chain/{symbol}?market=us&expiry=2025-02-21` → `{ "spot":231.4, "rows":[{"strike":230,"callBid":4.1,"callAsk":4.3,"putBid":2.8,"putAsk":3.0,"iv":0.28}] }`
- `POST /api/v1/options/payoff` body
```json
{ "spot":231.4, "strategy":"single|butterfly|straddle|strangle|covered_call|collar",
  "legs":[{"type":"call","side":"long","strike":230,"premium":4.2,"qty":1}],
  "rangePct":0.25 }
```
→ `{ "curve":[{"price":180,"pnl":-4.2}], "maxProfit":null, "maxLoss":420.0, "breakevens":[234.2], "netPremium":-420.0 }`
（`maxProfit` 为 `null` 表示理论无限）
- `POST /api/v1/options/backtest` 同因子回测请求体/响应体结构。
- `GET /api/v1/options/strategies` → `[{"id":"covered_call","name":"备兑看涨","desc":"..."}]`（期权回测可选策略清单）
- `GET /api/v1/options/spot/{symbol}?market=us` → `{ "spot":231.4, "asOf":"2025-01-02T10:00:00Z", "source":"yahoo" }`（计算器基准价，缺失时降级 synthetic 并标注）

## 7. 账号
- `POST /api/v1/auth/register` `{ "email":"a@b.c","password":"..." }` → `{ "ok":true,"requiresVerification":false }`
- `POST /api/v1/auth/login` `{ "email","password" }` → `{ "token":"...","user":{"id","email"} }`
- `POST /api/v1/auth/verify` `{ "email","code" }` → `{ "ok":true }`
- `GET /api/v1/auth/me`（`Authorization: Bearer`）→ `{ "id","email","market" }`
- 邮件验证默认关闭：仅当 `SMTP_HOST` 存在时 `requiresVerification=true`。
## 8. 实现补充（v1.1，联调后追加，均为向后兼容的加法）

以下为后端实现时新增的端点/字段，前端可忽略未使用的键；已有字段的语义不变。

- `GET /api/v1/auth/config` → `{"authEnabled":false,"requiresVerification":false,"tokenTtlHours":72}`。
  前端据此决定是否展示验证码步骤；`authEnabled=false` 时 `register|login|verify` 一律 **403**（中文说明），
  分析功能无需登录。
- `GET /api/v1/factor/mine/{factor}?market=us&window=252` → 单因子明细（从 `/factor/mine` 结果中筛出）。
- `GET /api/v1/options/chain/{symbol}?market=us` 不带 `expiry` 时默认最近到期日；行内额外返回
  `iv/callMid/putMid/inTheMoney`，响应头字段 `atmVol/expiry/source`（`model:blackscholes-realised-vol`
  = BS 模型价，**不是可交易报价**）。
- `POST /api/v1/options/payoff` 补充约定：
  - `netPremium` **负值 = 净支出**（long call 付 4.2 → `-420.0`）。
  - 金额口径为「每张 × 100 股」：`maxLoss/maxProfit/netPremium/pnlTotal` 为美元；`curve[].pnl` 为**每股**，
    前端不得再乘 100。响应另带 `multiplier:100`、`curveUnit:"perShare"`、`pnlAtSpot`、
    `profitUnbounded/lossUnbounded`。
  - `covered_call`/`collar` 只需传期权腿，后端自动补 +100 股 stock 腿。
  - 非法输入统一 400 中文文案（未知策略会列出可选枚举）。
- `valuation/score` 补充：`marketCap` 恒为 `null`（无合法免费股本数据源，不编造数值，前端渲染 "—"）；
  `metricsBasis:"price-derived-proxy"` 与 `warnings[]` 提示「P/E、P/B 等由价格序列反推，非财报口径」；
  另带 `bucket/bucketName/priceStats/seriesBasis`。
- `crowding`/`rotation` 补充：`dataThrough`（数据截止交易日）、`warnings[]`（代理指标说明）、
  industries 的 `change/proxy/dims`、rotation 的 `current{score,mu252,sigma252,bias}`。
- `factor/backtest`、`options/backtest` 补充：`sources/warnings/start/end/holdings/avgTurnover`。
- 全局约定：所有行情类响应带 `source`（`yahoo|akshare|synthetic`）；沙箱或断网时降级 `synthetic` 并在
  `warnings[]` 明示，**绝不伪称为真实行情**。
