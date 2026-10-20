# V2 Field Changes Implementation Plan

**Goal:** 交付 #268 的字段调整分组预览、一次删除确认、原子应用与整次版本撤销，采用已定稿视觉基线。

**Architecture:** 复用 Application 和 FieldSkillAdapter/Skill 脚本进行业务校验与暂存执行。V2 负责保护 Blob、持久化选择、幂等命令、新 Task/Run 及事务发布；前端只消费后端声明的原子组。Chainlit 保持独立。

**Tech Stack:** Python / FastAPI / SQLite / Alembic / React / TypeScript / native CSS。

**Baseline:** codex/v2-development, 0a0d4f00cefef702cb42cd761b5c5c1cbc6c869d；含 master 80c71496，#307 / #308 已集成。

## 1. 字段变更组契约与准备阶段

- 阅读 CONTEXT 字段调整、ADR-0008/0013、产品规格 §5/§6、技术规格字段变更 API，保持 config_ref 写回原来源。
- 实现 v2/backend/toolwithagent_v2/runtime/field_changes.py，复用现有类型化步骤及 Application 执行，不复制 add/delete/merge/decode/regex 数据逻辑。
- 在业务执行发布前截获字段计划。暂存副本上执行并冻结准备结果与生成正则，正式 apply/undo 不重复 Planner 或模型调用。
- 后端声明同字段关联操作、跨字段依赖与子规则归属；选项不能拆分原子组。明确单字段非删除变更直达应用，多组/删除/推断/跨子规则先预览。
- 添加 tests/test_field_changes.py，先覆盖同字段合组、跨字段依赖、独立组可分别选择、字段冲突、生成正则仅一次、混合计划后续按最终选择继续规划。

## 2. 持久化预览与选择

- 新增 Alembic migration，保留准备结果、原始版本、选择 revision、最终组状态与应用关系；业务内容进入受保护 Blob，不进入公开事件或日志。
- Store + API 提供 GET /runs/{id}/field-change-preview、POST /runs/{id}/field-change-selection。
- 验证 owner、If-Match、当前输入哈希、Run/checkpoint/revision，选择更新使旧确认失效。
- 添加刷新、重启、跨用户访问、未知组、拆组、过期 revision、重复请求的契约测试。

## 3. 确认与原子 apply

- POST /runs/{id}/field-change-apply 幂等冻结选择，创建独立确定性 Task/Run。
- 删除通过任务确认接口一次合并确认，绑定当前 Run/checkpoint/selection revision，列出字段与真实下游影响；取消或更新选择后旧令牌不可复用。
- Worker 只应用准备结果，不重新执行模型；发布配置与 business_state、血缘、消息及组状态同事务提交。
- 未选组结算为 not_applied_by_user；失败不发布部分产物，保留可恢复预览。
- 测试重复提交、幂等键冲突、取消迟到、worker fencing、发布失败回滚及历史 Run 不被改写。

## 4. 版本化 undo 与下游失效

- POST /artifacts/{id}/undo 幂等创建新的确定性 Task/Run，恢复本次提交前完整配置与业务槽位，保留全部历史。
- Store.publish_business 按 artifact_edges 递归传播下游 stale，避免只按 kind 失效；校验新发布产物不被同事务误标过期。
- 测试整次撤销、重复撤销、过期版本、下游多跳血缘、独立产物保留、配置 dict/list 根类型和下载兼容性。

## 5. 用户界面

- 新增 FieldChangesWorkspace.tsx 及对应测试，接入 App 的对话内摘要与中间区域原位预览。
- 按子规则 Tab 展示添加/修改/删除和不可拆组选择；一次删除确认列出影响，成功返回消息流，执行详情复用 #308 单实例 ContextPanel。
- 展示加载/空态/失败/过期/取消/用户未应用/已撤销文本；使用现有 Token，兼容明暗、键盘焦点与迟到响应守卫。
- 前端集成测试覆盖预览选择、确认、应用返回、undo、刷新恢复和权限变化。

## 6. 验证与交付

- 生产 Python 修改后重生成 docs/source-code-analysis.html，再运行根仓全量离线 pytest 与 V2 后端全量测试。
- 前端运行 Vitest、ESLint、TypeScript/Vite build；运行颜色自检和 git diff --check。
- 独立 Review 按规范/规格两轴检查，修复后复核；合入前再次同步 master 并验证受影响部分。
- 更新 CHANGELOG / v2 README，记录实际验证与人工验收限制。完整 PR 正文先在会话展示，用户确认后发布，base 为 codex/v2-development。
- 本计划不授权真实模型调用、启动服务、浏览器操作、合入 master 或切换默认入口。#272 的双入口真实样本与平台导入人工验收仍为独立交付门槛。
