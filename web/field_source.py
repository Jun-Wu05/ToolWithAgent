"""
日志字段来源 — 从日志解析结果提取真实字段，供字段映射使用。

背景（2026-07-28 修复）：
  自然语言「映射」曾直接用 Excel 列头（decoded_fields = df.columns），
  导致 LLM 映射的是「发生时间/事件名称/原始日志」等列头，而非日志
  KV 行里的真实字段（uuid/name/srcIp/...）。

  按钮路径（on_apply_field_mapping）一直是对的：从 log_classification
  生成子规则，提取 normalize 里的 index 字段。本模块将该逻辑抽出，
  让自然语言路径与按钮路径复用同一份字段来源。

CHANGED (2026-07-29):
  新增从原始日志直接提取字段的兜底——用户未做日志解析时，也能从
  raw_log_lines 用 KvExtractor 提取 KV 字段，不再强制先做日志解析。
"""
import re
from typing import List, Optional

from agent.shared.logger import get_logger
from agent.tools.rule_generator import generate_sub_rules
from agent.tools.rule_generator.field_mapping import EXCLUDED_FIELD_INDICES

logger = get_logger("field_source")

# 直接从 KV 日志行提取字段名的正则（兼容 | 和空格分隔）
_KV_KEY_RE = re.compile(r"(?:^|[\s|])([a-zA-Z_][a-zA-Z0-9_]*)=")


def extract_log_fields_for_mapping(
    classification: Optional[dict],
    raw_log_lines: Optional[list] = None,
) -> List[str]:
    """提取真实日志字段（去重、排序）。

    优先级：
    1. 有 log_classification → 从子规则 normalize 提取（最准确，复用按钮路径）
    2. 无解析结果但有 raw_log_lines → 从日志行直接提取 KV 字段名（兜底）
    3. 都没有 → 返回空列表

    Args:
        classification: log_classification（日志解析结果），可选。
        raw_log_lines:  原始日志行列表，可选。

    Returns:
        去重排序后的字段名列表；无数据时返回空列表。
    """
    # 路径 1：从日志解析结果提取（最准确）
    if classification and isinstance(classification, dict):
        all_logs_str = ""
        if raw_log_lines:
            all_logs_str = "\n".join(str(line) for line in raw_log_lines)
        try:
            sub_rules = generate_sub_rules(classification, all_logs_str=all_logs_str)
        except Exception as e:
            logger.warning(f"[FIELD_SOURCE] 生成子规则失败: {e}")
            sub_rules = []

        if sub_rules:
            all_fields = []
            for rule in sub_rules:
                fields = [
                    entry.get("index", "")
                    for entry in rule.get("normalize", [])
                    if entry.get("index", "") and entry.get("index", "") not in EXCLUDED_FIELD_INDICES
                ]
                all_fields.extend(fields)
            all_fields = sorted(set(all_fields))
            if all_fields:
                logger.info(f"[FIELD_SOURCE] 从日志解析结果提取 {len(all_fields)} 个真实字段")
                return all_fields

    # 路径 2：从原始日志行直接提取 KV 字段名（兜底，无需先做日志解析）
    if raw_log_lines:
        fields = _extract_kv_fields_from_lines(raw_log_lines)
        if fields:
            logger.info(f"[FIELD_SOURCE] 从原始日志行直接提取 {len(fields)} 个 KV 字段（未做日志解析的兜底）")
            return fields

    return []


def _extract_kv_fields_from_lines(raw_log_lines: list, max_lines: int = 20) -> List[str]:
    """从原始日志行直接提取 KV 字段名（兜底方案）。

    不依赖日志解析结果，直接用正则从日志行扫描 key= 模式。
    采样前 max_lines 行（足够覆盖所有字段），去重排序。

    Args:
        raw_log_lines: 原始日志行列表。
        max_lines:     采样行数上限。

    Returns:
        去重排序后的字段名列表。
    """
    fields = set()
    for line in raw_log_lines[:max_lines]:
        if not isinstance(line, str):
            continue
        for match in _KV_KEY_RE.finditer(line):
            fields.add(match.group(1))

    # 排除明显的非字段噪音（如纯数字、过短 key）
    cleaned = sorted(f for f in fields if len(f) >= 2)
    return cleaned
