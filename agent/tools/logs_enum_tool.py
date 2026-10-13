# -*- coding: utf-8 -*-
"""
日志枚举值提取工具

功能：
1. 从明文日志中采样供 LLM 分析
2. 调用 LLM 生成正则表达式
3. 验证并自动修复正则
4. 扫描全量日志提取枚举值
5. 返回映射表和 JSON 格式结果
"""

from __future__ import annotations

import json
from agno.tools import tool

from agent.tools.enum_extract_tool import (
    sample_logs,
    validate_and_fix_regex,
    extract_enum_values,
    format_mapping_table,
)
from agent.prompts import load_enum_extract_prompt


@tool(name="extract_enum_from_logs", description="从明文日志中提取指定字段的所有枚举值。输入：logs=日志内容, field_name=目标字段名。返回：枚举值列表、映射表、JSON格式结果。")
def extract_enum_from_logs(logs: str, field_name: str) -> str:
    """
    从明文日志中提取指定字段的所有枚举值
    
    Args:
        logs: 明文日志内容（多行）
        field_name: 目标字段名
        
    Returns:
        JSON 字符串，包含 field, regex, original_log, value, mapping_table
    """
    try:
        # 1. 采样日志供 LLM 分析（20行）
        sampled_logs = sample_logs(logs, 20)
        
        if not sampled_logs:
            return json.dumps({"error": "日志内容为空"}, ensure_ascii=False)
        
        # 2. 加载提示词
        prompt = load_enum_extract_prompt()

        # 注意：由于 Agent 工具无法直接调用 LLM，这里返回采样与提示词，
        # 实际正则生成由 Agent 的推理能力处理
        return json.dumps({
            "status": "need_regex",
            "field_name": field_name,
            "sampled_logs": sampled_logs,
            "prompt": prompt,
            "instruction": f"请分析以上采样日志，为字段 '{field_name}' 生成提取正则表达式"
        }, ensure_ascii=False)
        
    except FileNotFoundError as e:
        return json.dumps({"error": f"提示词文件缺失: {e}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"枚举提取失败: {e}"}, ensure_ascii=False)


def extract_enum_with_regex(logs: str, field_name: str, regex: str) -> str:
    """
    使用正则表达式提取枚举值
    
    Args:
        logs: 明文日志内容
        field_name: 目标字段名
        regex: 已验证的正则表达式
        
    Returns:
        JSON 字符串，包含完整结果
    """
    try:
        # 验证并修复正则
        sampled_logs = sample_logs(logs, 20)
        validated = validate_and_fix_regex(regex, sampled_logs, field_name)
        
        if not validated["valid"]:
            return json.dumps({
                "field": field_name,
                "regex": regex,
                "error": "正则验证失败",
                "validation": validated
            }, ensure_ascii=False)
        
        # 提取枚举值
        result = extract_enum_values(logs, validated["regex"])
        
        # 生成映射表
        mapping_table = format_mapping_table(result)
        
        # 整合结果
        output = {
            "field": field_name,
            "regex": validated["regex"],
            "regex_source": validated.get("source", "unknown"),
            "confidence": validated.get("confidence", "low"),
            "unique_count": result.get("unique_count", 0),
            "total_count": result.get("total_count", 0),
            "original_log": result.get("original_log", []),
            "value": result.get("value", []),
            "mapping_table": mapping_table
        }
        
        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": f"枚举提取失败: {e}"}, ensure_ascii=False)