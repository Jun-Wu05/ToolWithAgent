# Findings: auto/ 流水线分析与 Agent 设计发现

## 1. 三阶段流水线架构

### Phase1 — 确定性 Base64 解码与标准化索引提取
- **核心函数**：
  - `decode_base64_text(text)` — Base64 解码，自动修复 padding，UTF-8 错误处理
  - `extract_normalize_indexes(text)` — JSON 优先 → 正则回退的双重提取策略
  - `_extract_indexes_from_obj(obj)` — 递归提取嵌套 dict/list 中的 index 字段
  - `_extract_original_log_result(text)` — 定位 `index=="original_log"` 并返回 result 数组
- **特性**：完全确定性，无 LLM 依赖，适合直接封装为工具
- **输入**：原始解析文件 + index 数据文件
- **输出**：`normalize_indexes.txt`

### Phase2 — LLM 驱动的标准字段映射
- **强匹配规则**（三一致）：原始日志 / 标准化索引 / 标准字段说明必须完全对齐
- **弱匹配**：语义相似度回退，当强匹配无法命中时使用
- **提示词模板**：`提示词-强匹配.md` 和 `提示词(弱匹配).md` 已定义完整
- **关键发现**：Phase2 依赖外部 LLM，Agent 编排时需正确注入上下文（标准化索引 + 标准字段说明）
- **输入**：原始日志 JSON + normalize_indexes.txt + 标准字段说明.txt
- **输出**：标准字段映射结果文件

### Phase3 — 确定性正则批量字段提取
- **核心函数**：
  - `read_log_lines(path)` — 多编码读取（utf-8-sig, utf-16, gbk, cp936, utf-8），覆盖 Windows 常见编码
  - `process_log_once(log_lines, field_key, pattern)` — 单次正则扫描 + OrderedDict 去重 + 未匹配索引追踪
  - `reorder_log_lines(value_lines, unmatched_lines)` — 按字段值分组，`==========` 分隔，未匹配行归入 `未匹配` 组
  - `save_result(...)` — 输出 3 个文件：提取结果 / 映射文件 / 重排文件
- **特性**：完全确定性，正则驱动，无 LLM 依赖
- **关键发现**：OrderedDict 去重保证字段值唯一性；未匹配行处理确保无数据丢失
- **输入**：data/ 日志文件 + 字段键 + 正则模式
- **输出**：output/ 下的提取结果 + 映射文件 + 重排文件

## 2. 数据文件结构

### 标准字段.txt
- **规模**：700+ 字段定义
- **格式**：Tab 分隔，7 列
- **列定义**：系统属性名称 | 属性分类 | 字段名称 | 属性类型 | 描述 | 枚举值 | 对象
- **Agent 影响**：数据量大，需通过 `load_config` 按需加载，不宜硬编码

### 威胁类型.md
- **规模**：100+ 标准分类
- **用途**：Phase2 映射和威胁分类标准化
- **Agent 影响**：作为 `threat_classify` 工具的参考数据，应放入 `knowledge/` 目录

## 3. Agent 设计关键发现

### 工具划分原则
- **确定性代码**（Phase1/3）：直接导入现有函数，封装为工具，添加输入校验和错误处理
- **LLM 驱动阶段**（Phase2）：保留提示词模板机制，Agent 注入上下文后调用 LLM
- 此划分确保最小侵入原则——不修改现有 phase 代码

### ReAct 编排策略
- Phase1 → Phase2：Phase1 输出的 `normalize_indexes.txt` 自动作为 Phase2 的输入
- Phase2 → Phase3：Phase2 的映射结果指导 Phase3 的字段键选择
- 确定性阶段可自动串联；Phase2 需要 LLM 推理，Agent 应提供完整上下文

### 扩展性考量
- 方案A（.agent.md）可平滑升级为方案B（MCP Server）
- 5 工具各自独立，可单独测试和替换
- `load_config` 设计为通用配置加载器，未来可支持更多数据文件

## 4. 风险与注意事项

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Phase2 LLM 输出不稳定 | 映射质量波动 | 强匹配三一致规则作为硬约束 |
| 标准字段数据量大 | 加载耗时 | load_config 按需加载，支持维度检索 |
| 多编码文件读取 | Phase3 编码检测不准 | 已有 5 种编码回退策略 |
| 正则模式硬编码 | 新字段类型不匹配 | 工具支持动态传入 field_key + pattern |
