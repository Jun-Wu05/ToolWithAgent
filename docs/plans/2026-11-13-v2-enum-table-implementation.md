# V2 枚举表格 Implementation Plan

**Goal:** 按已批准的 enum-table/approved-v1 两张图实现只读上传映射预览、枚举提取和威胁映射表格。

**Architecture:** 复用 Artifact 内容与下载接口，结果卡与详情共用表格组件。上传预览通过本人只读接口读取绑定文件和成功校验 Run 的不可变内容，不公开 Session 或本机路径；填充复用现有 Application 操作与显式配置选择。

**Tech Stack:** React / TypeScript / CSS tokens / FastAPI / SQLite / pytest / Vitest。

**状态（2026-11-16）：实施完成，全部验证绿；未发布 PR/tracker（按发布前确认规则待用户过目）。**

## 完成记录

- 只读结果表格：`v2/frontend/src/EnumResultTable.tsx`（两列枚举 / 三列映射，默认 5 行、展开 50 行分页、全结果搜索、表头升/降/原序三态排序）+ `enum-result-table.css`；`App.tsx::businessCard` 与 `BusinessWorkspace.tsx::ArtifactValues` 接入。
- 上传预览投影：`store.py::enum_attachment_preview`（本人 + role/parse_status 门控，SHA 校验后经 staging 临时 xlsx 解析，服务端 sheet/q/page/size/sort 有界分页，历史附件返回 current=false）；`api/app.py` 路由透传；`worker.py` 校验成功回执。空 Sheet 在工作簿校验阶段被拒（上游语义），预览不暴露失败附件。
- 预览卡 `ConversationTimeline.tsx::EnumPreviewCard`：Sheet 页签带条数、四列表格、服务端分页/搜索（300ms 防抖）/排序、迟到响应隔离；仅当前附件显示「开始填充」，历史只读。「开始填充」经 `BusinessOperations preset="fill"` 复用现有操作表单（显式配置/字段选择），无可用配置时显示原因与上传规则引导。
- 测试：后端 `test_postprocessing.py` 新增 3 项契约测试（权限+历史不漂移、多 Sheet 分页搜索排序、失败校验/空表 404）；前端新增 `EnumResultTable.test.tsx`（7 项）并更新旧断言、预览卡 3 项、preset 2 项。
- 验证：根目录全量 pytest 退出码 0；`v2/backend/tests` 249 过；前端 vitest 289 过（19 文件）；`npm run lint` 0 error（1 个既有 warning 非本次文件）；`npm run build` 过；源码快照已重生成（122 文件 / 26221 行）。
- 视觉对照：`docs/design/enum-table/implementation-20261116/`（实现图 ×2、50% 叠加图 ×2、1440×900、深色、400px 窄屏；差异记录见该目录 README）。已知有意差异：批准图一「待确认」提示条按设计正文不实现；图二「映射威胁类型」静态按钮按血缘/权限规则由真实入口承接。

## 基线与边界

- 功能分支 `codex/v2-enum-table`，初始 V2 基线 `00566689a1acb30e56551bf19efb0d83fe24ea82`；按最新 SOP 核对 master 祖先及基线全量测试后改生产代码。
- 主目录批准图和设计文件保留，另复制到本 worktree 纳入交付；禁止覆盖 approved-v1。
- 不新增手工编辑、确认 token、下载格式或填充计算。历史预览不冒充已写入结果。
- Tracker 正文先展示再获批发布；服务启动与浏览器操作按项目人工验收边界交接。

## 1. 只读结果表格

- 新增 `v2/frontend/src/EnumTable.tsx` 与 `enum-table.css`：两列枚举、三列映射、四列附件预览；默认五行、展开后 50 行分页；全结果搜索、表头排序与恢复原序；保留展开前后的查询和页码。
- 修改 `App.tsx` 的 businessCard 与 `BusinessWorkspace.tsx` 的 ArtifactValues；保留正式下载、权限和血缘门控。
- 定向测试 0/1/5/51 行、空字符串、0、特殊字符、长值、分页搜索排序、读取失败重试与迟到响应隔离。

## 2. 上传预览投影

- 检查 `runtime/postprocessing.py`、`runtime/worker.py` 与 `infrastructure/store.py` 的附件生命周期；复用工作簿解析，不修改共享填充语义。
- 在 `api/app.py` 和 `api.ts` 增加本人只读查询，绑定 file/run/revision，显式返回 Sheet 完整总数与分页；当前操作资格与历史内容分开。
- `ConversationTimeline.tsx` 将预览挂载到匹配 Run 的助手结果，不放入用户附件气泡。
- 契约测试本人权限、校验失败/取消、历史文件、新附件同名 Sheet 替换、累计 Sheet、刷新、空数据和无配置。

## 3. 验证与交付

- 根目录全量 `python -X utf8 -m pytest -q --basetemp=.pytest-tmp-enum-final`。
- 按 V2 README 运行后端全量测试；前端 `npm test`、`npm run build`、`npm run lint`；运行视觉 Token 检查。
- 若修改共享生产 Python，先重生成源码快照。记录基线、实际测试结果与已知限制。
- 按原 PNG 尺寸、DPR=1、100% 缩放准备固定数据视觉用例；另验 1440×900、明暗与窄屏，保存实现图、叠加图和差异记录。视觉和真实会话证据分别记录；未执行的人工验收不得宣称通过。
