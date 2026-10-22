# Quiet Precision 正式 V2 接入计划

**Goal:** 将用户已验收的四 Tab 工作台设计接入真实 V2 前端。

**Architecture:** 以 codex/v2-development 同步 github/master 后的 7e4fd71e 为基线，在独立 codex/v2-quiet-precision 分支实施。保留已有 App 命令、SSE、身份隔离、草稿保存/冲突/应用流程，仅替换布局和呈现组件。新增视图从 Conversation、Artifact、Run 和既有内容查询 API 取数，不复制原型合成数据。

**Tech Stack:** React、TypeScript、CSS custom properties、Vitest、Testing Library。

## 已有授权和边界

- 用户在2026-10-22确认精修版设计合理，并要求正式融入版本。
- 本轮新设计替代旧视觉规格中320px侧栏等冲突项；保留四Tab、224px侧栏、表内字段选择和双主题。
- 不改后端执行、数据库或API结构；不复制原型的内存草稿、示例历史、固定数量和演示开关。
- 历史版本使用真实Artifact标识和创建时间，不生成虚构v1/v2。内容比较只对既有内容接口返回的真实快照计算。
- Tracker正文仍需展示确认后发布。本地实施与验证先完成，不擅自发布Issue、PR或切换默认入口。

## Task 1：主题

修改v2/frontend/src/styles.css，新增workbench.css，复用styles.css顶部集中定义的Token；在main.tsx加载。抽离已有颜色变量，迁移到已验收Soft Charcoal/Warm Neutral语义值；保留既有原语所用Token名称，正文14px，字段/JSON等宽，导航224px。

验证：构建、lint，公共原语测试，浅深主题可读性及小屏布局。

## Task 2：真实四Tab壳层

修改App.tsx，新增WorkspaceViews.tsx及对应测试。保留原对话命令和确认流程；任务概览从文件/执行/产物/草稿计算下一步。结果页保留版本选择及分类/映射/解析规则入口；真实编辑器保持挂载以保留筛选和未完成输入。轨迹按真实Run与事件组织，可展开查看元数据和关联产物。

验证：现有App、AppDraft、BusinessConfirmation回归；补充Tab保留草稿、结果定位、真实历史只读、身份切换清理以及错误恢复测试。

## Task 3：标准字段搜索菜单

新增StandardFieldPicker.tsx及测试，修改MappingWorkspace.tsx和相关交互测试。菜单支持搜索、方向键/Enter/Esc、禁用原因、占用者提示、最大320px及上下自动定位。继续调用原saveMapping/confirmMapping，不绕过服务端校验。

草稿revision变化后保留当前筛选页的编辑行和顺序；主动刷新或改变筛选才重算。失败保留待保存选择；版本冲突仍阻止后续写入并要求重新加载。

## Task 4：真实快照比较与验证

通过既有artifactContent查询真实内容，按JSON路径显示新增、修改、删除与未变化数量。没有可比较快照时显示明确空态，不制作示意历史。

全量root pytest、前端Vitest、构建、lint；按隔离V2环境运行后端回归。浏览器复查真实API本地数据的浅深色、桌面/窄屏与跨Tab完整路径，不触发付费模型调用。记录准确分支/HEAD和启动命令，给用户审阅后再进入发布步骤。

## 基线

- master: 5c6f017f13e013797c673c6b9b64aa1421712991。
- 集成同步提交: 7e4fd71e；只发生源码分析HTML冲突，已按合并后的源码重新生成解决。
- root pytest全量基线通过。
- npm全局缓存出现EEXIST/EBADF；核对新工作树与原型锁文件一致后复用同版本node_modules，未改变依赖或锁文件。

## 完成记录

实现和独立审查已完成；验证、基线同步兼容说明、真实 API 数据边界及精确启动命令见 `docs/design/quiet-precision-integration-acceptance.md`。Tracker 发布与 master 默认入口切换继续遵守原确认边界。
