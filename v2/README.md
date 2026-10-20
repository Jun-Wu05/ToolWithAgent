# ToolWithAgent V2 独立入口

V2 API、Worker、前端与原 Chainlit 入口并行运行。默认端口为 API `8100`、React `5173`；SQLite、上传文件和 Python 环境只放在当前 worktree 的 `tmp/` 中。当前支持主数据与枚举映射附件校验、日志类型提取、日志知识申请、字段映射、枚举提取、威胁类型映射、枚举/威胁填充、取消映射与兼容导出；成功产物可跨刷新/重启和后续轮次复用。业务通过既有 Application 执行；自然指令创建 Task/Run，方案确认恢复冻结计划而不重新规划，Run 同时支持持久进度、取消和重跑。字段映射结果默认显示对话摘要，可原位放大为编辑器，按子规则搜索、筛选、分页、自动保存 Draft，确认占用替换和精确路径联动，并原子应用为新版本或下载正式结果。

## 本地启动（PowerShell）

以下命令均从本 worktree 根目录执行：

```powershell
python -m venv tmp/venv
tmp/venv/Scripts/python.exe -m pip install -e './v2/backend[test]'
$env:V2_DATA_DIR = (Join-Path (Get-Location) 'tmp/v2-data')
$env:V2_MODE = 'development'
$env:V2_WORKER_CONCURRENCY = '1'
$env:PYTHONPATH = 'v2/backend'
```

分别在独立终端（设置相同的 `V2_DATA_DIR` 与 `PYTHONPATH`）启动：

```powershell
tmp/venv/Scripts/python.exe -m uvicorn toolwithagent_v2.main:app --host 127.0.0.1 --port 8100
```

```powershell
tmp/venv/Scripts/python.exe -m toolwithagent_v2.runtime.worker
```

前端从 `v2/frontend` 运行 `npm install`、`npm run dev`。前端开发代理指向 `http://127.0.0.1:8100`。

首次启动 API/Worker 自动执行 Alembic migration。开发模式默认 `dev-user`，可通过 `GET /api/v2/dev/identities` 和 `POST /api/v2/dev/session` 切换测试身份。生产模式不注册这些开发路由，也不会自动选择模拟身份；生产身份接入属于后续切片。

## 当前 API

- `GET /health/live`、`GET /api/v2/me`
- `GET/POST /api/v2/conversations`、`GET /api/v2/conversations/{id}`
- `POST /api/v2/conversations/{id}/messages`（创建自然语言业务 Task/Run；保留消息字段并增加 `task/run`）
- `POST /api/v2/conversations/{id}/log-parse`（显式文件与可选分类字段）
- `POST /api/v2/artifacts/{id}/submit-log-knowledge`（当前合格分类的显式申请）
- `POST /api/v2/conversations/{id}/field-mapping`（`file_id` 或 `classification_artifact_id` 二选一；`product`、`log_vendor` 必填，`data_source` 可留空；接受 `Idempotency-Key`）
- `GET /api/v2/artifacts/{id}/mapping-view?sub_rule=0&page=1&q=&status=`（仅本人结果；每页 50 行，搜索/筛选作用于整个选定子规则；返回事件名称标注明细和业务警告）
- `GET /api/v2/artifacts/{id}/download`（本人映射配置；复用既有 Base64 内容与文件名）
- `POST /api/v2/conversations/{id}/files`（multipart `file`，返回 file/task/run）
- `GET /api/v2/runs/{id}`、`GET /api/v2/conversations/{id}/events?after=N`（SSE）
- `POST /api/v2/runs/{id}/retry`（可带 `Idempotency-Key`，复制原 Run 的冻结快照）
- `POST /api/v2/runs/{id}/cancel-token` → `POST /api/v2/runs/{id}/cancel`（body 包含一次性 `token`）
- `POST /api/v2/runs/{id}/confirmation-token` → `POST /api/v2/runs/{id}/confirm`（body 包含 `token`、`checkpoint_revision`；重新领 token 可跨刷新恢复）
- `POST /api/v2/admin/runs/{id}/force-stop`（仅 Admin，body 包含非空 `reason`）
- 开发模式专用：`POST /api/v2/dev/conversations/{id}/fake-runs`（`scenario` 为 `success`、`confirm` 或 `fail`；仅用于持久化故障演示）

上传和消息命令接受 `Idempotency-Key`；相同身份、会话、key 和输入返回同一结果，换输入复用 key 返回 `idempotency_key_reused`。上传支持 `.csv`、`.txt`、`.log`、`.json`、`.jsonl`、`.xlsx`、`.b64`，默认上限 20 MiB。文件内容由 Worker 校验类型和哈希，状态从数据库事件表推送；刷新或重启后 REST 查询可恢复。所有 API 文件响应只包含安全元数据，不返回存储路径。

重跑保留历史 Run；当前 Run 的取消或强停立即撤销发布资格，旧 Worker 的迟到结果不能写入 Artifact。等待确认时，checkpoint、确认事项和 SSE 事件在同一事务内保存；确认后由 Worker 从下一动作续跑。Blob 先写 staging 并 fsync、校验哈希、改名为内容寻址文件，再与 Run 状态和事件一起提交数据库。启动对账仅清理超过一小时且无引用的 staging／孤儿文件，避免与正在发布的 Worker 竞争。

## 后端验证

每次运行 pytest 前固定临时目录，避免 Windows 的默认 TEMP 权限和路径问题：

```powershell
New-Item -ItemType Directory -Force 'tmp/system' | Out-Null
$env:TEMP = (Resolve-Path 'tmp/system').Path
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PYTHONPATH = 'v2/backend'
tmp/venv/Scripts/python.exe -c "import os,tempfile; assert tempfile.gettempdir()==os.environ['TEMP']"
tmp/venv/Scripts/python.exe -m pytest -q v2/backend/tests --basetemp=tmp/pytest-v2 -o cache_dir=tmp/pytest-cache
```


映射命令冻结文件、可选分类及规则数据源元数据，成功发布前再次检查主数据、分类与 Run 发布资格。正常未匹配允许成功；失败、取消或输入过期不发布部分结果，旧成功产物仍可查看和下载。只有最新且上游有效的映射被标记为当前结果。摘要和执行事件仅含计数；字段与样例通过本人主动打开的受保护结果接口读取。样例行号是日志条目序号，配置样例没有日志条目序号，不等同于 Excel 工作表行号。

事件名称待确认或自动威胁类型链路产生业务警告时，主字段映射仍按既有 Application 语义成功。普通摘要只增加待确认数量和预定义警告码，完整警告与最终标注明细只在本人打开的结果视图中展示，不进入普通事件或运行诊断。

当前字段映射契约没有数值匹配度和歧义标记；表格展示既有匹配状态作为依据，自动匹配行在每个状态组内保持原字段顺序，人工选择行优先。按真实匹配度排序及歧义提醒需要业务先提供可信证据，本轮不虚构分数或设置前端阈值。

## 字段映射 Draft（#267 冻结契约）

正式映射 Blob 不可变。编辑只保存本人 Draft；未应用的实际修改不会成为后续任务输入，并在服务重启后恢复。`GET /conversations/{id}` 的 `drafts` 仅含安全摘要，不含字段、样例或操作内容。多个旧来源 Draft 可逐个恢复、丢弃；`base_current=false` 时不能编辑或应用，但可读取和明确丢弃。

所有以下路径带 `/api/v2` 前缀。写操作仅允许 User 操作自己的资源；其他用户资源返回 404，Developer/Admin 写操作返回 403。

- `POST /artifacts/{id}/mapping-drafts`：获取或创建当前映射的 Draft，返回 `Draft`。
- `GET /mapping-drafts/{id}`：恢复完整本人 Draft。
- `GET /artifacts/{id}/mapping-view?draft_id={id}&sub_rule=0&page=1&q=&status=`：叠加草稿，整条子规则搜索/筛选后按 50 行分页。未传 `draft_id` 仍是正式产物。
- `GET /standard-fields?draft_id={id}&sub_rule=0&q=`：返回 `items[{name,category,occupied_by,disabled_reason}]`，只使用标准表规范中文名并排除事件名称、事件级别、日志类型、威胁类型。占用目标仍可见，`occupied_by` 是完整原始字段路径；占用不代表下拉禁用，选择后需要确认替换。
- `PATCH /mapping-drafts/{id}/operations/{operation_key}`：自动保存当前字段及明确选择的联动范围。
- `GET /mapping-drafts/{id}/same-source-candidates/{operation_key}`：读取已保存操作的精确同路径候选。
- `POST /mapping-drafts/{id}/replacement-confirmations`：确认或取消占用替换。
- `POST /mapping-drafts/{id}/apply`：冻结完整修改并排队新的确定性 Task/Run，返回 `{task,run,draft}`，HTTP 201。排队不是应用成功；等待 Run `succeeded` 且 Draft `applied`/`applied_artifact_id`，再继续发送原指令。
- `DELETE /mapping-drafts/{id}`：明确丢弃，返回 Draft `discarded`。正在应用时先等待或取消 Run。

`Draft` 字段如下：

```json
{
  "id": "...", "conversation_id": "...", "base_artifact_id": "...",
  "revision": 2, "status": "active", "changed_count": 1,
  "operation_count": 1, "apply_run_id": null, "applied_artifact_id": null,
  "base_current": true,
  "operations": [{"operation_key": "row-...", "proposal": {"sub_rule_id": "0", "source_path": "src.ip", "standard_field": "源地址", "linked_sub_rule_ids": []}, "changes": [{"sub_rule_id": "0", "source_path": "src.ip", "standard_field": "源地址"}]}]
}
```

普通 conversation 的 Draft 摘要省略 `operations` 和 `operation_count`；`changed_count` 是相对基准正式产物的实际最终字段变更数，回退至原状态可归零，归零不阻止发送新消息。Draft 状态为 `active` / `applying` / `applied` / `discarded`。编辑投影行额外返回：`sub_rule_id`、稳定 `operation_key`、`draft_modified`、`group_status`、`editable`、`disabled_reason`。`editable=false` 的平台固定来源或已占用平台固定目标行只读（后端同样拒绝调整）。正常威胁链的独立“威胁类型”条目与 `%{source}` 提取绑定不被字段关系编辑改变，原始字段/result始终保留。`user_modified`/“用户选择”表示人工证据（也可能来自基准正式产物）；`draft_modified` 才表示本 Draft 的未应用修改。UI 按 `group_status` 保持原组和原行位置，`status` 显示实际当前状态，应用后新正式产物重新排序。

PATCH、替换确认、apply、DELETE 必须传 `If-Match: <revision>`。apply 和替换确认同时必须传 `Idempotency-Key`，相同请求重试复用持久 receipt。PATCH 使用后端行返回的 `operation_key`，该 key 固定绑定子规则位置和完整路径，不由 UI 随意生成；同操作最新 revision 下的相同请求不重复增加 revision。子规则 `id` 是位置字符串，重复显示名不会混淆。

PATCH body：

```json
{"sub_rule_id":"0","source_path":"src.ip","standard_field":"源地址","linked_sub_rule_ids":[]}
```

`standard_field=null` 表示取消映射，保留原字段。默认只修改当前子规则；`linked_sub_rule_ids` 仅包含用户明确选择且无占用冲突的其他精确同路径子规则，不接受模糊名或末段名。成功返回 `{draft,candidates}`；`candidates` 为 `{source_path,standard_field,items[{sub_rule_id,name,current_standard_field,samples,selectable,conflict_source_path,selected,disabled_reason}]}`。`disabled_reason` 是兼容新增字段：平台固定来源或固定目标保护为 `mapping_source_not_editable`，目标占用为 `mapping_target_conflict`，可选候选为 `null`；同时存在只读和占用时优先显示只读保护原因，`conflict_source_path` 仍保留占用信息。只有可编辑且无占用的候选 `selectable=true`；伪造不可选的 linked ID 仍返回 `mapping_link_conflict`，不保存修改。后续可 GET 候选或用相同 operation key PATCH 新范围；整组选中修改保存在同一操作内。

选择已占用目标返回 HTTP 409 `mapping_target_conflict`，不保存任何变化。错误 `details` 返回 `{operation_key,proposal,occupied_by,candidates}`，即使该操作尚未保存也足够打开一次替换与联动范围对话框。UI 可在 `proposal.linked_sub_rule_ids` 中放入明确选中的 eligible IDs，再提交：

```json
{"operation_key":"row-...","proposal":{"sub_rule_id":"0","source_path":"src.ip","standard_field":"源地址","linked_sub_rule_ids":["2"]},"confirm":true}
```

确认在相同 revision 下重新验证，以一个原子操作清空当前子规则原占用者、赋值当前字段并保存显式联动。`confirm=false` 不改变 Draft/ revision。其他子规则占用冲突项始终 `selectable=false`，不能借替换确认绕过。改目标、取消、回退或改变联动范围时，先前操作的旧占用清理和已取消的联动不会残留。

稳定错误码：缺少 `If-Match` 为 428 `draft_revision_required`；非法 header 为 400 `invalid_draft_revision`；过期 revision 为 409 `draft_revision_conflict`（details 当前 revision），必须停止写入并明确重新加载。409 还包括 `mapping_target_conflict`、`mapping_link_conflict`、`mapping_base_stale`、`mapping_catalog_changed`、`draft_apply_in_progress`、`draft_not_editable`、`draft_resolution_required`、`mapping_draft_apply_stale`、`idempotency_key_reused`。非法目标/来源/key/scope、空 Draft 或缺少幂等 key 返回 400。Owner 编辑接口可返回错误位置；普通消息、SSE 与 Run 不暴露字段或业务值。

apply 冻结 base 内容、Draft revision/operations、当前目录版本及原 Run 的 Provider/Prompt/标准字段审计版本，不调用模型。Worker 在同一发布事务重查 revision、当前来源、目录版本、lease/leader/fence，生成会话内递增版本、新 Task/Run 与 `mapping_edit` 血缘，完成 Draft 并把旧产物及已有下游标为 stale。改变映射目标时清理旧目标的值映射/默认值，保留字段提取样例。失败、取消、失联或上游变化均保留可恢复 Draft 和原正式产物；旧失败 Run 不能覆盖后来编辑。旧自动映射运行在成功人工应用后失去发布资格，正常自动映射排队不受影响。

存在实际未应用修改时，新的 `POST /conversations/{id}/messages` 返回 409 `draft_resolution_required`；用户必须选择应用后发送、丢弃后发送或返回编辑。已成功消息的相同 receipt 重放仍返回原结果。发送入口不能把 Draft operations 作为业务输入。
## Draft 编辑范围与验收边界

草稿编辑和恢复沿基础正式版本保持固定行序与分组。正式应用的新版本按实际状态与人工修改优先重新排序；重新打开未应用草稿时的重排仍是已记录的 Spec Minor。

原生下拉选择即时自动保存，保存期间禁用关联控件。技术规格中的 300–500ms 防抖尚待后续交互完善，快速键盘切换可能需要等待当前保存完成；保存失败的选择可保留并重试。

浏览器视觉、真实 Provider、双入口真实样本与平台导入仍待人工验收；本轮自动验证不能替代合入 master、正式发布与入口切换的门槛。


## 后处理与跨轮产物（#276 冻结契约）

V2 独立环境通过 `python -m pip install -e "v2/backend[test]"` 安装声明的业务与 API 依赖；不需要 Chainlit。Agno/OpenAI/SQLAlchemy 与现有入口固定版本一致。启动真实业务前仍需项目 `.env` 与只读标准字段及其本地缓存，运行时不会自动生成远程 embeddings。

业务 Blob 只保存固定白名单中的业务状态，恢复为共享 `SessionState` 的 V2 类型；不会序列化 Team、模型密钥或其他运行时对象。已有白名单 JSON 状态继续通过同一恢复边界读取。

所有以下路径均带 `/api/v2` 前缀。上传 multipart 增加 `role=primary|enum_mapping`，默认 `primary` 兼容已有客户端。枚举附件必须 `.xlsx`，Sheet 名是目标字段，三列沿既有 `mappingType/orgValue/mappingValue` 协议；完整解析通过才生效。不同 Sheet 累积、同名 Sheet 完整替换，附件不会切换当前主数据。普通文件投影增加 `role`，原 file/task/run 字段保持。

`POST /conversations/{id}/messages` body 仍为 `{"content":"指令"}`，返回原 `id/actor/kind/content/created_at` 加 `{task:{id,status},run:{id,status}}`。自然语言只调用 Planner 一次；缺参/歧义通过助手追问结束本次 Run，不猜测，也不读取未应用 Draft。未应用修改返回 409 `draft_resolution_required`；等待方案确认返回 409 `confirmation_resolution_required`。成功 receipt 重放优先返回原结果。

按钮用 `POST /conversations/{id}/operations`，接受 `Idempotency-Key`，返回 `{task,run}`。body 是 `{"step":<严格既有 StepSpec>,"source_artifact_id":null,"config_artifact_id":null}`，两个 ID 可省略；操作源于结果卡时必须传对应卡的明确 ID，过期卡不能自动换到新产物。UI 使用固定 `step_id="operation"`，不构造 `step:` 引用或 `depends_on`。五种最小示例：

```json
{"step":{"step_id":"operation","type":"enum_extract","target_field":"alarm","source_ref":"session.logs"}}
{"step":{"step_id":"operation","type":"threat_mapping","source_ref":"session.artifacts.enum_values"},"source_artifact_id":"当前枚举产物ID"}
{"step":{"step_id":"operation","type":"fill","fill_kind":"enum","target_fields":["事件结果"],"source_ref":"session.enum_mapping_table","config_ref":"session.decoded_config"},"config_artifact_id":"当前配置产物ID"}
{"step":{"step_id":"operation","type":"fill","fill_kind":"threat","target_fields":["威胁类型"],"source_ref":"session.artifacts.threat_mapping","config_ref":"session.mapped_sub_rules"},"source_artifact_id":"当前威胁产物ID","config_artifact_id":"当前配置产物ID"}
{"step":{"step_id":"operation","type":"remove_mapping","target_fields":["status"],"config_ref":"session.decoded_config"},"config_artifact_id":"当前配置产物ID"}
{"step":{"step_id":"operation","type":"export","source_ref":"session.decoded_config"},"config_artifact_id":"当前配置产物ID"}
```

`config_ref` 只允许 `session.decoded_config`（上传规则）与 `session.mapped_sub_rules`（日志生成配置）。威胁直接值映射改用 `source_ref="user.values"` 和明确 `values`；威胁填充目标固定为“威胁类型”。规则导出还支持既有 `session.log_classification.entry_rules|sub_rules`，对应分类卡传 `source_artifact_id`。缺参数/非法 Literal 返回 422；按钮依赖返回 400 `button_dependencies_forbidden`；旧卡返回 409 `artifact_source_stale|config_source_stale`。枚举附件更新后须重填，旧来源导出失败 `enum_refill_required`，失败不覆盖旧正式结果。

Artifact 目录 `kind` 增加 `enum_values/threat_mapping/config_export`，配置更改仍属于兼容 `field_mapping` 族，使 mapping-view/Draft 始终基于最新正式配置。目录中的计数是 `summary.item_count`（配置族为原有 summary 计数），另有 `source_field/current/status`，配置族另有明确 `config_ref` 与身份、时间；`message_id` 指向原用户消息，`result_message_id` 指向同事务发布的助手结果。消息投影增加可空 `run_id`，Run 投影增加可空 `message_id`。内部 `business_state` 不进入结果目录或内容/下载接口。原始值只通过本人主动请求 `GET /artifacts/{id}/content` 返回：枚举 `{artifact_type,item_count,values,field,regex,original_log}`，威胁 `{artifact_type,item_count,mappings:[{mapping_type,original_value,mapped_value}],source_field}`，导出 `{artifact_type,item_count,content,download_kind}`；配置沿现有 mapping payload。`GET /artifacts/{id}/download` 按类型返回 JSON/XLSX/Base64 TXT 和既有文件名；旧历史结果仍可本人查看/下载，不参与当前输入自动绑定。

proposal 真实冻结完整类型化计划和输入版本，进入 `waiting_confirmation`；`POST /runs/{id}/confirmation-token` 返回既有 token/checkpoint_revision/kind/expires_at，`kind=business_plan`，payload 为 `{question,choices,operations}`。`POST /runs/{id}/confirm` body 仍为 `{token,checkpoint_revision}`，增加可选 `Idempotency-Key`，同请求重放不重复入队。恢复走同一 Executor 循环，成功步骤账本保留、`step:` 依赖保留、已耗恢复预算不重置，确认不调用 Planner。内容哈希、来源 ID、状态、lease/epoch/fence 在确认和发布边界重查；输入改变返回 `continuation_stale` 或 Run `business_input_stale`，取消/Worker 接管禁止迟到结果发布。

后端离线自动验证覆盖规则 dict 根和未知键保留、附件重填、跨刷新/重启 typed 槽位、原子多产物发布、真实 proposal 确认、成功前缀/恢复预算、本人内容授权和日志隐私。真实 Provider、双入口脱敏业务样本、平台导入与浏览器交互仍按既有人工验收门槛完成。


`GET /conversations/{id}` 增加 `session_facts: SafeSessionFacts|null`、`session_facts_error: string|null`。结构是 Contracts `build_session_facts` 的按钮白名单投影，只有 `has_logs/has_log_classification/has_decoded_config: boolean`、`enum_mapping_row_count/mapped_sub_rule_count: number` 与下述三个目录字段；不会把原始字段路径或规则名目录加入普通会话响应。按钮使用 `available_config_refs: string[]`、`enum_mapping_target_fields: string[]`、`referenceable_artifacts: [{source_ref,artifact_type,source_field,item_count,target_bindings:[{config_ref,target_field}]}]`，不包含枚举原值或威胁映射内容。无输入是合法空事实；重建/哈希失败明确返回 `session_facts=null`、`session_facts_error="business_input_unavailable"`，UI 保留历史结果可读、禁用依赖按钮并展示就地错误，不能把此错误当成“没有输入”。


真实执行进度通过原 SSE `run_progress` 事件与 `GET /runs/{id}` 的 `events` 恢复。每项事件为 `{sequence,scope_type,scope_id,event_type,status,summary,created_at}`；`summary` 只含 `{phase,progress_status,operation,dependency_scope_ids}`，phase/status 是既有枚举，operation 是既有业务类型或 null，scope/dependency IDs 是单 Run 内稳定生成的匿名哈希。UI 可显示当前步骤、阶段、终态和依赖，不解析模型文本。原始 plan/step ID、用户值、问题、message_code 与任意 Tool detail 不进入该时间线。取消或 lease/epoch/fence 失效后拒绝迟到进度。


下载内容与本人内容 API 区分：枚举 JSON 下载保持 Chainlit 的 `{field,regex,original_log,value}`（不是 typed `values` 包装）；日志分类 JSON 下载保持分类对象自身根结构；威胁 XLSX 保持 sheet `threat_mapping` 与列 `mappingType/orgValue/mappingValue`。三者复用既有中文 UTF-8、JSON 缩进与下载文件名契约。


明确清空沿原消息接口发送 `POST /conversations/{id}/messages` body `{"content":"清空数据"}`（既有 Application 完整清空命令同样支持），返回原消息字段和 `task/run`（初态 queued，Run kind 为 `business_clear`）。不调用 Planner 或模型；入队事务取消旧活动 Run/确认，释放同会话串行队列，明确清空可越过待确认/未应用 Draft 守卫。Worker 的领取 fence 事务按命令入队时冻结的 ID 范围最终停用原主数据及枚举附件、失效正式配置/typed 状态/贡献/重填/checkpoint，并返回助手回执“业务数据已清空，历史结果仍可查看和下载。”；失败的旧 Worker 无权迟到发布。刷新或重启后的业务事实为空。历史文件保留原 role/parse_status，新增 `active:boolean`，清空后为 false；前端停用其解析与映射动作，保留历史列表。历史 Artifact 为 stale/current=false，配置、分类、枚举、威胁和导出内容仍经本人接口可读/下载。命令入队后上传的新文件及其后续任务保留，创建 active=true 的新输入；清空不解析旧 Blob，旧内容损坏也能完成，提交前再次检查 lease/epoch/fence。

生产运行中首次白名单瞬时失败耗尽自动恢复预算时，保存执行器真实冻结计划、成功前缀账本、已用预算及实际 staging（包括显式威胁事务副本），转入 waiting_confirmation。执行前 proposal 的首次确认执行同样适用。此时 confirmation payload 可附 `reason_code="recovery_exhausted"`，问题和选项为安全静态文案；确认只重试未完成步骤，原恢复预算不重置。人工恢复后的再次失败终止 Run，不反复创建待确认循环；参数缺失或来源歧义仍结束为安全追问，不能靠确认猜参数或改变冻结计划。

## 视觉基线自检（#307）

颜色、字体、圆角、焦点及明暗主题按 `docs/design/v2-visual-baseline.md` 实施。运行 `python scripts/check_v2_visual_tokens.py` 可逐项对照规格中的 21 项浅色和 21 项深色颜色，并输出源码行号；同时检查变量引用、组件硬编码颜色和四个工具类。脚本只读，不更新规格。

主题沿用本机 `twa-v2-theme` 记忆，在首次绘制前初始化；系统原生控件随主题切换。颜色自检和自动回归不代替 #310 的明暗视觉人工终验。

## 视觉公共原语（#308）

`v2/frontend/src/VisualPrimitives.tsx` 提供状态圆点与文字、运行/待确认/失败提示条、上下文抽屉、折叠工具调用块及耗时/Token 格式化。工作台通过 `PanelState = null | {type: 'execution' | 'artifact'; id: string}` 管理唯一上下文；默认关闭，关闭恢复工作区，窄屏使用覆盖布局。抽屉支持 Esc、标签页方向键和焦点返回，切换标签不丢失未提交输入。

当前工作台复用本人 Run/Artifact 的受保护接口和既有异步响应隔离。工具调用块只承载调用方已获准展示的数据，默认折叠；Developer 调用数据接入由 #270 完成，不从普通用户摘要构造调用详情。快捷入口、Composer 及其余页面视觉应用由 #309 持续补齐，明暗视觉人工终验仍待 #310。
