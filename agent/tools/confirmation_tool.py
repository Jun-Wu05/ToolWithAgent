"""
确认工具 - Human-in-the-Loop

用于在关键节点请求用户确认
"""

import json
from typing import Any, Optional

from agno.tools import tool


@tool(name="confirm_mapping_table", description="请求用户确认字段映射表", requires_confirmation=True)
def confirm_mapping_table(
    mapping_table: str,
    step_name: str = "字段映射",
    confirmation_message: str = "请确认以下字段映射表"
) -> str:
    """
    展示字段映射表并请求用户确认
    
    此工具会自动暂停执行，等待用户确认后才继续。
    用于关键决策节点，确保用户掌控处理流程。
    
    Args:
        mapping_table: 映射表数据（JSON字符串格式）
            [
                {"原始字段": "content.srcip", "标准字段": "源地址"},
                ...
            ]
        step_name: 步骤名称
        confirmation_message: 确认提示信息
    
    Returns:
        等待确认提示
    """
    # 解析映射表
    try:
        table_data = json.loads(mapping_table) if isinstance(mapping_table, str) else mapping_table
        count = len(table_data) if isinstance(table_data, list) else 0
    except:
        count = 0
    
    return json.dumps({
        "status": "waiting_confirmation",
        "step_name": step_name,
        "confirmation_message": confirmation_message,
        "data": table_data if isinstance(table_data, list) else [],
        "summary": f"等待确认 {step_name}，共 {count} 个映射项",
        "action_required": "请确认是否执行此映射"
    }, ensure_ascii=False, indent=2)


@tool(name="confirm_threat_mapping", description="请求用户确认威胁类型映射", requires_confirmation=True)
def confirm_threat_mapping(
    mapping_table: str,
    confirmation_message: str = "请确认以下威胁类型映射"
) -> str:
    """
    展示威胁类型映射表并请求用户确认
    
    Args:
        mapping_table: 映射表数据（JSON字符串格式）
        confirmation_message: 确认提示信息
    
    Returns:
        等待确认提示
    """
    try:
        table_data = json.loads(mapping_table) if isinstance(mapping_table, str) else mapping_table
        count = len(table_data) if isinstance(table_data, list) else 0
    except:
        count = 0
    
    return json.dumps({
        "status": "waiting_confirmation",
        "step_name": "威胁类型映射",
        "confirmation_message": confirmation_message,
        "data": table_data if isinstance(table_data, list) else [],
        "summary": f"等待确认威胁类型映射，共 {count} 个映射项",
        "action_required": "请确认是否应用此威胁类型映射"
    }, ensure_ascii=False, indent=2)


@tool(name="confirm_output", description="请求用户确认最终输出", requires_confirmation=True)
def confirm_output(
    output_summary: str,
    output_type: str = "Base64"
) -> str:
    """
    在输出前请求用户确认
    
    Args:
        output_summary: 输出摘要
        output_type: 输出类型（Base64/JSON/Excel）
    
    Returns:
        等待确认提示
    """
    return json.dumps({
        "status": "waiting_confirmation",
        "step_name": "最终输出",
        "output_type": output_type,
        "summary": output_summary,
        "confirmation_message": f"请确认是否生成 {output_type} 输出",
        "action_required": "确认后将生成最终输出"
    }, ensure_ascii=False, indent=2)


@tool(name="request_modification", description="请求用户修改映射结果")
def request_modification(
    current_mapping: str,
    modification_type: str = "字段"
) -> str:
    """
    请求用户修改映射结果
    
    Args:
        current_mapping: 当前映射内容
        modification_type: 修改类型（字段/威胁类型/枚举）
    
    Returns:
        修改请求说明
    """
    return json.dumps({
        "status": "modification_requested",
        "modification_type": modification_type,
        "current_mapping": current_mapping,
        "instruction": f"请提供修改后的 {modification_type} 映射",
        "format": "JSON数组格式，每项包含原始值和目标值"
    }, ensure_ascii=False, indent=2)
