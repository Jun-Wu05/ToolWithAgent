# -*- coding: utf-8 -*-
"""
枚举值提取工具

功能：
1. 从日志中采样指定行数
2. 验证 LLM 输出的正则表达式
3. 用正则扫描全量日志，提取枚举值
4. 生成映射表和输出 JSON
"""

from __future__ import annotations

import json
import re
from collections import Counter, OrderedDict
from typing import Optional


def sample_logs(logs_str: str, sample_size: int = 20) -> str:
    """
    从日志中均匀采样指定行数
    
    从开头、中间、结尾各取一部分，保证样本有代表性
    
    Args:
        logs_str: 原始日志字符串
        sample_size: 采样行数，默认20行
        
    Returns:
        采样的日志字符串
    """
    lines = [line for line in logs_str.strip().split('\n') if line.strip()]
    
    if not lines:
        return ""
    
    total_lines = len(lines)
    
    # 如果日志行数小于采样数，直接返回全部
    if total_lines <= sample_size:
        return '\n'.join(lines)
    
    # 均匀采样策略：将日志分成 sample_size 段，每段取1行
    step = total_lines / sample_size
    sampled_indices = [int(i * step) for i in range(sample_size)]
    
    # 去重并保持顺序
    seen = set()
    unique_indices = []
    for idx in sampled_indices:
        if idx not in seen:
            seen.add(idx)
            unique_indices.append(idx)
    
    sampled_lines = [lines[i] for i in unique_indices if i < total_lines]
    
    return '\n'.join(sampled_lines)


def validate_regex(regex: str, sample_logs: str) -> dict:
    """
    验证正则表达式是否能从采样日志中提取到值
    
    Args:
        regex: LLM 输出的正则表达式
        sample_logs: 采样日志
        
    Returns:
        {"valid": bool, "matches": list, "error": str}
    """
    try:
        pattern = re.compile(regex)
    except re.error as e:
        return {"valid": False, "matches": [], "error": f"正则语法错误: {e}"}
    
    matches = []
    for line in sample_logs.strip().split('\n'):
        line_matches = pattern.findall(line)
        matches.extend(line_matches)
    
    # 去重
    unique_matches = list(OrderedDict.fromkeys(matches))
    
    if not unique_matches:
        return {"valid": False, "matches": [], "error": "正则未匹配到任何值"}
    
    return {"valid": True, "matches": unique_matches, "error": None}


def validate_regex_with_stats(regex: str, sampled_logs: str) -> dict:
    """
    验证正则并返回统计信息
    
    Args:
        regex: 正则表达式
        sampled_logs: 采样日志
        
    Returns:
        {
            "valid": bool,
            "matches": list,
            "match_rate": float,  # 匹配率 0-1
            "error": str | None
        }
    """
    lines = [l for l in sampled_logs.strip().split('\n') if l.strip()]
    total = len(lines)
    
    if total == 0:
        return {"valid": False, "matches": [], "match_rate": 0, "error": "无日志样本"}
    
    try:
        pattern = re.compile(regex)
    except re.error as e:
        return {"valid": False, "matches": [], "match_rate": 0, "error": f"正则语法错误: {e}"}
    
    matches = []
    matched_lines = 0
    
    for line in lines:
        match = pattern.search(line)
        if match:
            matched_lines += 1
            if match.lastindex:
                matches.append(match.group(1))
            else:
                matches.append(match.group(0))
    
    unique_matches = list(OrderedDict.fromkeys(matches))
    match_rate = matched_lines / total if total > 0 else 0
    
    return {
        "valid": matched_lines > 0,
        "matches": unique_matches,
        "match_rate": match_rate,
        "error": None if matched_lines > 0 else "无匹配"
    }


def validate_and_fix_regex(regex: str, sampled_logs: str, field_name: str) -> dict:
    """
    验证正则，失败时尝试5种常用模式修复
    
    Args:
        regex: LLM 输出的正则表达式
        sampled_logs: 采样日志
        field_name: 目标字段名
        
    Returns:
        {
            "regex": str | None,  # 最终使用的正则
            "valid": bool,
            "confidence": "high" | "medium" | "low",
            "source": "llm" | "fallback" | "failed"
        }
    """
    # 1. 先验证 LLM 生成的正则
    result = validate_regex_with_stats(regex, sampled_logs)
    if result["valid"] and result["match_rate"] >= 0.5:
        return {
            "regex": regex,
            "valid": True,
            "confidence": "high" if result["match_rate"] >= 0.8 else "medium",
            "source": "llm",
            "matches": result["matches"]
        }
    
    # 2. 尝试5种备用模式
    fallback_patterns = [
        (f'"{field_name}":"([^"]+)"', "JSON带引号"),
        (f'{field_name}="([^"]+)"', 'key="value"格式'),
        (f'{field_name}=([^\s]+)', 'key=value格式'),
        (f'"{field_name}":\\s*"([^"]+)"', "JSON带空格"),
        (f'{field_name}[=:]\\s*([^,}}\\s]+)', "宽松匹配"),
    ]
    
    for pattern, pattern_type in fallback_patterns:
        result = validate_regex_with_stats(pattern, sampled_logs)
        if result["valid"] and result["match_rate"] >= 0.5:
            return {
                "regex": pattern,
                "valid": True,
                "confidence": "medium",
                "source": "fallback",
                "fallback_type": pattern_type,
                "matches": result["matches"]
            }
    
    # 3. 全部失败
    return {
        "regex": None,
        "valid": False,
        "confidence": "low",
        "source": "failed",
        "original_error": result.get("error")
    }


def extract_enum_values(logs_str: str, regex: str, max_values: int = 100) -> dict:
    """
    用正则扫描全量日志，提取枚举值及原始样本
    
    Args:
        logs_str: 全量日志字符串
        regex: 验证通过的正则表达式
        max_values: 最大返回枚举值数量，默认100
        
    Returns:
        {
            "field": 字段名,
            "regex": 正则表达式,
            "original_log": [每种枚举值的原始日志样本],
            "value": [枚举值列表],
            "total_count": 总匹配行数,
            "value_counts": {枚举值: 出现次数}
        }
    """
    try:
        pattern = re.compile(regex)
    except re.error as e:
        raise ValueError(f"正则语法错误: {e}")
    
    # value_lines: 枚举值 -> 原始日志列表
    value_lines: OrderedDict = OrderedDict()
    total_count = 0
    
    for line in logs_str.strip().split('\n'):
        if not line.strip():
            continue
            
        matches = pattern.findall(line)
        
        for match in matches:
            # 处理元组匹配结果
            if isinstance(match, tuple):
                match_value = next((item for item in match if item), "")
            else:
                match_value = str(match)
            
            if match_value:
                total_count += 1
                if match_value not in value_lines:
                    value_lines[match_value] = []
                value_lines[match_value].append(line)
    
    # 转换为结果格式
    values = list(value_lines.keys())
    value_counts = {v: len(lines) for v, lines in value_lines.items()}
    
    # 按出现次数排序
    sorted_items = sorted(value_lines.items(), key=lambda x: len(x[1]), reverse=True)
    
    # 每个枚举值只取第一条原始日志作为样本
    original_logs = [lines[0] for _, lines in sorted_items[:max_values]]
    
    return {
        "original_log": original_logs,
        "value": values[:max_values],
        "total_count": total_count,
        "value_counts": value_counts,
        "unique_count": len(values)
    }


def extract_enum_with_field(logs_str: str, field_name: str, regex: str, max_values: int = 100) -> dict:
    """
    提取指定字段的枚举值（带字段名）
    
    Args:
        logs_str: 全量日志字符串
        field_name: 目标字段名
        regex: 验证通过的正则表达式
        max_values: 最大返回枚举值数量
        
    Returns:
        {
            "field": 字段名,
            "regex": 正则表达式,
            "original_log": [每种枚举值的原始日志样本],
            "value": [枚举值列表],
            "total_count": 总匹配行数,
            "value_counts": {枚举值: 出现次数}
        }
    """
    result = extract_enum_values(logs_str, regex, max_values)
    result["field"] = field_name
    return result

