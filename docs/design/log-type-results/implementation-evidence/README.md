# 日志类型结果表 · 实施证据

实施：2026-11-12（Asia/Shanghai）。基线 `bd0919ed`（`github/codex/v2-development`，PR #443 合并点）。
实施 worktree：`D:\Agent\agent_design\twa-v2-log-type-results`，分支 `codex/v2-log-type-results`。
批准视觉版本：`log-type-results-v1`，四个批准文件 SHA-256 已逐一核验一致（见 HANDOFF §4）。

## 0. 导出入口规则一键直出（#444 验收反馈二轮）

> 本节对应分支 `codex/v2-export-rules-direct`（基线 `d036eb52`，PR #445 合并点）。

- 交互：点击「导出入口规则」→ 按钮转「导出中…」→ 排队既有 export 操作（`session.log_classification.entry_rules`）→ run 完成后自动下载生成的规则 TXT；展开式表单（规则内容选择 + 开始处理）从结果卡移除。
- 前置指引：规则 TXT 文件头要求数据源产品/厂商元数据（`application/adapters/shared.py::require_rule_source_fields`），该元数据由标准字段映射带入（`store.read_business_session` 从映射 run 快照恢复）。无映射产物的会话点击导出时直接显示「导出入口规则需要数据源产品/厂商：请先完成「标准字段映射」后重试。」，不发起注定失败的导出（真实浏览器验证：指引出现、operations 请求 0 次、无 busy 瞬态）。`export-01-buttons.png`（按钮行）/ `export-02-guidance.png`（指引态）。
- 失败路径（App 测试覆盖）：run 失败时错误就地显示、按钮恢复可用、不触发下载；幂等 receipt 防重复提交。
- 子规则导出按钮本轮不加（用户决定，延后到标准字段映射后续轮次）；前置指引逻辑对将来的子规则入口同样适用。

## 1. 改动面

| 文件 | 性质 |
|---|---|
| `v2/frontend/src/LogClassificationResult.tsx` | 新增：结果组件 + 卡片容器（读取、重试、迟到响应隔离） |
| `v2/frontend/src/log-classification.css` | 新增：`lcr-` 命名空间样式，颜色全部引用现有 tokens |
| `v2/frontend/src/LogClassificationResult.test.tsx` | 新增：42 个测试（KV/JSON/头部/缺失元数据 fixtures） |
| `v2/frontend/src/App.tsx` | 接入：`classificationCard` 换用新卡片，业务按钮全部保留为 actions |
| `v2/frontend/src/App.test.tsx` | 补充分类产物 mock：全量展示、读取失败重试、stale、身份切换迟到响应 |
| `v2/frontend/src/BusinessWorkspace.tsx` | 接入：`ArtifactValues` 分类分支复用结果组件 |
| `v2/frontend/src/ConversationTimeline.tsx` | 缺口修复：产物无 `result_message_id` 时按 run_id 关联完成消息（见 §4） |
| `v2/frontend/src/ConversationTimeline.test.tsx` | 补充 run_id 兜底关联回归测试 |

未改任何 Python / 后端 / 契约 / API。

## 2. 回归结果

| 套件 | 命令 | 结果 |
|---|---|---|
| 根目录 Python（基线，改动前） | `python -X utf8 -m pytest -q --basetemp=.pytest-tmp-log-type-results-baseline` | 1030 passed |
| v2 后端 | `PYTHONPATH=v2/backend tmp/venv/Scripts/python.exe -m pytest -q v2/backend/tests --basetemp=tmp/pytest-log-type-results` | 246 passed |
| 前端 | `npm test` | 18 files / 273 tests passed |
| 前端构建 | `npm run build`（tsc -b + vite build） | 通过 |
| 前端 Lint | `npm run lint` | 0 error；1 个既有 warning（`FieldChangesWorkspace.tsx:34` react-hooks/exhaustive-deps，非本次改动文件） |

备注：v2 后端套件曾出现 1 例 `test_postprocessing.py::test_old_card_id_and_untyped_button_sources_are_rejected` 失败，定位为与本实施无关的并行种子脚本共享 `agent/logs` 文件锁干扰；隔离重跑该用例通过，且在无并行的完整重跑中 246 全绿。

## 3. 视觉验收（真实 App，SSE 长连接，CDP 精确视口）

- 服务：worktree 内 `uvicorn`（127.0.0.1:8100）+ worker 进程 + `vite`（127.0.0.1:5173），数据目录 `tmp/acceptance-data`。
- 数据：离线种子脚本 `tmp/seed_acceptance.py`（FixtureBusiness，不经 LLM），内容取自批准图稿固定样例（auth/traffic/threat/system、未匹配 2 行、JSON 变体同源）。
- 截图浏览器：Chrome headless（CDP），`--force-device-scale-factor=1`，视口 1440×900 / 390×844。
- 文件：`app-01…04`（全页）、`app-05-export-rules-open.png`（「导出解析规则」展开态）、`side-by-side-01…03`（批准图稿卡片 vs 生产卡片，左右合成）、`style-probe-1440.json`（计算样式探针）。
- 按钮行（用户验收反馈后修复）：底部操作按钮对齐图稿改为单行排布——`查看产物 / 下载产物 / 导出入口规则 / 申请加入知识库 / 标准字段映射 / 提取字段枚举值` 同属 `.lcr-actions-row`（flex-wrap，窄屏自动换行）；展开「导出入口规则」时表单经 `flex-basis:100%` 换行到按钮行下方全宽显示（app-05 与程序化布局检查：同行按钮 top 一致、表单区独立于按钮行）。App 测试含六按钮同容器的防回归断言。
- 二轮验收反馈调整：① 结果消息自带的三个建议 chips（标准字段映射/查看解析规则/提取字段枚举值）不再渲染——操作已全部由卡内按钮行承载；「提取字段枚举值」保留为卡内按钮（点击填入输入框占位话术，与原 chip 行为一致）。② 分类导出固定入口规则：按钮文案「导出入口规则」，表单移除「规则内容」选择（子规则导出待标准字段映射后续轮次开放），仅剩「开始处理」。程序化验证：结果消息内 chips = 0，导出表单无规则内容选项。

### 计算样式探针（1440×900，JSON 变体会话）

| 项 | 图稿设计值 | 生产实测 |
|---|---|---|
| 三列宽度 | 23% / 18% / 59% | 23.0% / 18.0% / 59.0% |
| 表头高 | 约 36px | 36px |
| 表格正文 | 13px | 13px |
| 样例预览 | 12px / 1.75 行高 / 最多 2 行 | 12px / 21px / line-clamp 2 |
| 类型/样例字体 | 等宽 | `ui-monospace, Cascadia Code, …` |
| 摘要网格（JSON） | .8fr 1.5fr 1fr 1.1fr | 实测比例 1 / 1.875 / 1.25 / 1.375（一致） |
| 圆角 | 6px | 6px |
| 页面横向溢出 | 无 | 无 |
| 高亮 | 可定位时 | 预览与展开区均存在 `<mark>` |

### 像素对照（卡片区域，容忍度 16/通道）

| 场景 | 对齐后整卡匹配 | 说明 |
|---|---|---|
| 分类总览 | 86.5%（dy=12） | 差异集中在标题块与操作区（见下） |
| KV 展开态 | 77.8%（dy=−42） | 图稿该视图含 review-only 行距压缩（10px vs 生产 12px），纵向累积错位 |
| JSON 变体 | 81.6%（dy=−42） | 同上 |

已知且经确认的像素差异来源（均为方案 §4/§2.1 划定的生产边界，非还原偏差）：

1. 标题块：生产沿用 V2 已有 `result-card` 标题（含时间戳），图稿为 18px `assistant-title` 构图。
2. 操作区：生产为真实业务按钮（查看产物、下载产物、导出解析规则、标准字段映射、申请加入知识库），图稿为三个演示按钮。
3. 图稿 KV/JSON 截图带 `.detail-view` 审稿压缩样式（HANDOFF §1 明确不进生产）。
4. 生产按方案 §3.2 补充显示合法覆盖计数（`（覆盖 43/45 行）`）。

## 4. 实施中发现的既有缺口（已修复）

真实后端的 `store._artifacts` 对 `log_classification` 明细不返回 `result_message_id`（store.py 分类分支无该字段），导致分类卡片在真实会话时间线从未挂载（旧实现同样受影响；既有 App 测试以 `linkRecentFixture` 人为补链）。

修复采用前端稳定标识兜底：`buildTurns` 对无 `result_message_id` 的产物回退用其 `run_id` 关联携带同一 run_id 的完成消息（`_assistant_message` 恒写入 run_id）。不引入时间/相邻猜测，不改 Python。回归测试：`ConversationTimeline.test.tsx > attaches artifacts without result_message_id through their run completion message`。

## 5. 生产/图稿边界确认

- 图稿的审稿切换栏、待确认水印、模拟 toast、`detail-view` 隐藏前文、演示按钮：未进入生产。
- `dangerouslySetInnerHTML` 未使用；`<script>`、反引号、`|` 均按文本渲染（组件测试覆盖）。
- 复制走既有 `VisualPrimitives.CopyButton`，始终复制原始样例字符串；JSON 格式化仅改显示。
- 权限与业务资格（`mapping_eligible`、`submission_eligible`、developer 隐藏写入口）行为与接入前一致（App 测试覆盖）。
