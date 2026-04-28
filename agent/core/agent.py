"""
Agent主入口

基于Agno的智能Agent实现
整合会话管理、历史记录、多模型策略、业务工具
"""

import os
import base64
import json
import re
from typing import Optional, Any, List
import logging

from agno.agent import Agent
from agno.models.siliconflow import Siliconflow

from agent.core.model_config import ModelConfig
from agent.core.prompts import load_system_prompt

# 初始化日志
logger = logging.getLogger("agent")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ============= 简化的编解码函数（不依赖Agent） =============

def _decode_base64_text(text: str) -> str:
    """解码单个 Base64 文本内容"""
    cleaned = "".join(text.split())
    if not cleaned:
        return ""
    
    # 验证是否为有效的 Base64 字符
    import re
    if not re.match(r'^[A-Za-z0-9+/=\s]+$', cleaned):
        raise ValueError("输入包含非Base64字符，可能是原始文本而非Base64编码")
    
    missing_padding = len(cleaned) % 4
    if missing_padding:
        cleaned += "=" * (4 - missing_padding)
    
    # 使用 ascii 编码确保兼容性
    decoded_bytes = base64.b64decode(cleaned.encode('ascii'))
    return decoded_bytes.decode("utf-8", errors="replace")


def _extract_normalize_indexes(text: str) -> list:
    """从解码后的文本中提取 normalize 下所有的 index 值"""
    indexes: list = []
    
    try:
        payload = json.loads(text)
        indexes.extend(_extract_indexes_from_obj(payload))
        return indexes
    except Exception:
        pass
    
    pattern = re.compile(r'"normalize"\s*:\s*\[(.*?)\]', re.S)
    match = pattern.search(text)
    if not match:
        return indexes
    
    block = match.group(1)
    for item in re.finditer(r'"index"\s*:\s*(\[[^\]]*\]|\d+|".*?"|null|true|false)', block, re.S):
        value = item.group(1).strip()
        try:
            indexes.append(json.loads(value))
        except Exception:
            indexes.append(value)
    
    return indexes


def _extract_indexes_from_obj(obj: Any) -> list:
    """递归提取对象中的 index 字段"""
    indexes: list = []
    
    if isinstance(obj, dict):
        if "normalize" in obj and isinstance(obj["normalize"], list):
            for item in obj["normalize"]:
                if isinstance(item, dict) and "index" in item:
                    indexes.append(item["index"])
        for value in obj.values():
            indexes.extend(_extract_indexes_from_obj(value))
    elif isinstance(obj, list):
        for item in obj:
            indexes.extend(_extract_indexes_from_obj(item))
    
    return indexes


def _extract_original_log_result(text: str) -> Any:
    """找到整个对象中 index == "original_log" 的项，直接返回它的 result 数组"""
    try:
        payload = json.loads(text)
        return _find_original_log_result(payload)
    except Exception:
        return None


def _find_original_log_result(obj: Any) -> Any:
    """递归查找 index: "original_log" 并返回对应的 result"""
    if isinstance(obj, dict):
        if obj.get("index") == "original_log" and "result" in obj:
            return obj["result"]
        
        for value in obj.values():
            res = _find_original_log_result(value)
            if res is not None:
                return res

    elif isinstance(obj, list):
        for item in obj:
            res = _find_original_log_result(item)
            if res is not None:
                return res
    return None


def simple_decode(b64_text: str) -> dict:
    """
    简化的解码函数，不依赖 Agent
    
    功能：
    1. Base64解码
    2. 提取normalize indexes字段
    3. 提取original_log result
    
    Args:
        b64_text: Base64 编码的文本
    
    Returns:
        dict: {
            "status": "success" | "error",
            "decoded_json": dict,
            "decoded_text": str,
            "fields": list,
            "original_log": list,
            "field_count": int
        }
    """
    try:
        decoded_text = _decode_base64_text(b64_text)
        fields = _extract_normalize_indexes(decoded_text)
        original_log = _extract_original_log_result(decoded_text)
        
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
        data: JSON对象
    
    Returns:
        dict: 编码结果
    """
    try:
        json_text = json.dumps(data, ensure_ascii=False)
        encoded = base64.b64encode(json_text.encode('utf-8')).decode('utf-8')
        
        return {
            "status": "success",
            "encoded": encoded
        }
    except Exception as e:
        return {
            "status": "error",
            "error_message": str(e)
        }

# 导入业务工具
from agent.tools.base64_tool import base64_decode_tool, base64_encode_tool
from agent.tools.standard_mapper import field_mapping_tool, generate_mapping_table_tool
from agent.tools.threat_type_tool import threat_type_tool, apply_threat_mapping_tool
from agent.tools.enum_field_tool import enum_field_tool, apply_enum_mapping_tool
from agent.tools.confirmation_tool import (
    confirm_mapping_table,
    confirm_threat_mapping,
    confirm_output,
    request_modification
)


def create_agent(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    enable_memory: bool = False,
    debug_mode: bool = False,
    use_session_db: bool = False  # 新增参数：是否使用SqliteDb会话管理
) -> Agent:
    """
    创建主Agent实例
    
    这是项目的核心Agent，具备以下能力：
    - 意图理解
    - 任务规划
    - 工具调用
    - 状态管理
    - 业务工具整合
    
    Args:
        user_id: 用户ID，用于区分不同用户
        session_id: 会话ID，不提供则自动创建
        enable_memory: 是否启用记忆系统（后续功能）
        debug_mode: 是否启用调试模式
        use_session_db: 是否使用SqliteDb持久化（Web应用建议关闭）
    
    Returns:
        Agent实例
    """
    logger.info("创建Agent实例...")
    
    # 获取API Key
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    if not api_key:
        raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")
    logger.info(f"API Key已加载: {api_key[:10]}...")
    
    # 加载系统提示词
    instructions = load_system_prompt()
    logger.info("系统提示词已加载")
    
    # Agent基础配置
    agent_config = {
        # 模型配置
        "model": Siliconflow(
            id=ModelConfig.MAIN_MODEL,
            api_key=api_key
        ),
        
        # 基本信息
        "name": "数据映射助手",
        "description": "安全设备配置规则字段映射智能助手",
        
        # 指令
        "instructions": instructions,
        
        # 输出格式
        "markdown": True,
        "debug_mode": debug_mode,
        
        # 业务工具 ⭐
        "tools": [
            # Base64工具
            base64_decode_tool,
            base64_encode_tool,
            
            # 字段映射工具
            field_mapping_tool,
            generate_mapping_table_tool,
            
            # 威胁类型工具
            threat_type_tool,
            apply_threat_mapping_tool,
            
            # 枚举字段工具
            enum_field_tool,
            apply_enum_mapping_tool,
            
            # HITL确认工具 ⭐
            confirm_mapping_table,
            confirm_threat_mapping,
            confirm_output,
            request_modification,
        ],
    }
    
    # 可选：会话持久化（Web应用建议关闭，避免数据库锁）
    if use_session_db:
        from agno.db.sqlite import SqliteDb
        db_path = os.path.join(os.getcwd(), "tmp", "agents.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        agent_config["db"] = SqliteDb(db_file=db_path)
        agent_config["user_id"] = user_id
        agent_config["session_id"] = session_id
        agent_config["add_history_to_context"] = True
        agent_config["num_history_runs"] = 5
        logger.info(f"启用SqliteDb会话管理: {db_path}")
    else:
        logger.info("不使用SqliteDb会话管理（推荐用于Web应用）")
    
    # 创建Agent
    agent = Agent(**agent_config)
    logger.info(f"Agent创建成功: {agent.name}")
    
    return agent


def create_simple_agent(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    use_session_db: bool = False
) -> Agent:
    """
    创建简单任务Agent
    
    用于处理简单的数据转换任务：
    - Base64解码
    - 字段提取
    - 简单编码
    
    Args:
        user_id: 用户ID
        session_id: 会话ID
        use_session_db: 是否使用SqliteDb
    
    Returns:
        简单任务Agent实例
    """
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    if not api_key:
        raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")
    
    agent_config = {
        "model": Siliconflow(
            id=ModelConfig.SIMPLE_MODEL,
            api_key=api_key
        ),
        "name": "SimpleAgent",
        "description": "处理简单的数据转换任务",
        "instructions": """
你是一个简单任务助手，负责：
1. Base64解码 - 将Base64字符串解码为原始数据
2. 字段提取 - 从数据中提取字段
3. 简单编码 - 将数据编码为Base64

保持简单直接，执行任务后返回结果。
""",
        "markdown": True,
        "debug_mode": False,
    }
    
    # 可选会话管理
    if use_session_db:
        from agno.db.sqlite import SqliteDb
        db_path = os.path.join(os.getcwd(), "tmp", "agents.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        agent_config["db"] = SqliteDb(db_file=db_path)
        agent_config["user_id"] = user_id
        agent_config["session_id"] = session_id
        agent_config["add_history_to_context"] = True
        agent_config["num_history_runs"] = 3
    
    return Agent(**agent_config)


def create_complex_agent(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    use_session_db: bool = False
) -> Agent:
    """
    创建复杂推理Agent
    
    用于处理需要推理的复杂任务：
    - 字段映射
    - 威胁类型标准化
    - 枚举处理
    
    Args:
        user_id: 用户ID
        session_id: 会话ID
        use_session_db: 是否使用SqliteDb
    
    Returns:
        复杂推理Agent实例
    """
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    if not api_key:
        raise ValueError("请设置环境变量 SILICONFLOW_API_KEY")
    
    agent_config = {
        "model": Siliconflow(
            id=ModelConfig.COMPLEX_MODEL,
            api_key=api_key
        ),
        "name": "ComplexAgent",
        "description": "处理需要推理的复杂任务",
        "instructions": """
你是一个复杂推理助手，负责：

## 1. 字段映射
- 根据标准字段表，生成字段映射表
- 支持弱匹配（模糊匹配）和强匹配（精确匹配）
- 输出格式：[{原始字段: xxx, 标准字段: xxx, 匹配度: 高/中/低}]

## 2. 威胁类型标准化
- 将原始威胁类型映射到标准值
- 使用威胁类型枚举
- 处理特殊情况

## 3. 枚举处理
- 处理mappingType字段
- 原始值到映射值的转换

## 标准字段表
使用标准字段表中的中文名称作为标准字段。

## 约束
1. 只使用标准字段，禁止自造字段名
2. 清晰展示映射过程和结果
3. 关键决策交给用户确认
""",
        "markdown": True,
        "debug_mode": False,
    }
    
    # 可选会话管理
    if use_session_db:
        from agno.db.sqlite import SqliteDb
        db_path = os.path.join(os.getcwd(), "tmp", "agents.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        agent_config["db"] = SqliteDb(db_file=db_path)
        agent_config["user_id"] = user_id
        agent_config["session_id"] = session_id
        agent_config["add_history_to_context"] = True
        agent_config["num_history_runs"] = 5
    
    return Agent(**agent_config)


def route_task(task: str) -> str:
    """
    任务路由 - 根据任务类型选择合适的Agent
    
    Args:
        task: 任务描述
    
    Returns:
        Agent类型：'simple', 'complex', 'main'
    """
    task_lower = task.lower()
    
    # 简单任务
    if any(keyword in task_lower for keyword in ['解码', '编码', 'base64', 'decode', 'encode']):
        if '映射' not in task_lower and '威胁' not in task_lower:
            return 'simple'
    
    # 复杂任务
    if any(keyword in task_lower for keyword in ['映射', '威胁', '标准化', '枚举']):
        return 'complex'
    
    # 默认主Agent
    return 'main'


def create_routed_agent(
    task: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> Agent:
    """
    根据任务类型创建合适的Agent
    
    Args:
        task: 任务描述
        user_id: 用户ID
        session_id: 会话ID
    
    Returns:
        适合处理该任务的Agent
    """
    agent_type = route_task(task)
    
    if agent_type == 'simple':
        return create_simple_agent(user_id, session_id)
    elif agent_type == 'complex':
        return create_complex_agent(user_id, session_id)
    else:
        return create_agent(user_id, session_id)
