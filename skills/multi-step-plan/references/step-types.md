# 步骤类型参考

每种步骤类型对应的操作、数据依赖和系统执行方式。RouterAgent 在分解复合意图时参考此文档选择正确的步骤类型。

## log_parser — 日志类型识别
- **操作**：识别日志格式（KV/JSON/syslog），提取分类字段和日志类型
- **数据依赖**：需要原始日志数据（已上传文件的"原始日志"列）
- **结果存储**：`log_classification`（含日志格式、分类字段、各类型样本）
- **后续可接**：mapping / enum / threat

## mapping — 标准字段映射
- **操作**：将日志字段映射到标准字段库（语义检索 + LLM 匹配）
- **数据依赖**：需要日志解析结果（`log_classification`）提取真实字段
- **结果存储**：`mapped_sub_rules`（映射后的子规则）、`last_mapping_data`
- **后续可接**：enum / threat / fill

## enum — 枚举值提取
- **操作**：从日志中提取指定字段的枚举值（LLM 生成正则 + 全量扫描）
- **数据依赖**：需要原始日志数据 + 用户指定字段名
- **结果存储**：`last_enum_extract_result`（含 field、value 列表、unique_count）
- **后续可接**：threat（用枚举值作为威胁映射输入）/ fill

## threat — 威胁类型映射
- **操作**：将告警内容映射到标准威胁分类（参考威胁类型列表）
- **数据依赖**：
  - 直接模式：用户输入告警文本
  - 枚举模式：自动读取 `last_enum_extract_result.value` 作为待映射数据
- **结果存储**：`last_threat_data`（映射结果列表）、`threat_mapping_table`、`last_fill_type="threat"`
- **后续可接**：fill（将威胁映射结果填充到子规则）

## fill — 填充到子规则
- **操作**：将映射结果（威胁/枚举）填充到解析规则的子规则中
- **数据依赖**：
  - 威胁填充：需要 `last_threat_data`（由 threat 步骤产生）
  - 枚举填充：需要 `enum_excel_path`（用户上传的映射表）
  - 需要 `mapped_sub_rules`（由 mapping 步骤或按钮产生）
- **结果存储**：更新 `mapped_sub_rules`（链式回写）
- **后续可接**：通常是最后一步（导出结果）

## 常见复合流程

| 用户场景 | 步骤序列 |
|---------|---------|
| 提取枚举值做威胁映射 | `enum` → `threat` |
| 枚举值威胁映射后填充 | `threat` → `fill`（枚举值已在上一步提取） |
| 字段映射后提取枚举 | `mapping` → `enum` |
| 完整流程：映射→提取枚举→威胁映射→填充 | `mapping` → `enum` → `threat` → `fill` |
