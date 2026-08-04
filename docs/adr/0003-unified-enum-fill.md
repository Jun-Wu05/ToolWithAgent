# ADR-0003：统一枚举值填充（威胁/事件名称/事件级别等不再分离）

**日期**：2026-07-16
**状态**：已采纳

## 背景

系统最初将填充分为两条路径：
- 威胁类型填充（`threat_handler.py` + `apply_threat_mapping`）：mappingType=REGULAR，值来自 LLM 对应的标准威胁分类
- 枚举填充（`enum_handler.py` + `apply_enum_fill`）：mappingType=EQUAL，值来自日志提取或 Excel 映射表

两者在 apply 层面的操作完全相同：遍历 normalize 数组 → 匹配目标字段 → 追加 mappings。

## 决策

统一为**枚举值填充**（`fill_dispatcher.py` + `mapping_utils.apply_fill_to_sub_rules`）。所有标准字段枚举（威胁类型、事件名称、事件级别、操作类型等）的填充走同一代码路径。

## 理由

1. **领域本质统一**：威胁类型、事件名称、事件级别、操作类型等标准字段的填充，本质都是枚举值填充——把值映射结果写入 normalize 项的 mappings 数组。分离只是历史原因（威胁类型先实现，枚举后实现）。
2. **消除重复**：统一前有 4 处重复的去重追加逻辑（threat_fill / enum_field_tool / field_mapping × 2）。统一后集中到 `mapping_utils.append_mappings_to_normalize` 一处。
3. **可扩展**：未来新增标准字段枚举类型（如日志级别、设备类型等）无需新增 handler，只需填充时提供对应的 mappingType 和映射表。
4. **链式回写**：统一后所有填充共享 `mapped_sub_rules` 链式回写机制，支持多字段迭代（A→B→C 基于上次结果）。

## mappingType 区分

统一操作但仍保留 mappingType 区分（由映射表内容决定，不由代码路径决定）：
- **EQUAL**：精确匹配（枚举值从日志提取或用户指定）
- **REGULAR**：正则匹配（威胁类型等需要模糊匹配的场景）

## 后果

- **正面**：消除4处重复；新增枚举字段类型零成本；链式回写统一；`route_config` 填充判定简化（返回 `"fill"`，不猜类型）
- **负面**：`fill_dispatcher` 需通过 `last_fill_type` 标记 + 用户文本语义判断填充类型（而非硬编码路由）
- **迁移**：旧的按钮驱动流程（`handle_threat_fill_flow` / `handle_enum_fill_flow`）保留兼容，内部调用统一函数
