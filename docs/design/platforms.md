# ToolWithAgent 平台与页面登记

本文登记公共日志知识库涉及的运行端，并把父 PRD #200 页面清单中的 DESIGN 复用项映射到 [DESIGN.md](./DESIGN.md) 的通用原语。页面布局、业务交互和状态规格仍以父 PRD 为唯一事实源；本文不重复页面规格。

## 唯一定位规则

页面使用 `platform-id / page-id` 作为唯一标识。`page-id` 只要求在所属平台内唯一，因此两个平台都可以拥有 `app-shell`，但引用时必须同时写出 `platform-id`。

## 平台登记

| platform-id | 运行端与环境 | app-shell | 登记页面 | 边界 |
|---|---|---|---|---|
| `chainlit-web` | 现有 Chainlit Web；用户在浏览器中进行聊天、上传文件和查看日志类型提取结果 | `chainlit-web / app-shell` | `app-shell`、`log-analysis-chat` | 复用现有聊天框架，不新增菜单、路由或管理入口 |
| `local-admin-web` | 部署机器的桌面浏览器；服务仅监听本机回环地址，并使用启动期临时令牌 | `local-admin-web / app-shell` | `app-shell`、`knowledge-review` | 独立的本机审核工具，不复用 Chainlit 会话壳层，不提供公网、局域网或移动端入口 |

## 页面与壳层

| 页面唯一标识 | 页面角色 | 所属壳层 | 父 PRD 用户故事 |
|---|---|---|---|
| `chainlit-web / app-shell` | 现有聊天框架 | 自身 | — |
| `chainlit-web / log-analysis-chat` | 日志分析会话中的知识申请入口 | `chainlit-web / app-shell` | US-3、US-4 |
| `local-admin-web / app-shell` | 本机审核台的安全边界与稳定壳层 | 自身 | US-11 |
| `local-admin-web / knowledge-review` | 日志知识申请审核工作区 | `local-admin-web / app-shell` | US-5～US-8、US-11 |

## DESIGN 原语映射

下表逐项覆盖父 PRD 页面清单中的“DESIGN 复用”。组合名称映射到最小通用原语，不在此派生新的页面组件。

| 页面唯一标识 | 父 PRD DESIGN 复用项 | `DESIGN.md` §5 原语 |
|---|---|---|
| `chainlit-web / app-shell` | 导航、按钮、Loading | 导航；按钮与交互；Loading |
| `chainlit-web / log-analysis-chat` | 次按钮、局部 Loading、就地错误反馈 | 按钮与交互（次按钮）；Loading（局部）；错误与就地反馈 |
| `local-admin-web / app-shell` | 顶栏、表面、错误、Loading | 导航（顶栏）；卡片容器；错误与就地反馈；Loading |
| `local-admin-web / knowledge-review` | 双栏导航、列表行、卡片、状态徽章、输入与表单、确认浮层、空状态、局部 Loading | 导航（双栏）；列表行；卡片容器；状态徽章；输入与表单；确认浮层；空状态；Loading（局部） |

## 验收结论

- `DESIGN.md` §5 已覆盖父 PRD 引用的全部通用原语；§6 保留证据阅读、人工批准、敏感原文和第一版范围约束。
- 两个平台的 `app-shell` 由复合标识唯一定位，功能页继承各自壳层。
- 两个平台继续复用“可信的运维台”、系统字体、等宽日志、低层级表面与文字按钮约束。
- 本登记不包含 mockup、PNG、业务路由、API、数据库代码或页面布局重述。
