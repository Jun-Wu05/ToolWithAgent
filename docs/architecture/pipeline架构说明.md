# 日志解析 Pipeline 架构说明

> **文档版本**：2026-06-03-v4  
> **对应目录**：`agent/tools/pipeline/`  
> **调用方**：`web/chainlit_app.py`

---

## 1. Pipeline 总览

日志解析 Pipeline 采用 **3-Step 串联 + Step 2a 内嵌定位** 设计：

```
原始日志字符串 (logs_str)
  │
  ▼
┌─────────────────────────────────────────────────────┐
│ Step 1: identify_log_format                         │
│ 文件: log_format_identifier.py                      │
│ 职责: LLM 识别日志格式类型 (支持 JSON 和 KV)         │
│ 输出: format_type, format_detail, header_end_marker, │
│       feature_field, kv_connector, kv_separator      │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│ Step 2: classify_log_features                       │
│ 文件: log_classifier.py (路由)                        │
│                                                      │
│ ┌─ Step 2a: locate_feature (日志头+JSON/KV 触发) ──┐ │
│ │ 文件: log_feature_locator.py                      │ │
│ │ 职责: LLM 判断特征在 header 还是 body              │ │
│ │ 输出: feature_location, feature_field, reason      │ │
│ └───────────────────────────────────────────────────┘ │
│                                                      │
│ 路由结果:                                             │
│ - header → Path A: log_header_processor.py           │
│ - body   → Path Main/Path KV (JSON/KV)               │
│ - 纯JSON → 直接 Path Main                             │
│ - 纯KV   → 直接 Path KV                               │
│                                                      │
│ 输出: classification_details, feature_identifier, ... │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│ Step 3: fill_sample_logs                            │
│ 文件: log_sample_filler.py                          │
│ 职责: 用 feature_identifier 正则从原始日志中匹配样本       │
│ 输出: 完整的 classification JSON                      │
└─────────────────────────────────────────────────────┘
```

### 外部调用链

```
chainlit_app.py
  ├── Step 1: _do_identify_log_format(logs_str)
  ├── Step 2: _do_classify_log_features(logs_str, format_type, format_detail,
  │                                      feature_field, format_info, header_end_marker)
  │   └── 内部: locate_feature → Path A / Path Main / Path KV
  └── Step 3: fill_sample_logs(classification_str, logs_str)
```

---

## 2. 目录与文件职责

```
agent/tools/pipeline/
├── __init__.py                  (0行)  空文件
├── llm_client.py               (~110行) 共享 LLM 调用 + 格式归一化
├── log_format_identifier.py    (~120行) Step 1: 格式识别
├── log_feature_locator.py      (~90行)  Step 2a: 特征定位 (新增)
├── log_classifier.py           (~310行) Step 2: 路由 + Path Main
├── log_header_processor.py     (~230行) Step 2: Path A 日志头分类
├── log_sample_filler.py        (~200行) Step 3: 样本回填
├── models.py                    (~50行) TypedDict 类型定义
│
├── common/
│   ├── aggregator.py           (~96行)  特征值聚合引擎
│   ├── json_utils.py           (~94行)  JSON 提取工具函数
│   ├── knowledge_store.py      (~80行)  向量知识库存储
│   └── llm_postprocessor.py   (~244行) LLM 响应后处理
│
└── extractors/
    ├── __init__.py              (~15行) 包级 re-export
    ├── base.py                  (~60行) 抽象基类 ValueExtractor
    ├── json_extractor.py        (~40行) JSON 提取器（当前使用）
    ├── header_extractor.py     (~130行) 日志头提取器（✅ Path A 已集成）
    └── kv_extractor.py          (~40行) KV 提取器（预留扩展）
```

### 文件引用关系图

```
chainlit_app.py
  │
  ├── log_format_identifier.py ──→ llm_client.py
  │
  ├── log_classifier.py ─────────→ llm_client.py
  │   │                           → log_feature_locator.py (Step 2a) ← 新增
  │   │                              → extractors/header_extractor.py (aggregate_headers)
  │   │                              → extractors/json_extractor.py (JsonExtractor)
  │   │                              → llm_client.py
  │   │                           → extractors/json_extractor.py (JsonExtractor)
  │   │                           → common/llm_postprocessor.py
  │   │                           → common/knowledge_store.py
  │   │                           → log_header_processor.py (Path A)
  │   │                              → extractors/header_extractor.py (aggregate_headers)
  │   │
  └── log_sample_filler.py ──────→ models.py
```

---

## 3. 路由分支逻辑（CHANGED 2026-06-03）

Step 2 的 `_do_classify_log_features()` 根据 `format_type` 和 `format_detail` 判断路由：

```
_do_classify_log_features(format_type, format_detail, ...)
  │
  ├── [format != json && format != kv]
  │   → UNSUPPORTED
  │
  ├── [format == kv && "日志头" in format_detail]  ← 日志头+KV
  │   → Step 2a: locate_feature()
  │     ├── feature_location=header → Path A (日志头分类)
  │     ├── feature_location=body   → Path KV (KV body 分类)
  │     └── feature_location=unknown → FAILED
  │
  ├── [format == kv]  ← 纯 KV
  │   → 直接 Path KV
  │
  ├── ["日志头" in format_detail]  ← 日志头+JSON
  │   → Step 2a: locate_feature()
  │     ├── feature_location=header → Path A
  │     ├── feature_location=body   → Path Main (可能修正 feature_field)
  │     └── feature_location=unknown → FAILED
  │
  └── [纯 JSON]
      → 直接 Path Main
```

### KV 格式支持（2026-06-03 新增）

**支持的 KV 格式**：
- 纯 KV：`key=value key2=value2`（空格分隔）
- 日志头+KV：`<priority>timestamp host app: key=value ...`

**KV 分隔符透传**：
Step 1 返回的 `kv_connector` 和 `kv_separator` 自动映射为 `tab` 和 `delimit`，透传给 KvExtractor：
- `kv_connector="="` → `tab="="`（键值分隔符）
- `kv_separator="space"` → `delimit=" "`（字段分隔符）→ 正则 `\s+`

**语义说明**（2026-06-05 统一）：
- `delimit`：字段分隔符，即键值对之间的分隔符（如 `space`、`||`、`\t`）
- `tab`：键值分隔符，即键和值之间的连接符（如 `=`、`:`）

**KV Path 分支**：
- Path KV：`_classify_kv_features()` 使用 KvExtractor 提取特征值
- 支持的 KV 分隔符变体：
  - `key=value` 空格分隔
  - `key:value` 空格分隔
  - `key:value` 管道分隔 (`||`)

### Step 2a: 特征定位

**触发条件**：`format_detail` 包含"日志头"（即 `has_header=true`），适用于日志头+JSON 和日志头+KV 格式。

**输入**：
- header 聚合统计（`HeaderExtractor.aggregate_headers()`）
- body 字段候选（`JsonExtractor` / `KvExtractor` 分析 `feature_field`）
- 采样日志 5 行

**LLM 判断依据**：
- body 和 header 都有有效分类特征 → 选择语义更匹配"日志类型"的
- 仅 body 有 → body
- 仅 header 有 → header
- 都没有 → unknown

**输出**：
```json
{"feature_location": "body|header|unknown", "feature_field": "...", "reason": "判断依据"}
```

---

## 4. 数据流详解

### 4.1 Step 1 输出 → Step 2 输入

Step 1 返回 JSON 字符串，关键字段：

```json
{
  "format": "JSON",
  "format_detail": "日志头+JSON",
  "has_header": true,
  "feature_field": "categoryName",
  "header_end_marker": " - - - - "
}
```

| 字段 | 类型 | 说明 | 用于 |
|------|------|------|------|
| `format` | str | `JSON` / `CSV` / `unknown` | Step 2 路由 |
| `format_detail` | str | `纯JSON` / `日志头+JSON` | Step 2 路由（判断是否触发 Step 2a） |
| `has_header` | bool | 是否有 syslog 头 | header_end_marker 是否有效 |
| `feature_field` | str | 分类字段名 (如 `categoryName`) | Step 2a / Path Main 提取 |
| `header_end_marker` | str | 头部与 body 分隔符 | real_samples 去头 |

### 4.2 Step 2 输出 → Step 3 输入

Step 2 返回 JSON 字符串（结构不变）：

```json
{
  "status": "SUCCESS",
  "log_format": "JSON",
  "log_format_detail": "日志头+JSON",
  "feature_field": "categoryName",
  "feature_identifier": "(\\{[\\S\\s]*\\})",
  "feature_count": 4,
  "total_valid_lines": 208,
  "covered_lines": 208,
  "classification_details": [...]
}
```

---

## 5. 函数索引

### 5.0 Step 2a: 特征定位（新增）

| 函数 | 文件 | 说明 |
|------|------|------|
| `locate_feature(logs_str, feature_field, format_detail)` | `log_feature_locator.py` | LLM 判断特征在 header 还是 body |
| `_prepare_header_analysis(logs_str)` | `log_feature_locator.py` | 用 HeaderExtractor 聚合日志头模式 |
| `_prepare_body_analysis(logs_str, feature_field)` | `log_feature_locator.py` | 用 JsonExtractor 分析 body 字段候选 |

### 5.1 Step 1: 格式识别

| 函数 | 文件 | 说明 |
|------|------|------|
| `_do_identify_log_format(logs_str)` | `log_format_identifier.py` | 纯函数版，chainlit_app 直接调用 |
| `identify_log_format(logs_str)` | `log_format_identifier.py` | @tool 装饰版，Agent 模式使用 |

### 5.2 Step 2: 特征分类

| 函数 | 文件 | 说明 |
|------|------|------|
| `_do_classify_log_features(...)` | `log_classifier.py` | 路由入口（含 Step 2a 调用） |
| `_classify_json_features(...)` | `log_classifier.py` | Path Main 核心（JSON 格式） |
| `_classify_kv_features(...)` | `log_classifier.py` | Path KV 核心（KV 格式，2026-06-03 新增） |
| `_build_feature_identifier(fmt, detail)` | `log_classifier.py` | JSON→`(\{[\S\s]*\})`，KV→`""` |
| `classify_header_features(...)` | `log_header_processor.py` | Path A: 日志头分类 |

### 5.3 Step 3: 样本回填

| 函数 | 文件 | 说明 |
|------|------|------|
| `fill_sample_logs(classification, logs_str)` | `log_sample_filler.py` | 用 feature_identifier 正则匹配样本 |

### 5.4 公共模块

| 函数 | 文件 | 说明 |
|------|------|------|
| `aggregate_by_field(lines, extractor, field)` | `common/aggregator.py` | 通用聚合引擎 |
| `aggregate_headers(logs_str)` | `extractors/header_extractor.py` | 日志头聚合（Path A 使用） |
| `postprocess_llm_classification(...)` | `common/llm_postprocessor.py` | 后处理管线 |
| `match_real_samples(parsed, logs_str, ...)` | `common/llm_postprocessor.py` | 用 extractor 匹配真实样本行 |
| `_call_llm_direct(prompt, **kwargs)` | `llm_client.py` | 统一 LLM API 调用 |
| `_try_parse_json(text)` | `llm_client.py` | 从 LLM 响应提取 JSON |

### 5.5 Extractor 策略类

| 类 | 文件 | 说明 | 状态 |
|------|------|------|------|
| `ValueExtractor` | `extractors/base.py` | 抽象基类 | ✅ 使用中 |
| `JsonExtractor` | `extractors/json_extractor.py` | JSON body 特征提取 | ✅ 使用中 |
| `HeaderExtractor` | `extractors/header_extractor.py` | 日志头特征提取 | ✅ Path A 已集成 |
| `KvExtractor` | `extractors/kv_extractor.py` | KV 格式特征提取（支持非 ASCII key） | ✅ Path KV 已集成（2026-06-03） |

---

## 6. Prompt 文件

| 文件 | 用途 |
|------|------|
| `agent/prompts/log_format_identify.md` | Step 1 格式识别 prompt |
| `agent/prompts/log_feature_locate.md` | Step 2a 特征定位 prompt（新增） |
| `agent/prompts/log_classify_feature.md` | Step 2 Path Main 分类 prompt |
| `agent/prompts/log_header_classify.md` | Step 2 Path A 头部分类 prompt |

---

## 7. 常见问题

### Q: Step 2a 什么时候触发？
**A**: 仅当 `format_detail` 包含"日志头"时触发。纯 JSON/纯 KV 直接走 Path Main/Path KV，不触发 Step 2a。

### Q: Step 2a 失败了怎么办？
**A**: 异常时降级为 `feature_location=body`，JSON 格式走 Path Main，KV 格式走 Path KV，保证不阻塞流程。

### Q: real_samples 为什么没去头？
**A**: 
- JSON 格式：使用 `header_end_marker` 字符串分割
- KV 格式（2026-06-05 修复）：使用 `feature_identifier` 正则提取 body（优先），降级使用 `header_end_marker`
- Path A 中已修复（2026-05-29），现通过参数传递

### Q: chainlit_app.py 中的路由为什么简化了？
**A**: 路由逻辑已内置到 `_do_classify_log_features()` 中（含 Step 2a），chainlit_app 只需统一调用即可。

### Q: LLM 输出 JSON 解析失败怎么办？
**A**: 已实施双重保障机制（2026-06-05）：
1. **Prompt 约束**：在所有 prompt 中添加 JSON Schema 定义，要求 LLM 输出规范 JSON
2. **API 约束**：DeepSeek/硅基流动 API 使用 `response_format={"type": "json_object"}` 强制 JSON 输出
3. **解析容错**：`_try_parse_json` 仅去除 markdown 围栏，不再尝试修复不完整 JSON
4. **不支持的 API**：智谱 GLM 等不支持 `response_format` 的 API，依赖 Prompt 约束

### Q: feature_identifier 在不同 Path 中的值？
**A**: 
- Path Main/Path KV（纯格式）：由 `_build_feature_identifier()` 生成，JSON 返回 `(\{[\S\s]*\})`，KV 返回 `""`
- Path A（日志头+JSON）：由 `_get_feature_identifier()` 或 `_generate_kv_feature_identifier()` 生成，包含日志头到 body 的正则

### Q: Diversion_method 的含义是什么？
**A**: 分类依据字段的中文业务名称（如 `"告警类型"`、`"事件类型"`），用于 `rule_generator.py` 中子规则命名（`{logtype}_{Diversion_method}_子规则`）。Path Main、Path KV 和 Path A 均由 LLM 自行填写；Path A fallback 默认值为 `"日志头特征分类"`。

### Q: KV 格式支持哪些分隔符？
**A**: 
- `kv_connector`（键值分隔符）：`=`、`:` 等
- `kv_separator`（键值对分隔符）：`space`（空格）、`||`（管道）、`;`（分号）等
Step 1 返回后自动透传给 KvExtractor，动态构建正则模式。
