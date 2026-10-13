# ADR-0015：测试与生产共用唯一组合根

- 状态：已接受
- 日期：2026-10-12
- 关联：Issue #312；PR #319；ADR-0009

## 背景

ADR-0009 已确立 `create_default_adapters(team)` 为生产唯一组合入口，但测试侧长期存在第二分派真相：`ProfessionalAgentAdapter` 以 isinstance 链只认识部分步骤类型（迁移时 26 处测试引用），与 `composition.py` 的注册表各自演化。生产新增适配器不会自动进入测试视野；旁路认识的步骤集合过时时，测试将静默偏离生产分派路径，且这种漂移没有门禁可拦截。

## 决策

测试与生产共用同一组合根，删除测试专属分派旁路。

- 测试以 `create_default_adapters(team)` 为基座构造分派表，需要假件时按注册键覆盖单个条目（如 `["field_mapping"]`）；不再构造只认部分步骤类型的测试分派器。
- `application/adapters/professional.py`（isinstance 链旁路）删除，`adapters/__init__.py` 不再导出；同一步骤类型自此只有一个分派真相。
- 最小装配用法不受影响：`PlanExecutor({"field_mapping": adapter})` 仍合法，注册表条目取出的即适配器实例，测试注入与生产共享同一对象形态。
- 生产新增适配器自动进入测试视野：分派回归只可能发生在 `composition.py` 一处。

## 后果

### 正面

- 分派语义单一来源，测试路径即生产路径。
- 测试假件注入有统一模式（组合根基座 + 按注册键覆盖）。

### 负面

- 测试对组合根的构造副作用敏感，team 装配成本计入测试。
- 需要假件的用例必须了解注册键名，键名变更同时波及生产与测试。

## 与既有 ADR 的关系

扩展 ADR-0009「Application Adapters」小节中「`create_default_adapters(team)` 是唯一组合入口」的适用范围：由生产入口扩展到测试入口，其余结论不变。已知遗留：`field_runtime` 的 `init_field_cache` 仍由 `web/start_handler.py` 直连消费（#319 记录，不属于本决策范围）。
