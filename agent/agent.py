"""
Agno Agent 定义

接入 SiliconFlow 的 DeepSeek-V3.2 模型
"""
import os
from pathlib import Path
from typing import Optional

from agno.agent import Agent
from agno.models.siliconflow import Siliconflow

from agent.tools.base64_tool import base64_decode_and_extract, decode_base64_text, extract_normalize_indexes, extract_original_log_result
from agent.tools.standard_mapper import standard_field_mapping, load_object_mapping, apply_field_mapping, manage_sim_entities
from agent.tools.base64_encoder import base64_encode, json_to_base64
from agent.tools.file_tool import read_file, write_file, list_files, get_project_root, get_standard_fields_path, get_config_path
from agent.tools.enum_field_tool import decode_enum_config, generate_enum_mapping_template, apply_enum_mapping, load_mapping_from_excel, get_enum_fields_list
from agent.tools.threat_type_tool import generate_threat_type_mapping_table, apply_threat_type_mapping
from agent.tools.extract_field_tool import extract_field_values, generate_mapping_table, save_mapping_to_excel
from agent.prompts import load_field_weak_prompt, load_field_strong_prompt, load_threat_type_prompt, load_enum_field_prompt


def load_standard_fields_txt() -> str:
    """加载标准字段表"""
    # 优先从 agent/data/ 加载
    data_path = Path(__file__).parent / "data" / "标准字段.txt"
    if not data_path.exists():
        # 从 auto/phase2/data/ 加载
        data_path = Path(__file__).parent.parent / "auto" / "phase2" / "data" / "标准字段.txt"
    
    if data_path.exists():
        return data_path.read_text(encoding='utf-8')
    
    return "标准字段表加载失败"


def create_agent(session_id: Optional[str] = None, user_id: Optional[str] = None) -> Agent:
    """
    创建 Agent 实例
    
    Args:
        session_id: 会话 ID
        user_id: 用户 ID
        
    Returns:
        Agent: 配置好的 Agno Agent
    """
    # 加载标准字段表（全量 654 行）
    standard_fields = load_standard_fields_txt()
    
    # 加载提示词
    field_prompt = load_field_weak_prompt()
    threat_prompt = load_threat_type_prompt()
    
    # 加载枚举字段提示词
    enum_prompt = load_enum_field_prompt()
    
    # 构建系统提示词
    system_prompt = f"""
# 安全设备配置规则字段映射智能助手

你是一个专业的网络安全日志标准化专家。

## 你的核心能力

### 功能1：标准字段映射
1. 解码 Base64 编码的数据文件
2. 从解码后的 JSON 中提取字段列表
3. 根据标准字段表生成字段映射表
4. 执行字段映射并管理 simEntities 数组
5. 将处理后的数据编码为 Base64 输出

### 功能2：威胁类型枚举处理
1. 解码威胁类型配置
2. 生成威胁类型映射表
3. 应用映射到 normalize 数组的 mappings 字段
4. 输出标准化后的威胁类型

### 功能3：普通字段枚举批量处理 ⭐（当前阶段）
1. 用户上传 Base64 编码的配置文件
2. 用户上传映射表 Excel 文件（格式：mappingType | orgValue | mappingValue | field）
3. 展示解码后的字段信息和 Excel 映射内容
4. 等待用户确认
5. 用户确认后，执行映射到 normalize 数组的 mappings 字段
6. 输出填充好的 Base64 加密 txt 文件

**注意：映射表 Excel 格式说明**
| mappingType | orgValue | mappingValue | field |
|-------------|----------|--------------|-------|
| REGULAR     | 原始值1  | 映射目标值1  | 目标字段名 |
| REGULAR     | 原始值2  | 映射目标值2  | 目标字段名 |

## 标准字段表（必须严格使用以下中文名称）
```
{standard_fields}
```

## 字段映射提示词
{field_prompt}

## 威胁类型标准化提示词
{threat_prompt}

## 普通字段枚举处理提示词
{enum_prompt}

## 重要约束
1. 只能使用标准字段表中的中文系统属性名称
2. 禁止自造字段名、禁止翻译字段名
3. 字段映射表输出格式必须严格为 Markdown 表格
4. 表格格式：| 原始字段名 | 系统属性名称 | 匹配状态/说明 |
5. 用户确认映射表后，再执行实际的映射处理

## 你的任务流程

### 标准字段映射流程
1. 接收用户上传的 Base64 编码数据
2. 使用 base64_decode_and_extract 工具解码并提取字段
3. 根据标准字段表生成字段映射表（Markdown 表格格式）
4. 展示映射表，等待用户确认或修改
5. 用户确认后，使用 standard_field_mapping 执行映射
6. 使用 base64_encode 输出最终 Base64 数据

### 普通字段枚举处理流程（当前阶段）
1. 用户说"处理枚举字段"或类似指令
2. 接收用户上传的 Base64 编码配置文件
3. 接收用户上传的映射表 Excel 文件
4. 使用 decode_enum_config 工具解码配置
5. 使用 load_mapping_from_excel 工具加载映射表
6. 展示解码后的字段信息和 Excel 映射内容摘要
7. 询问用户是否确认执行映射
8. 用户确认后，使用 apply_enum_mapping 执行映射
9. 使用 json_to_base64 输出填充好的 Base64 加密 txt

## 配置文件路径
- Excel 模板: {get_config_path("对象.xlsx")}
- 威胁类型配置: {get_config_path("threat_type_config.json")}
"""
    
    # 从环境变量读取模型配置
    model_id = os.getenv("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3.2")
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    
    # 使用 SiliconFlow 官方模型
    model = Siliconflow(
        id=model_id,
        api_key=api_key,
    )
    
    # 创建 Agent
    agent = Agent(
        model=model,
        name="数据映射解析助手",
        description="安全设备配置规则字段映射智能助手",
        instructions=system_prompt,
        user_id=user_id or "anonymous",
        session_id=session_id,
        markdown=True,
        debug_mode=False,
    )
    
    return agent


def run_agent_text(agent: Agent, user_message: str) -> str:
    """
    运行 Agent 并返回文本响应
    
    Args:
        agent: Agent 实例
        user_message: 用户消息
        
    Returns:
        str: Agent 响应文本
    """
    response = agent.run(user_message)
    return response.content


# 为了兼容 Streamlit，提供简化的调用接口
def simple_decode(b64_text: str) -> dict:
    """
    简化的解码函数，不依赖 Agent
    
    Args:
        b64_text: Base64 编码的文本
        
    Returns:
        dict: 解码结果
    """
    try:
        decoded_text = decode_base64_text(b64_text)
        fields = extract_normalize_indexes(decoded_text)
        original_log = extract_original_log_result(decoded_text)
        
        import json
        try:
            decoded_json = json.loads(decoded_text)
        except json.JSONDecodeError:
            decoded_json = {"raw_text": decoded_text[:1000]}
        
        return {
            "status": "success",
            "decoded_json": decoded_json,
            "decoded_text": decoded_text,
            "fields": fields,
            "original_log": original_log,
            "field_count": len(fields) if fields else 0
        }
    except Exception as e:
        return {
            "status": "error",
            "error_message": str(e)
        }


def simple_encode(data: dict) -> dict:
    """
    简化的编码函数，不依赖 Agent
    
    Args:
        data: 要编码的数据
        
    Returns:
        dict: 编码结果
    """
    try:
        import json
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        encoded = json_to_base64(data)
        
        return {
            "status": "success",
            "base64_encoded": encoded,
            "decoded_preview": json_str[:200],
            "original_length": len(json_str),
            "encoded_length": len(encoded)
        }
    except Exception as e:
        return {
            "status": "error",
            "error_message": str(e)
        }


if __name__ == "__main__":
    # 测试 Agent
    agent = create_agent()
    print("Agent 创建成功！")
    print(f"模型: {agent.model.id}")
