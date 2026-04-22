# Task: 将 auto/ 三阶段流水线转换为 Copilot Agent（allinone）

## Approach

将 `auto/` 目录中现有的三阶段安全日志标准化流水线（Phase1 确定性解析 → Phase2 LLM 字段映射 → Phase3 正则批量提取）封装为一个统一的 Copilot Agent，采用 **方案A（.agent.md 声明 + 5 工具 ReAct 循环）**，使原本需要手动逐步执行的流程可通过自然语言指令自动编排完成。

## Scope

### In（范围内）
- 创建 `auto/allinone/` 目录结构，包含 `.agent.md` 声明文件
- 封装 5 个工具：`phase1_decode`、`phase2_map`、`phase3_extract`、`threat_classify`、`load_config`
- 实现 ReAct 循环编排：确定阶段自动串联，LLM 阶段提供上下文注入
- 将 Phase2 提示词模板（强匹配/弱匹配）集成为 Agent 知识
- 将威胁类型分类（`威胁类型.md`）封装为独立工具
- 将标准字段数据（`标准字段.txt`）通过 `load_config` 工具按需加载
- 编写端到端测试流程验证 Agent 编排能力

### Out（范围外）
- 不实现 MCP Server（方案B，留作未来扩展）
- 不修改现有 `phase1/index.py`、`phase3/field.py` 的核心逻辑
- 不开发 GUI 界面或 CLI 入口
- 不重构现有 Phase2 的 LLM 调用方式（保持提示词模板机制）

## Phases

### Phase 1: 项目骨架与 Agent 声明
- [ ] 创建 `auto/allinone/` 目录结构（`tools/`、`knowledge/`、`docs/`）
- [ ] 编写 `.agent.md` 声明文件，定义 Agent 名称、描述、模型、工具列表
- [ ] 在 `.agent.md` 的 description 中包含触发示例（如"帮我处理这份安全日志"）

### Phase 2: 封装 Phase1 解码工具
- [ ] 创建 `tools/phase1_decode.py`，导入 `decode_base64_text()`、`extract_normalize_indexes()`、`_extract_original_log_result()`
- [ ] 封装为工具函数：接收原始文本 → 返回标准化索引列表 + 原始日志结果
- [ ] 添加输入校验（非空文本、Base64 格式检测）和错误处理

### Phase 3: 封装 Phase2 LLM 映射工具
- [ ] 创建 `tools/phase2_map.py`，集成强匹配/弱匹配提示词模板
- [ ] 工具函数：接收标准化索引 + 原始日志 → 调用 LLM → 返回标准字段映射结果
- [ ] 将 `提示词-强匹配.md` 和 `提示词(弱匹配).md` 复制到 `knowledge/` 目录
- [ ] 实现三一致校验逻辑（原始日志/标准化索引/标准字段说明必须对齐）

### Phase 4: 封装 Phase3 正则提取工具
- [ ] 创建 `tools/phase3_extract.py`，导入 `read_log_lines()`、`process_log_once()`、`reorder_log_lines()`
- [ ] 工具函数：接收日志路径 + 字段键 + 正则模式 → 返回提取结果 + 映射 + 重排
- [ ] 未匹配行自动归入 `未匹配` 分组，保持原逻辑

### Phase 5: 威胁类型分类工具
- [ ] 创建 `tools/threat_classify.py`，加载 `威胁类型.md` 中的 100+ 标准分类
- [ ] 工具函数：接收威胁描述 → 返回匹配的标准威胁类型
- [ ] 将 `威胁类型.md` 复制到 `knowledge/` 目录作为参考数据

### Phase 6: 配置加载工具
- [ ] 创建 `tools/load_config.py`，支持按需加载 `标准字段.txt`（700+ 字段定义）
- [ ] 工具函数：接收配置名称 → 返回结构化配置数据（解析 Tab 分隔的 7 列格式）
- [ ] 支持按属性分类、字段名称等维度检索标准字段

### Phase 7: 端到端测试与文档
- [ ] 编写端到端测试：模拟完整流水线（Phase1 → Phase2 → Phase3 → 威胁分类）
- [ ] 验证 ReAct 循环编排：确定性阶段自动切换，LLM 阶段正确注入上下文
- [ ] 更新 `auto/allinone/docs/` 中的使用说明文档

## Decisions

| Decision | Rationale | Date |
|----------|-----------|------|
| 方案A（.agent.md + 工具）优于方案B（MCP Server） | Agent 方式开发快、调试直观，未来可平滑升级为 MCP | 2025-06 |
| 5 工具 ReAct 循环模式 | 每阶段独立工具便于调试和复用，ReAct 循环支持灵活编排 | 2025-06 |
| Phase1/3 确定性封装，Phase2 LLM 集成 | 遵循现有架构：确定性代码直接调用，LLM 部分保留提示词模板 | 2025-06 |
| 数据文件通过 load_config 按需加载 | 避免硬编码 700+ 标准字段，保持数据与代码分离 | 2025-06 |
| 不修改现有 phase 代码 | 最小侵入原则，通过导入封装而非重写 | 2025-06 |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| （暂无） | — | — |
