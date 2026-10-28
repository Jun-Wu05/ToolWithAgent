# #309 页面视觉基线核对

基线：`codex/v2-development@e0d07226b0f097125672be408d407de279a36cb3`。规格：`docs/design/v2-visual-baseline.md` §5。此单只调整现有 V2 页面的视觉表达，不改变 Token 值或业务契约。

| 页面 | 自动核对点 | 人工终验 |
|---|---|---|
| 工作台与壳层 | 既有 TaskHintBar、单实例 ContextPanel、快捷入口只预填；侧栏当前项使用 `--tint-primary`；最近会话仅在该用户确有 Run 时显示最新状态点/字 | 明暗、窄屏、焦点与抽屉行为 |
| 我的执行、我的任务 | StatusText、状态筛选 chips、行悬停；完成 Run 用真实开始/结束时间算耗时，无时间显示 `—` | 明暗与多视口 |
| Developer Run 诊断 | 列表、概览和步骤时间线用 StatusText；运行耗时由真实时间戳计算；列表筛选 chips；详情保留右侧面板并复用 TaskHintBar、ToolCallBlock；缺失证据仍标「未采集」 | 明暗、长 ID、五 Tab 与窄屏 |
| 字段映射 | 状态点/字、草稿修改行浅蓝底加左侧警告指示、解析异常行危险浅底；保留现有输入和两档线 | 明暗、长字段、横向滚动 |
| 字段变更 | 状态点/字；增删改沿用成功、危险、主色；现有分组卡片和前后对比保持 | 明暗、批量变更与窄屏 |
| Admin | 既有 Token 变量适用；本单不改变管理布局 | 与 #310 联合验收 |

## 证据边界

- 会话摘要 API 在 owner 范围内返回每个会话最新当前 Run 的状态；无 Run 返回空值，侧栏不显示状态点。该接口不返回冻结输入或其他用户会话。
- Developer 诊断使用现有五 Tab 和右侧详情栏。独立 Skill/Tool ID 的采集缺口仍由 #270 跟踪，页面继续明确显示「未采集」。
- 明暗和多视口的人工视觉终验与 #310 及其他 V2 切片联合进行；此文档不把自动测试视作人工验收。

## 验证命令

- 根仓：`pytest -q`
- V2 后端：`pytest -q v2/backend/tests`
- 前端：在 `v2/frontend` 运行 `npm test -- --run --maxWorkers=1`、`npm run lint`、`npm run build`

## 自动验证记录

- 根仓全量 pytest 通过；测试使用本地非密钥字段缓存和占位 API key。
- V2 后端 227 passed；会话状态摘要的空会话、单用户和用户隔离定向测试 3 passed。
- 前端全量 Vitest 214 passed（单线程，避免并发资源争用）；lint 为 0 错误、1 条既有 React Hooks 警告；生产构建通过。
