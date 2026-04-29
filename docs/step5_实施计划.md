# Step 5: 拆解 Chainlit 巨石应用 — 实施计划

## 目标

将 `web/chainlit_app.py`（当前约 1600 行）按职责拆分为 7 个模块，主文件压缩至 ~300 行。

## 当前文件结构分析

chainlit_app.py 包含以下内容：

| 区域 | 行数（估） | 职责 |
|------|----------|------|
| 导入 & 路径初始化 | ~1-50 | 项目路径、dotenv、logger |
| 路由关键词常量 | ~51-130 | MAPPING_KEYWORDS 等 + `_load_route_keywords()` |
| Chainlit 事件处理 | ~131-250 | `start()`, `main()` |
| 文件上传处理 | ~251-420 | `handle_file_upload()` |
| 威胁填充 | ~421-610 | `execute_threat_fill()`, `_handle_threat_fill_flow()` |
| 枚举填充 | ~611-850 | `execute_enum_fill()`, `_handle_enum_fill_flow()`, `execute_enum_fill_with_base64()` |
| Action 回调 | ~851-1010 | `on_fill_threat_with_field()`, `on_confirm_fill()`, `on_start_enum_fill()` |
| 用户消息处理 | ~1011-1090 | `handle_user_message()` 及子函数 |
| LLM 调用层 | ~1091-1390 | `_call_team_with_retry()`, `_log_token_usage()`, `_probe_nested()`, `_setup_agno_logging_bridge()`, `_build_llm_input()` |
| 响应处理 | ~1391-1610 | `_process_team_response()`, `send_action_buttons()`, `_route_request()` |

## 拆分方案

```
web/
├── chainlit_app.py          # 主入口 (~300行) — Chainlit 事件 + 编排
├── route_config.py          # 路由关键词配置 (~50行)
├── llm_client.py            # LLM 调用与 Token 统计 (~250行)
├── input_builder.py         # LLM 输入构建 (~50行)
├── response_handler.py      # 响应解析与表格展示 (~150行)
├── threat_handler.py        # 威胁类型处理 (~250行)
└── enum_handler.py          # 枚举处理 (~400行)
```

### 各模块职责与依赖

#### 1. `web/route_config.py`
- `_load_route_keywords()` → `(mapping_kw, threat_kw, enum_kw, enum_extract_kw)`
- 模块级常量: `MAPPING_KEYWORDS`, `THREAT_KEYWORDS`, `ENUM_KEYWORDS`, `ENUM_EXTRACT_KEYWORDS`
- **依赖**: `os`, `json`, `logger`

#### 2. `web/llm_client.py`
- `_call_team_with_retry(team, full_input, loading_msg) → result`
- `_log_token_usage(result)`
- `_probe_nested(label, obj, model_name, emit_fn)`
- `_setup_agno_logging_bridge() → handler`
- 模块级状态: `_agno_bridge_installed`
- 便捷封装: `async call_team(team, full_input, loading_msg) → result`
- **依赖**: `asyncio`, `time`, `logging`, `re`, `logger`, `ModelConfig` (from `agent.core.model_config`)

#### 3. `web/input_builder.py`
- `build_llm_input(user_text, user_session) → str`
- **依赖**: `json`, `logger`

#### 4. `web/response_handler.py`
- `process_team_response(result, user_lower, user_session, loading_msg, msg) → bool`
- `send_action_buttons(msg, mapping_data)`
- **依赖**: `chainlit as cl`, `web.parsers`, `json`, `io`, `datetime`, `pandas`, `logger`

#### 5. `web/threat_handler.py`
- `execute_threat_fill(user_session, file_content)`
- `handle_threat_fill_flow(user_session, user_text) → bool`
- `on_fill_threat_with_field(action)`
- **依赖**: `chainlit as cl`, `json`, `src.threat_fill_handler`, `agent.core.agent`, `logger`

#### 6. `web/enum_handler.py`
- `execute_enum_fill(user_session, file_content)`
- `handle_enum_fill_flow(user_session, user_text) → bool`
- `on_start_enum_fill(action)`
- `handle_enum_extract_flow(user_session, team, user_text)`
- `ENUM_EXTRACT_PROMPT` (模块级常量)
- **依赖**: `chainlit as cl`, `json`, `re`, `os`, `agent.tools.enum_field_tool`, `agent.tools.enum_extract_tool`, `agent.core.agent`, `logger`

#### 7. `web/chainlit_app.py` — 主入口
保留:
- `start()`, `main()`, `handle_file_upload()`, `handle_user_message()`, `on_confirm_fill()`
- 路径初始化和 dotenv 加载
- 从各子模块导入所需函数

## 实施步骤

1. **创建 `web/route_config.py`** — 迁出路由关键词加载
2. **创建 `web/llm_client.py`** — 迁出 LLM 调用与 Token 统计
3. **创建 `web/input_builder.py`** — 迁出 LLM 输入构建
4. **创建 `web/response_handler.py`** — 迁出响应解析
5. **创建 `web/threat_handler.py`** — 迁出威胁处理
6. **创建 `web/enum_handler.py`** — 迁出枚举处理
7. **重构 `web/chainlit_app.py`** — 替换为 import + 薄编排层
8. **语法检查 & 功能验证**

## 关键约定

- 所有子模块不导入 `chainlit_app.py`（避免循环引用）
- 公共 API 使用不带下划线前缀的函数名
- 每个模块有独立的 `logger` 实例
- 函数签名保持兼容（`user_session: dict` 参数不变）