# V2 工作台设计与实现规格

本目录为本地评审稿。`index.html`、`fixture.js` 和 `render.py` 固定渲染九张图片；前八张是约定的六个主状态、深色主题和 1024px 校验，第九张核对 1440×900。运行 `python -X utf8 docs/design/workbench-redesign/render.py` 可重建图片。发布 tracker 前先由用户过目。

## 图稿

| 图片 | 状态与检查点 |
| --- | --- |
| `01-chat-running.png` | 对话运行中；进展按步骤呈现，身份仅在消息边缘出现一次 |
| `02-chat-confirm.png` | 待确认与映射区；确认动作和来源字段同屏 |
| `03-chat-complete.png` | 完成与产物；结果、版本和下载入口同屏 |
| `04-trace-overview.png` | 轨迹总览；时间导航和紧凑事件账本 |
| `05-trace-selected.png` | 选中调用；右侧检查区有边界、换行和按需展开 |
| `06-trace-failure.png` | 失败定位与重试；错误代码、未执行步骤和修复方向 |
| `07-dark.png` | 深色轨迹；相同信息层级和状态语义 |
| `08-narrow-1024.png` | 1024px 收窄；导航缩成窄栏，账本与检查区仍可读 |
| `09-trace-1440.png` | 1440×900 核对图 |

## 数据来源与脱敏边界

图中 Run `a946359d` 来源于 2026-11-09 V2 验收归档：一次成功字段映射、约 45 秒、21 条 `run_events`、14 条模型调用、193 个字段、137 已匹配、56 未匹配。同一会话共导出 6 次 Run、61 条事件，时间带和实际页面均使用这组数据。`fixture.js` 保留当前 Run 的事件先后顺序、阶段、批次和本地时间；`run-fixture.json` 是前端截图使用的白名单投影。两者均不含原始参数、模型内容、日志或客户字段。会话文案、文件名、映射表的字段名和失败说明是**脱敏设计文案**；不表示验收库中逐字存在这些消息或字段。失败代码 `data_source_fields_required` 来自归档中另一次失败 Run `014806e5`；图中失败前的具体事件文案按状态展示，不充当原始日志证据。

## 布局与视觉规格

- 主参考视口 1850×670；另核对 1440×900 和 1024×670。桌面侧栏 220px，内容区左右留 27px；轨迹填满可用宽度。选中检查区约 365px，1024px 下约 300px。对话打开资源区时，资源区约 510px；1024px 下约 380px。实际 V2 资源区可拖动，保持已有宽度状态。
- 色值：底 `#F5F7F9`、表面 `#FFFFFF`、内嵌 `#EDF1F4`、正文 `#202A33`、次级 `#61717D`、操作 `#315E7A`。边界用 `#DCE3E8`。身份不用彩色标签；绿、黄、红仅用于状态。深色使用同等对比与层级。
- 正文 15px；轨迹行 14px；时间、状态和辅助信息 12px。Run ID、步骤 ID、时间与技术内容用等宽字体。列表行目标高度 37–39px；长摘要允许换行，行高随内容增加。选中态采用浅蓝灰背景和左侧 3px 标记。
- 按钮分主要动作、次要动作和文字动作；禁用态保持可读，并由 `disabled` 禁止操作。悬停只改变背景，键盘焦点用 2px 实线外框。减少无目的动效；状态变化可用短时背景过渡，遵守 `prefers-reduced-motion`。

## 交互规格

1. 对话与轨迹是同一会话的两个视图。切换时保留未发送文本、当前资源区内容、轨迹搜索与选中项；切换会话时清除旧会话的检查区和诊断详情。现有 `visitedTabs` 保持视图挂载。
2. 轨迹先显示 Run，再按 `Run.events.sequence` 展示事件；与用户消息按真实 `message_id` 关联。无关联时只显示 Run，不能捏造需求分组。产物以 `run_id` 关联。时间带按钮定位到 Run，点击行打开检查区；搜索匹配名称、摘要、Run ID 和步骤 ID，状态筛选可组合使用。每批最多 20 个 Run，继续载入下一批；每批最多 4 个并行详情请求。
3. 原始参数、结果和模型内容不进入总览。选中 Run 后明确点击“查看模型调用”，再选中调用与“参数/结果”标签，调用已有用户诊断接口，由服务端继续执行身份与脱敏规则。缺少摘要、时间、步骤或权限时分别显示“未采集”或服务端错误，不猜测内容。
4. 选中检查区有独立滚动；ID、JSON 和长文本使用 `overflow-wrap:anywhere`，技术正文 `pre-wrap`，最大高度限制内部滚动。1024px 下列表摘要换为两行；更窄视口检查区移到下方。`Tab` 可到搜索、筛选、时间点、事件、检查区和动作；`Enter`/`Space` 激活原生按钮，`Escape` 关闭检查区。
5. 失败 Run 提供错误代码与原因、完整诊断以及“重新执行”；运行中可停止。确认动作仍由原对话流程负责。工具调用若没有独立采集记录，界面显示“未采集”，不把模型调用或业务日志伪装成工具调用。

## 实现对应与数据缺口

`v2/frontend/src/TrajectoryLedger.tsx` 是当前可操作的轨迹实现，复用 `api.run`、`api.userDiagnosticRun` 和 `api.userDiagnosticCall`，没有公共 API 改动。对话、映射与产物仍由原 V2 组件负责；本轮以 Token 和轨迹布局改造为主。Run 详情已含按序事件；诊断接口有模型调用、步骤、日志和产物。**独立工具事件、调用与 Run 事件之间的精确因果链、原始工具参数/结果尚无统一可用账本字段**，后续若要在总览逐条合并，需先设计最小采集与授权投影。图中模型调用是按需检查区示意，不表示现有 Run 事件已经逐条带调用 ID。

## 本地对照截图

`10-implemented-overview.png` 至 `14-implemented-1440.png` 由 `v2/frontend/trajectory-preview.html` 渲染，使用同一份 `run-fixture.json`，覆盖轨迹总览、选中详情、深色、1024px 和 1440px。运行前先在 `v2/frontend` 启动 Vite，再执行 `python -X utf8 docs/design/workbench-redesign/render_implementation.py`。预览页只用于固定数据的组件视觉对照；完整应用的登录、会话切换和真实接口验收仍需在集成环境执行。

设计图是独立静态 HTML。静态图的会话文字和部分事件摘要经过脱敏编辑，因此对照以布局、层级、尺寸、排版、颜色、状态和展开行为为准；实际页的事件名称与状态以白名单导出的记录为准。当前先做本地评审，图稿中任何脱敏文案若需要换成真实会话文字，应由有权限的验收环境提供，不写入仓库。

## 2026-11-11 视觉确认

用户确认 `15-chat-running-1440.png` 对话效果作为还原基线。轨迹页隐藏整个底部输入区（含任务提示条、上传和发送）；切回对话保留草稿。预览与真实工作台同步使用该规则。按相同视口、字体和状态对照验收；本次确认不代表完整业务流程已验收。

## 2026-11-11 真实工作台集成证据

本轮把批准外壳落实到真实 App（侧栏 220px、主列 card 底、标题 57px、轨迹容器 20px 27px、清理死规则），完整记录见 [integration-verification.md](integration-verification.md)。

- **固定数据视觉对照**（真实 App 入口 + 本地 fixture API，同源批准数据）：`integration-chat-running-1440.png`、`integration-trace-no-composer-1440.png`；对话区与预览 0 像素差异，轨迹页底部与预览 0 像素差异。
- **真实测试会话**（uvicorn+worker、dev 模式、fake-runs 与真实上传）：`integration-real-{confirm,fail,success,artifacts,trace,developer}-1440.png`；轨迹页 composer `display:none` 高度 0、无可聚焦控件、草稿往返保留均有 DOM 断言。
- **可用性**：`integration-chat-1024.png`、`integration-chat-narrow-390.png`、`integration-chat-dark-1440.png`、`integration-trace-1024.png`，各视口无横向溢出。
- **回归**：定向 50 项、前端全量 227 项（第 3 次全绿，前两次为并行负载超时抖动，已记录）、构建通过、lint 仅 1 条已知误报警告；根全量 pytest 结果见 verification 文档。

最短启动（与本轮验收一致）：`v2/frontend` 起 Vite（5173）；worktree 根目录设 `V2_DATA_DIR/V2_MODE=development/V2_WORKER_CONCURRENCY=1/PYTHONPATH=v2/backend` 后用 `tmp/venv` 分别起 uvicorn（8100）与 `toolwithagent_v2.runtime.worker`。
