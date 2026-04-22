# auto/ 三阶段流水线整合实现方案

## 一、架构决策

### 1.1 方案选择：独立 Python 脚本（非 Agent/Skill）

**理由：**
- 流水线是**严格顺序执行**（phase1 → phase2 → phase3），无动态分支
- phase2 依赖外部 LLM API（需要用户手动调用提示词），不适合自动化编排
- 输入输出都是文件系统操作，无需 GUI 交互
- 用户已有完整的三阶段独立脚本，整合目标是**减少手动操作**，而非重构为 Agent

**最终方案：**
```
allinone/
├── docs/                    # 文档目录（本文件所在）
├── pipeline.py              # 主流水线脚本
├── config.yaml              # 配置文件（路径、LLM API 配置等）
├── phase1_processor.py      # Phase1 逻辑封装
├── phase2_llm_caller.py     # Phase2 LLM 调用封装（可选自动化）
├── phase3_extractor.py      # Phase3 逻辑封装
├── utils.py                 # 公共工具函数
└── data/                    # 统一输入目录
    └── output/              # 统一输出目录
```

---

## 二、功能模块设计

### 2.1 Phase1 处理器（`phase1_processor.py`）

**输入：**
- `data/*.txt`：原始 Base64 编码的索引数据文件

**输出：**
- `output/phase1/normalize_indexes.txt`：汇总的 normalize index 值
- `output/phase1/decoded/*.txt`：解码后的原始文件（可选保留）

**核心函数：**
```python
def process_phase1(input_dir: str, output_dir: str) -> dict:
    """
    执行 Phase1 处理
    
    返回：
    {
        "normalize_indexes_file": "path/to/normalize_indexes.txt",
        "decoded_files": ["path1", "path2", ...],
        "stats": {"total_files": 10, "success": 10, "failed": 0}
    }
    """
```

**复用逻辑：**
- 直接移植 `auto/phase1/index.py` 的核心函数：
  - `decode_base64_text()`
  - `extract_normalize_indexes()`
  - `_extract_indexes_from_obj()`
  - `_extract_original_log_result()`

---

### 2.2 Phase2 LLM 调用器（`phase2_llm_caller.py`）

**输入：**
- `output/phase1/normalize_indexes.txt`：Phase1 输出的索引文件
- `config.yaml` 中的 LLM API 配置（可选）
- 提示词模板：
  - `auto/phase2/提示词-强匹配.md`
  - `auto/phase2/标准字段.md`（弱匹配版）
  - `auto/phase2/威胁类型.md`

**输出：**
- `output/phase2/field_mapping.md`：标准字段映射表（Markdown 格式）
- `output/phase2/threat_type_mapping.md`：威胁类型映射表（Markdown 格式）

**核心函数：**
```python
def process_phase2(
    normalize_indexes_file: str,
    output_dir: str,
    llm_config: dict = None,
    auto_call: bool = False
) -> dict:
    """
    执行 Phase2 处理
    
    参数：
    - auto_call: 是否自动调用 LLM API（默认 False，需手动复制提示词）
    
    返回：
    {
        "field_mapping_file": "path/to/field_mapping.md",
        "threat_mapping_file": "path/to/threat_type_mapping.md",
        "prompt_files": {
            "field_strong": "path/to/prompt_field_strong.txt",
            "field_weak": "path/to/prompt_field_weak.txt",
            "threat": "path/to/prompt_threat.txt"
        }
    }
    """
```

**实现策略：**
1. **手动模式（默认）：**
   - 读取 `normalize_indexes.txt` 内容
   - 加载三个提示词模板
   - 将索引内容插入模板占位符
   - 输出三个完整提示词文件到 `output/phase2/prompts/`
   - 打印提示信息：
     ```
     Phase2 提示词已生成，请手动复制到 LLM 并将结果保存为：
     - output/phase2/field_mapping.md
     - output/phase2/threat_type_mapping.md
     完成后按回车继续...
     ```

2. **自动模式（可选）：**
   - 如果 `config.yaml` 配置了 LLM API（如 OpenAI/Claude API）
   - 自动调用 API 并保存结果
   - 需要处理 API 限流、重试逻辑

---

### 2.3 Phase3 提取器（`phase3_extractor.py`）

**输入：**
- `output/phase2/field_mapping.md`：字段映射表
- `data/*.txt`：原始日志文件（与 Phase1 输入相同）

**输出：**
- `output/phase3/extraction_result.json`：提取结果（字段→值列表）
- `output/phase3/mapping_table.tsv`：映射表（字段→匹配行号）
- `output/phase3/reordered_logs.txt`：按值分组重排的原始日志

**核心函数：**
```python
def process_phase3(
    field_mapping_file: str,
    log_dir: str,
    output_dir: str,
    field_key: str = None,
    regex_pattern: str = None
) -> dict:
    """
    执行 Phase3 处理
    
    参数：
    - field_key: 字段键（如 "srcIp"），为 None 时从 mapping 文件自动提取
    - regex_pattern: 正则表达式，为 None 时使用默认规则
    
    返回：
    {
        "extraction_file": "path/to/extraction_result.json",
        "mapping_file": "path/to/mapping_table.tsv",
        "reordered_file": "path/to/reordered_logs.txt",
        "stats": {"total_lines": 1000, "matched": 800, "unmatched": 200}
    }
    """
```

**复用逻辑：**
- 直接移植 `auto/phase3/field.py` 的核心函数：
  - `read_log_lines()`
  - `process_log_once()`
  - `reorder_log_lines()`
  - `save_result()`

**增强功能：**
- 自动从 `field_mapping.md` 解析字段键和正则（无需手动输入）
- 支持批量处理多个字段

---

### 2.4 主流水线（`pipeline.py`）

**核心逻辑：**
```python
def run_pipeline(config_path: str = "config.yaml"):
    """
    执行完整三阶段流水线
    
    流程：
    1. 加载配置
    2. 执行 Phase1（自动）
    3. 执行 Phase2（手动或自动）
    4. 执行 Phase3（自动）
    5. 生成执行报告
    """
    config = load_config(config_path)
    
    # Phase1
    print("=== Phase1: 索引提取 ===")
    phase1_result = process_phase1(
        input_dir=config["phase1"]["input_dir"],
        output_dir=config["phase1"]["output_dir"]
    )
    print(f"✓ Phase1 完成：{phase1_result['stats']}")
    
    # Phase2
    print("\n=== Phase2: LLM 字段映射 ===")
    phase2_result = process_phase2(
        normalize_indexes_file=phase1_result["normalize_indexes_file"],
        output_dir=config["phase2"]["output_dir"],
        llm_config=config.get("llm"),
        auto_call=config["phase2"].get("auto_call", False)
    )
    
    if not config["phase2"].get("auto_call", False):
        input("Phase2 提示词已生成，请手动完成 LLM 调用后按回车继续...")
    
    # Phase3
    print("\n=== Phase3: 字段值提取 ===")
    phase3_result = process_phase3(
        field_mapping_file=phase2_result["field_mapping_file"],
        log_dir=config["phase3"]["log_dir"],
        output_dir=config["phase3"]["output_dir"]
    )
    print(f"✓ Phase3 完成：{phase3_result['stats']}")
    
    # 生成报告
    generate_report(phase1_result, phase2_result, phase3_result)
```

---

## 三、配置文件设计（`config.yaml`）

```yaml
# 输入输出路径配置
phase1:
  input_dir: "data"                          # 原始 Base64 文件目录
  output_dir: "data/output/phase1"           # Phase1 输出目录

phase2:
  output_dir: "data/output/phase2"           # Phase2 输出目录
  auto_call: false                           # 是否自动调用 LLM API
  prompt_templates:
    field_strong: "../phase2/提示词-强匹配.md"
    field_weak: "../phase2/标准字段.md"
    threat: "../phase2/威胁类型.md"

phase3:
  log_dir: "data"                            # 原始日志目录（与 phase1 输入相同）
  output_dir: "data/output/phase3"           # Phase3 输出目录
  auto_extract_fields: true                  # 是否自动从 mapping 文件提取字段

# LLM API 配置（可选，用于 Phase2 自动调用）
llm:
  provider: "openai"                         # 或 "anthropic"
  api_key: "your-api-key-here"
  model: "gpt-4"
  max_tokens: 4096
  temperature: 0.0

# 日志配置
logging:
  level: "INFO"
  file: "data/output/pipeline.log"
```

---

## 四、实现步骤

### 阶段 1：基础框架搭建（1-2小时）
1. ✅ 创建目录结构
2. ✅ 编写 `config.yaml` 模板
3. ✅ 实现 `utils.py`（日志、文件读写、配置加载）
4. ✅ 编写 `pipeline.py` 主框架（空函数占位）

### 阶段 2：Phase1 迁移（30分钟）
1. ✅ 复制 `auto/phase1/index.py` 核心函数到 `phase1_processor.py`
2. ✅ 调整输入输出路径为配置驱动
3. ✅ 添加错误处理和日志
4. ✅ 单元测试

### 阶段 3：Phase2 封装（1小时）
1. ✅ 实现手动模式（生成提示词文件）
2. ✅ 实现自动模式（可选，调用 LLM API）
3. ✅ 添加提示词模板变量替换逻辑
4. ✅ 测试提示词生成

### 阶段 4：Phase3 迁移（1小时）
1. ✅ 复制 `auto/phase3/field.py` 核心函数到 `phase3_extractor.py`
2. ✅ 实现自动字段提取（从 `field_mapping.md` 解析）
3. ✅ 调整输出格式为统一规范
4. ✅ 单元测试

### 阶段 5：集成测试（1小时）
1. ✅ 端到端测试完整流水线
2. ✅ 验证输出文件格式
3. ✅ 性能测试（大文件处理）
4. ✅ 错误场景测试（缺失文件、格式错误等）

### 阶段 6：文档和优化（30分钟）
1. ✅ 编写 `README.md`（使用说明）
2. ✅ 添加命令行参数支持（`--config`, `--phase`, `--verbose`）
3. ✅ 代码注释完善
4. ✅ 性能优化（如有需要）

---

## 五、使用示例

### 5.1 完整流水线执行
```bash
cd D:\360\leetcode\tools\auto\allinone
python pipeline.py
```

### 5.2 单独执行某个阶段
```bash
# 只执行 Phase1
python pipeline.py --phase 1

# 只执行 Phase3（假设 Phase1/2 已完成）
python pipeline.py --phase 3
```

### 5.3 自定义配置文件
```bash
python pipeline.py --config my_config.yaml
```

---

## 六、关键技术点

### 6.1 错误处理
- 所有文件操作使用 `try-except` 包裹
- Phase2 手动模式需检测输出文件是否存在才能继续
- Phase3 需处理日志文件编码问题（UTF-8/GBK 自动检测）

### 6.2 性能优化
- Phase1/3 使用流式读取大文件（避免内存溢出）
- Phase3 使用 `OrderedDict` 去重（保持插入顺序）
- 多文件处理可考虑并行（`multiprocessing`）

### 6.3 可扩展性
- Phase2 LLM 调用支持插件化（可扩展支持更多 LLM 提供商）
- Phase3 正则规则可外部化为配置文件
- 支持自定义后处理钩子（如结果格式转换）

---

## 七、与现有代码的关系

### 7.1 保留原有脚本
- `auto/phase1/`, `auto/phase2/`, `auto/phase3/` 保持不变
- `allinone/` 作为整合版本，不影响原有独立脚本使用

### 7.2 共享资源
- 提示词模板：`allinone/` 直接引用 `auto/phase2/*.md`
- 标准字段文件：`allinone/` 直接引用 `auto/phase2/data/标准字段.txt`

### 7.3 输出隔离
- `allinone/data/output/` 独立于 `auto/phase*/output/`
- 避免相互覆盖

---

## 八、后续优化方向

1. **Web UI 界面**：使用 Flask/Streamlit 提供可视化操作界面
2. **增量处理**：支持只处理新增文件（基于文件修改时间）
3. **结果对比**：Phase3 输出支持与历史结果 diff
4. **告警通知**：处理失败时发送邮件/钉钉通知
5. **Docker 容器化**：打包为 Docker 镜像，简化部署

---

## 九、风险与依赖

### 9.1 外部依赖
- Python 3.8+
- 第三方库：`pyyaml`, `requests`（如启用 LLM 自动调用）
- LLM API（Phase2 自动模式需要）

### 9.2 潜在风险
- Phase2 手动模式依赖用户操作，可能中断流程
- 大文件处理可能内存不足（需流式处理）
- 日志文件编码不一致可能导致解析失败

### 9.3 缓解措施
- 提供详细的错误提示和日志
- 支持断点续传（保存中间状态）
- 添加文件大小和编码检测

---

## 十、验收标准

1. ✅ 能够一键执行完整三阶段流水线
2. ✅ Phase1 输出 `normalize_indexes.txt` 格式正确
3. ✅ Phase2 生成的提示词可直接复制到 LLM 使用
4. ✅ Phase3 输出三个文件（JSON/TSV/TXT）格式正确
5. ✅ 配置文件支持自定义路径和参数
6. ✅ 错误场景有清晰的提示信息
7. ✅ 代码有完整的中文注释
8. ✅ 提供使用文档（README.md）

---

**文档版本：** v1.0  
**创建时间：** 2025-01-XX  
**最后更新：** 2025-01-XX  
**作者：** Claude (Anthropic)
