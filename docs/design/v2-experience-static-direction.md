# V2 前端静态视觉方向（已确认，待交互规格评审）

> 2026-10-30。两张图是静态设计稿，含演示文件和演示字段；不代表真实 Excel、Run 或 Skill/Tool 验收结果。用户已认可整体视觉方向及加宽后的默认对话区。本阶段没有制作新的交互原型。

## 同一任务的两种画面

| 画面 | 1440px 设计图 | 作用 |
|---|---|---|
| 默认对话 | [查看图片](concepts/v2-conversation-default.png) | 对话宽度约 900px；上传文件、进展、待确认动作和运行记录随相关消息出现。 |
| 映射工作区打开 | [查看图片](concepts/v2-mapping-workspace-open.png) | 对话保持可见；右侧字段映射区可拉伸、可关闭；草稿与应用状态分开。 |

## 已确认的交互原则

- 默认展示舒展的对话；只有出现需要审查或编辑的结果时，才打开右侧工作区。
- 映射工作区从对应的待确认消息打开。桌面端可拖动边界改变宽度，关闭后回到完整对话；重新打开时沿用服务端草稿。
- 应用成功后，结果与产物入口出现在对话中；右侧工作区保持打开，供用户继续复核或自行关闭。
- 运行记录从对应消息展开，按需查看步骤、Run ID、错误及真实 Skill/Tool 证据；未采集的身份不得推测。
- 1440px 为首要评审视口；1024px 下映射区占主画面，保留明确的返回对话入口。

## 视觉取舍

- 中性白与石墨色承担主界面；仅以克制的深青色区分主要操作，暖色提示待确认。状态必须同时有文字。
- 对话正文按阅读宽度排版；任务操作可占用更宽区域。减少重复标题、装饰标签和同质卡片。
- 图上的文件名、3 列及样例值只用于说明信息层级。实际字段、状态、产物和证据以 V2 API 及联合验收为准。

## 参考来源

- [ChatGPT Canvas](https://openai.com/index/introducing-canvas/)与 [Claude Artifacts](https://support.anthropic.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them)：对话保留上下文，成果在需要时获得独立工作空间。
- [Notion Agent](https://www.notion.com/help/notion-agent)：对话可以在侧栏或浮层出现，不必永久压缩主内容。
- [v0 工作区截图](https://www.saasui.design/application/v0)与 [Replit Agent 工作区](https://replit.com/blog/whats-changed-agent3-to-agent4)：结果可直接操作，并与对话保持联系。
- [LangSmith Trajectories](https://www.langchain.com/blog/langsmith-trajectories-tracing)：先阅读按顺序发生的会话动作，再下钻完整执行轨迹。

## 后续边界

前端体验重设计 PRD 已在本地形成实施规格，见 [PRD](../prd/v2-frontend-experience-redesign.md)。是否需要交互原型由用户另行决定；正式前端实施、旧视觉基线修订及 tracker 发布均不在本次静态设计交付中。
