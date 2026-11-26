# V2 工作台交互演进蓝图——对标 AG-UI / LangGraph / Dify 的 40% 通畅性路线

> 2026-11-25 · 依据 #461/#462 拆分 · 调研对象：AG-UI 协议、LangGraph、Dify、LobeChat、Open WebUI
> 状态：草案（经用户评审后按 P1→P5 逐项切片）

## 1. 调研对照

| 参照系 | 核心模式 | 关键事实 |
|---|---|---|
| **AG-UI 协议**（CopilotKit 等推动的 Agent-User Interaction Protocol） | 类型化事件流作为前后端契约 | 事件分类学：`RUN_STARTED/FINISHED`（run 生命周期）、`STEP_STARTED/FINISHED`（具名阶段边界）、`TOOL_CALL_START/ARGS/END`（工具调用）、`STATE_DELTA`（状态增量）、`TEXT_MESSAGE_*`（文本生命周期）、human-in-the-loop 确认事件。前端只消费事件流渲染，不依赖模板猜测 |
| **LangGraph** | `interrupt()` 人机协同 | agent 提案 → 图冻结 → UI 弹审批对话框（approve/edit/reject）；checkpoint 支撑恢复。关键动作必须显式确认后才提交状态变更 |
| **Dify** | Chatflow = 对话层 + 流程层合一 | 用户在聊天界面交互，每条消息触发设计好的 flow；Agent 节点推理+按需调用工具；过程可见 |
| **LobeChat standalone 插件 / Open WebUI Generative UI** | 消息内渲染自定义 UI | 插件完全自主控制交互体验，在消息流内渲染图表/表格/后续动作；结果卡与对话一体 |

**共性结论**：一线 agent 工作台都遵循「**事件流即对话内容**」——执行过程、结果、下一步建议全部内联在消息流里且语义自洽；顶部横幅类通知只保留错误级；每个产物卡的标题/摘要能回指用户的输入意图。

## 2. V2 现状同构性分析

V2 的骨架已经与上述模式同构，差距不在架构而在「最后一公里」：

| V2 现有机制 | 对应参照 | 已对齐 | 缺口 |
|---|---|---|---|
| `run_events`（`run_progress` + phase + dependency_scope_ids，SSE 推送） | AG-UI `STEP_*` 事件 | 事件流存在且类型化 | 前端未把它叙事化为对话内的执行过程（只渲染成「运行中」三字+独立轨迹页） |
| `waiting_confirmation` + BusinessConfirmation 对话框 | LangGraph `interrupt()` | 审批流存在 | 确认文案模板腔；确认与上下文的对应关系弱 |
| 产物卡（enum_values/field_mapping/config_export…） | Generative UI | 卡片在消息流内 | 卡标题/摘要按 kind 猜模板，与输入意图错位（#461 修复） |
| `suggestions` 目录（#435） | 下一步引导 | 机制存在 | 建议不跟随本轮操作语义（#461 修复） |
| `setNotice` 顶部横条（16 处） | 通知分级 | — | 信息级与阻断级混用同一横条；一线产品信息级不入横幅 |

## 3. 40% 缺口清单与演进路线

### P1 输入输出语义对应（已切片：#461）
- **参照系**：Generative UI（结果卡回指输入意图）
- **改动面**：fill 产物 `metadata.operation` + 前端按 operation 渲染标题/摘要 + 完成话术中文化 + `business_done(operations)` 建议参数化
- **验收信号**：输入「枚举值填充」→ 全程输出（消息/卡片/建议）无「标准字段映射」字样；真映射任务不受影响

### P2 通知分级与 inline 化
- **参照系**：AG-UI（事件即内容）；ChatGPT/ Claude 断线重连的内联系统条
- **改动面**：删 `App.tsx:792` notice 横条与 9 处信息级 `setNotice`（对话流已有等价信息）；4 处阻断类转 inline（编辑守卫→资源面板/composer 行内警告；字段变更守卫→字段变更卡；SSE 中断→对话流内系统条「连接中断，重连中」）
- **验收信号**：正常全流程零顶部横条；断 SSE 时对话流出现内联重连提示；编辑草稿未保存切页时有就近警告且草稿不丢

### P3 完成话术由执行数据生成
- **参照系**：LangGraph 工具调用结果叙事化
- **改动面**：执行器已有 `changed_count/before/after`（如 ENUM_FILL 日志），把每步的真实数据汇入完成消息（「枚举值填充已完成：事件结果 2 条规则已写入（allow→允许、deny→拒绝）」）；替换 worker.py 固定模板族
- **验收信号**：同一操作在不同数据下产出不同话术；话术含数字与字段名，无裸操作枚举

### P4 执行过程内联消息流（STEP 叙事）
- **参照系**：AG-UI `STEP_STARTED/FINISHED` + Dify 过程可见
- **改动面**：`run_progress` 事件在对话流消息内渲染为可折叠步骤时间线（进行中/完成/失败三态 + 依赖序）；轨迹页保留为深度诊断入口
- **验收信号**：执行中用户在对话流内能看到「正在填充(1/1) → 已写入配置」的过程叙事，无需切轨迹页

### P5 确认流文案与建议语义化（跟随 P3/P4 之后）
- **参照系**：LangGraph interrupt 审批对话框
- **改动面**：确认对话框引用具体操作与数据（「将把 2 条枚举规则写入事件结果字段」）；`classification_done`/`mapping_done` 建议同样按上下文回填
- **验收信号**：确认弹窗可独立理解（不依赖会话历史）；建议 chips 与当前产物一致

### 依赖关系
P1 独立；P2 独立；P3 依赖执行器步骤数据透传（小改）；P4 依赖 P2（横条腾退后叙事进场）；P5 依赖 P3/P4 的数据与组件基础。

## 4. 不做什么

- 不引入 AG-UI 协议依赖本身（V2 SSE 事件已同构，按其分类学命名与补齐即可）
- 不做多 agent 编排/可视化流程画布（与「解析规则处理」单域场景不匹配）
- 不动下载契约、草稿/撤销链路（P 系列全部为展示层与话术层）
