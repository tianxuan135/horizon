## 变更说明

<!-- 这个 PR 做了什么，为什么需要它。避免只贴 commit 列表。 -->

## 关联 Issue

<!-- 例如：Closes #123 / Refs #456 -->

## 变更类型

- [ ] 新功能（feat）
- [ ] 缺陷修复（fix）
- [ ] 重构（refactor）
- [ ] 性能优化（perf）
- [ ] 文档（docs）
- [ ] 构建 / 镜像 / 依赖（build）
- [ ] CI（ci）
- [ ] 其他（chore）

## 影响范围

<!-- 勾选涉及的部分，便于 reviewer 分配注意力 -->

- [ ] `api/`（后端路由 / provider / 缓存 / 数据模型）
- [ ] `web/`（页面 / 组件 / lib）
- [ ] `infra/`（compose / nginx / Dockerfile）
- [ ] `docs/`（含 `API_CONTRACT.md`、`DATA_SOURCES.md`）
- [ ] `.github/` 或其他仓库配置
- [ ] 无用户可见行为变化

## 接口契约

- [ ] 本 PR 未改动任何 API 响应字段
- [ ] 本 PR 改动了 API，且已同步更新 `docs/API_CONTRACT.md`（说明改动点：…）
- [ ] 本 PR 新增数据源，且已更新 `docs/DATA_SOURCES.md` 与 `provider_status()` 的 license 文案

## 验证方式

<!-- 贴出实际执行的命令与关键输出，不要只写「已测试」 -->

```text
# 示例
cd api && python -m uvicorn app.main:app --port 8000
curl http://127.0.0.1:8000/health
cd web && npm run build
```

## 截图 / 录屏

<!-- 涉及 UI 变更时提供；请确认截图中不含密钥、token 与真实个人邮箱 -->

## 合规自查（硬性，必须全部勾选）

- [ ] **无硬编码密钥**：没有把 token / key / 口令 / 私钥写入代码、配置、测试或本 PR 描述
- [ ] **无付费数据源凭据**：`.env.example` 中所有凭据位仍为空；未提交任何商业数据源账号或 token
- [ ] **无荐股 / 带单 / 自动交易功能**：本 PR 不含买卖建议、目标价、评级、自动下单或交易 API 对接
- [ ] 涉及数据展示时，`source` / `asOf` / `warnings` 字段如实填写；代理指标标注为 `synthetic` 并说明成因
- [ ] 未新增绕过付费墙、登录态、验证码或 robots 限制的抓取逻辑
- [ ] 新增外部请求均设置了超时，且失败时可降级，不会向用户抛 500

## 代码质量自查

- [ ] TypeScript 无新增 `any` 逃逸，`npm run build` 通过
- [ ] Python 新增/修改函数均有类型注解
- [ ] 无调试残留（`console.log` / `print` / 临时定时任务）
- [ ] 无与主题无关的格式化噪音
- [ ] 文件为 UTF-8（无 BOM）、LF 换行

## 其他说明

<!-- 破坏性改动、迁移步骤、回滚方式、需要维护者决策的点 -->