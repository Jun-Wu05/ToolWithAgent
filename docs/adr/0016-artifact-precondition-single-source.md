# ADR-0016：可引用产物前置校验的单一来源

- 状态：已接受
- 日期：2026-10-12
- 关联：Issues #314、#320；PR #318、#321；ADR-0006、ADR-0009

## 背景

威胁填充与威胁类型映射都以先前的可引用会话产物为输入，其「产物可用」前置校验曾双份实现：执行器 `_validate_step` 按 facts 投影判定，适配器直连路径按 session 槽解析判定。两份实现已实际漂移——错误消息「不可用」与「已不可用」各走各的（#314、#320 复核证据），且全套件对这对拦截分支曾零覆盖，漂移无法被测试察觉。

## 决策

产物可用性前置校验收口为 `application/execution.py` 模块级公开函数，执行器预检与适配器直连路径共同消费。

- `threat_fill_source_precondition`（#314）与 `threat_mapping_source_precondition`（#320）是唯一实现：拦截结果非 None 时调用方原样返回；通过时返回已验证产物槽供直接使用。
- 判定基于 session 槽（`latest_threat_artifact` / `latest_enum_artifact`）解析，与 `referenceable_artifacts` 投影恒等——投影即由该槽解析生成，因此不保留第三份投影版实现。
- 防漂移由测试钉死：两条路径对同一坏会话必须产出相同 error_code 与 message（#321 引入的契约断言）。
- 消息文本统一「已不可用」家族（产物存在过、现已失效）。
- 演进规则：新增「以可引用产物为输入」的步骤类型时沿用该模式——模块级单源函数、双路径消费、同码同文防漂移断言。

## 后果

### 正面

- 拦截语义从「人工同步纪律」变为「单一来源 + 测试契约」，漂移即测试红。
- `_failed` / `_needs_input` 同步收敛为 `execution_policy` 唯一实现，适配器经导入再导出。

### 负面

- 执行核心 `execution.py` 承载具体步骤族的前置校验，公开面扩大；同类函数增多时需警惕膨胀，届时可评估独立 preconditions 模块（当前两个函数的规模不值得拆）。

## 与既有 ADR 的关系

ADR-0009 的「核心运行时只依赖 Contracts 与标准库」不被破坏——两个函数只依赖 Contracts 类型与标准库；「领域预检通过 ExecutionPolicy 注入」的接缝不变，本 ADR 只收口产物可用性这一特定族类。ADR-0006 的可引用产物语义继续有效。

## 同族收口（不单独立 ADR）

同期两项规模较小的单源收口遵循同一原则：#313 配置树遍历收口为 `agent/shared/mapping_utils.py` 三原语（13 处递归 walker 消费同一遍历）；#311 下载文件名契约迁入 `contracts/download_naming.py`（web 与 v2 共用唯一事实源）。
