# V2 枚举表格展示交接

初稿：2026-11-12。归档更新：2026-11-13。交付性质：设计图已获用户确认的开发交接，未开始实施。

设计正文见 [V2 枚举表格展示方案](../design/2026-11-12-v2-enum-table-design.md)。用户要求沿用 V2 视觉，为枚举相关结果补充 Chainlit 式表格可读性；本轮不要编写业务代码，不做枚举手工编辑器。

## 已确认设计图与还原要求

用户已确认两张图，并要求“一比一还原”。接手必须先打开原图和设计正文 §7–§8，以图片作为两个浅色桌面状态的视觉基准，不再自行探索新风格。

- [图一：枚举映射预览](../design/enum-table/approved-v1/01-enum-mapping-preview.png)：工作表页签、四列表格、待填充状态、查看全部与开始填充、底部待确认提示。
- [图二：枚举提取结果](../design/enum-table/approved-v1/02-enum-extraction-result.png)：两列表格、已完成状态、下载、折叠正则、后续操作；无待确认提示条。

原始 PNG 已保存到仓库，不依赖聊天或生成缓存。不得覆盖 approved-v1；后续变更另存版本。示例数据只用于隔离的视觉对照，真实标签和业务能力以方案正文及后端事实为准。图一待确认提示不意味着新增确认流程；图二后续操作按字段血缘与权限展示。

实施时记录原图尺寸和截图环境，用相同示例数据、同尺寸视口、DPR=1、100% 缩放生成真实组件截图，并提供叠加对照和差异清单；另验 1440×900 工作台。必须核对消息对齐、表格密度、按钮层级和留白，不能以测试通过代替视觉还原。深色、窄屏、展开与异常态未包含在本次图片确认中，需独立检查。

## 基线

主目录 master 是 ff6775d1，不能用它的旧 V2 判断当前实现。已检查的 GitHub 远端跟踪分支为 `github/codex/v2-development`，提交 d036eb52，含工作台 #443 与日志类型结果 #445。远端名 `github` 对应 GitHub，`origin` 对应 GitCode；不要误用 `origin/codex/v2-development`。本地 `codex/v2-development` 停在 4870e3a8，且被其他 worktree 占用。

后续实施先核对最新远端与协作领取，按仓库 SOP 在合适分支/worktree 开始；保护现有未提交设计文件。不切换默认 Chainlit 入口，不自动提交或发布 tracker。

## 已确定的改动方向

1. 对话结果卡补最多 5 行的只读表格摘要；完整表格支持原位展开、50 行分页及全结果搜索。
2. 三类来源分开：枚举 Excel 上传预览、枚举提取 values、威胁/枚举映射。上传预览不能标成填充成功。
3. 沿用最新 220px 侧栏工作台、现有 Token、6px 圆角和对话/轨迹语义；不换视觉风格。
4. 只读展示、正式下载及现有操作复用；不加入修改单元格、逐行应用、批量重映射。

## 代码接入点

| 接入点 | 当前职责 / 后续工作 |
|---|---|
| `web/file_handlers.py`、`web/parsers.py` | Chainlit 上传预览参考，核对真实字段和累计 Sheet 语义 |
| `web/plan_renderer.py` | 枚举值/威胁映射表格及下载行为参考 |
| `v2/frontend/src/ConversationTimeline.tsx` | 消息、文件、产物关联；新增预览必须挂回正确消息 |
| `v2/frontend/src/App.tsx::businessCard` | 当前通用数量卡，接入只读摘要，保持查看与下载 |
| `v2/frontend/src/BusinessWorkspace.tsx::ArtifactValues` | 当前 enum_values 是列表、threat_mapping 已有表格；统一呈现而非重复业务计算 |
| `v2/frontend/src/api.ts` | 核对 artifact 内容接口与附件预览投影契约 |
| `v2/backend/toolwithagent_v2/runtime/postprocessing.py`、`runtime/worker.py` | 已有附件提交路径，确认预览快照和可公开字段 |
| `v2/backend/toolwithagent_v2/infrastructure/store.py` | 当前 SessionFacts 提供目标字段/计数；检查是否需要只读预览查询 |

上传预览的完整行未确认已在 API 暴露，实施者必须先确认数据契约。若缺失，提出最小只读投影，明确文件/Run/修订绑定、访问控制、分页和总数；不直接暴露持久化 Session，不绕过 Application 修改填充逻辑。成功填充的逐行状态需要后端事实，不可从输入预览推断。

## 建议实施顺序与交付证据

先核对现有接口和真实 payload，再实现已有 artifact 的表格摘要/完整查看，随后补附件预览。复用现有填充操作和下载命名。补定向组件/契约测试，验证大数据、历史版本、跨刷新与权限；按仓库要求执行全量检查。真实 App 明暗与窄屏截图，并标记固定数据视觉证据或真实会话证据，不能混写。

完成标准以设计正文 §6–§8 为准，包括两张确认图的视觉对照。正式 tracker/PR 按仓库发布流程处理。本轮仅归档图片与更新文档，没有运行实现测试，没有改业务代码，没有发布 issue/PR。
