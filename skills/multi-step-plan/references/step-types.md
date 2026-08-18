# 步骤类型参考

每种步骤类型对应的操作、数据依赖、**params 参数定义**和系统执行方式。RouterAgent 在分解复合意图时参考此文档选择正确的步骤类型并提取参数。

> **ADR-0004 步骤指令自包含原则**：RouterAgent 必须在 params 中提取并携带执行所需的参数，执行器（handler）不从用户原文猜测。

## 通用字段

每个步骤是一个 JSON 对象，支持以下字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `type` | 是 | 步骤类型（log_parser/mapping/enum/threat/fill） |
| `params` | 否 | 用户语义参数（字段名等），由 RouterAgent 从上下文提取 |
| `data_deps` | 否 | 数据依赖声明（引用前序步骤的 type），表示本步需要该步骤的产出 |

## log_parser — 日志类型识别
- **操作**：识别日志格式（KV/JSON/syslog），提取分类字段和日志类型
- **params**：无
- **数据依赖**：需要原始日志数据（session 的 raw_log_lines，系统自动读取）
- **结果存储**：`log_classification`（含日志格式、分类字段、各类型样本）
- **后续可接**：mapping / enum / threat

## mapping — 标准字段映射
- **操作**：将日志字段映射到标准字段库（语义检索 + LLM 匹配）
- **params**：通常无（字段列表由系统从日志解析结果提取）
- **数据依赖**：需要日志解析结果（`log_classification`）提取真实字段
- **结果存储**：`mapped_sub_rules`（映射后的子规则）、`last_mapping_data`
- **后续可接**：enum / threat / fill

## enum — 枚举值提取
- **操作**：从日志中提取指定字段的枚举值（LLM 生成正则 + 全量扫描）
- **params**：

  | 参数 | 说明 | 提取来源 |
  |------|------|---------|
  | `field` | 要提取枚举值的字段名（如"漏洞名称"） | 用户原文 + 字段列表 |

- **数据依赖**：需要原始日志数据（系统自动读取 raw_log_lines）
- **结果存储**：`last_enum_extract_result`（含 field、regex、value 列表、unique_count）
- **后续可接**：threat（用枚举值作为威胁映射输入）/ fill

## threat — 威胁类型映射
- **操作**：将告警内容映射到标准威胁分类（参考威胁类型列表）
- **params**：通常无
- **数据依赖**：
  - 声明 `"data_deps":["enum"]` → 自动读取 `last_enum_extract_result.value` 作为待映射数据
  - 无 data_deps → 用户直接输入告警文本
- **结果存储**：`last_threat_data`（映射结果列表）、`threat_mapping_table`、`last_fill_type="threat"`
- **后续可接**：fill（将威胁映射结果填充到子规则）

## fill — 填充到子规则
- **操作**：将映射结果（威胁/枚举）填充到解析规则的子规则中
- **params**：

  | 参数 | 说明 | 提取来源 |
  |------|------|---------|
  | `field` | 回填目标字段名（如"漏洞名称"、"alarm_category"） | 对话上下文 + 字段列表 + mapped_sub_rules |
  | `source` | 数据来源类型：`"threat"` 或 `"enum"` | 步骤序列推断（前序步骤类型） |

- **数据依赖**：
  - 声明 `"data_deps":["threat"]` → 读取 `last_threat_data`
  - 声明 `"data_deps":["enum"]` → 读取枚举映射表
- **结果存储**：更新 `mapped_sub_rules`（链式回写）
- **后续可接**：通常是最后一步（导出结果）

## 常见复合流程

| 用户场景 | 步骤序列（含 params/data_deps） |
|---------|-------------------------------|
| 提取枚举值做威胁映射 | `enum(field=X)` → `threat(data_deps=[enum])` |
| 枚举值威胁映射后填充 | `enum(field=X)` → `threat(data_deps=[enum])` → `fill(field=X, source=threat, data_deps=[threat])` |
| 字段映射后提取枚举 | `mapping` → `enum(field=Y, data_deps=[mapping])` |
| 完整流程 | `mapping` → `enum(field=X, data_deps=[mapping])` → `threat(data_deps=[enum])` → `fill(field=X, source=threat, data_deps=[threat])` |

## 参数提取示例

用户输入："把漏洞名称的枚举值提取出来后，进行威胁类型映射填回去"

RouterAgent 的 Synthesis 过程：
1. "漏洞名称" → enum 步骤的 `params.field`
2. "填回去" → 结合字段列表，回填目标也是"漏洞名称"对应的 normalize 项 → fill 步骤的 `params.field`
3. 威胁映射在前、填充在后 → fill 的 `params.source = "threat"`，`data_deps = ["threat"]`

输出：
```json
{"steps":[
  {"type":"enum","params":{"field":"漏洞名称"}},
  {"type":"threat","data_deps":["enum"]},
  {"type":"fill","params":{"field":"漏洞名称","source":"threat"},"data_deps":["threat"]}
]}
```
