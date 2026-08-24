"""纯辅助函数（无 Chainlit 依赖，可在后台线程安全调用）。

历史遗留的旧解析/渲染函数（parse_mapping_results、render_mapping_result、
content_to_str、load_object_entity_map）与 utils 版 is_enum_mapping_excel
重复副本已删除；存活实现位于 web/parsers.py、web/plan_renderer.py 与
web/file_handlers.py。
"""

import json
from typing import Optional, Dict, Any, List

from agent.shared.logger import get_logger

logger = get_logger("web.utils")


def parse_json_safe(text: str) -> Optional[Dict[str, Any]]:
    """
    安全解析 JSON，支持 markdown 代码块包装

    Args:
        text: 待解析的 JSON 文本

    Returns:
        解析后的字典，失败返回 None

    Examples:
        >>> parse_json_safe('{"key": "value"}')
        {"key": "value"}

        >>> parse_json_safe('```json\\n{"key": "value"}\\n```')
        {"key": "value"}
    """
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re as _re
        m = _re.search(r"\{.*\}", text, _re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None


def render_log_parser_result(
    classification: Optional[Dict[str, Any]], format_info: Optional[Dict[str, Any]]
) -> str:
    """
    将 pipeline 结果渲染为用户可读的 Markdown 文本

    Args:
        classification: 日志分类结果
        format_info: 格式信息

    Returns:
        Markdown 格式的日志解析结果字符串
    """
    if classification is None:
        return "❌ 日志解析失败：无法解析分类结果"

    status = classification.get("status", "FAILED")
    if status == "FAILED":
        error = classification.get("error", "未知错误")
        return f"❌ 日志解析失败: {error}"

    log_format = classification.get("log_format", "未知")
    feature_field = classification.get("feature_field", "log_type")
    feature_count = classification.get("feature_count", 0)
    overall_summary = classification.get("overall_summary", "")
    details = classification.get("classification_details", [])

    lines: List[str] = []
    lines.append("## 🔍 日志解析结果")
    lines.append("")

    # CHANGED: 日志格式 + 格式详情合并显示，精简展示项
    log_format_detail = classification.get("log_format_detail", "")
    if log_format_detail and log_format_detail != log_format:
        format_display = f"{log_format}（{log_format_detail}）"
    else:
        format_display = log_format

    # CHANGED: 从 analysis 提取分隔符（KV 格式专用）
    analysis = classification.get("analysis", {})
    delimit = analysis.get("delimit", "")
    tab = analysis.get("tab", "")
    is_kv = str(log_format).upper() == "KV"

    lines.append(f"| 项目 | 值 |")
    lines.append(f"|---|---|")
    lines.append(f"| 日志格式 | {format_display} |")
    lines.append(f"| 业务分类字段 | `{feature_field}` |")
    lines.append(f"| 分类数量 | {feature_count} |")
    # CHANGED: KV 格式展示分隔符（含"判断失败"），JSON 格式隐藏
    if is_kv:
        lines.append(f"| 字段分隔符 | {delimit or '判断失败'} |")
        lines.append(f"| 键值分隔符 | {tab or '判断失败'} |")

    # 未匹配行覆盖信息：不含分类特征字段的行不归入任何类型，单独提示而非进入分类。
    coverage = classification.get("coverage") or {}
    unmatched_lines = int(coverage.get("unmatched_lines", 0) or 0)
    if unmatched_lines > 0:
        total_lines = int(coverage.get("total_lines", 0) or 0)
        lines.append("")
        lines.append(f"### ⚠️ 未归入任何类型：{unmatched_lines}/{total_lines} 行")
        unmatched_samples = coverage.get("unmatched_samples") or []
        if unmatched_samples:
            lines.append("")
            lines.append("```")
            for sample in unmatched_samples:
                lines.append(str(sample))
            lines.append("```")
        lines.append("")
        lines.append(
            "这些行不含分类特征字段，可能属于其他日志类型字段；"
            "可指定其他字段作为日志类型，或改用自动探测重新提取。"
        )

    if overall_summary:
        lines.append("")
        lines.append(f"### 📝 综合描述")
        lines.append(overall_summary)

    if details:
        lines.append("")
        lines.append(f"### 📊 分类详情（{len(details)} 类）")
        lines.append("")
        # CHANGED (2026-07-28): 样例改用代码块展示，而非 Markdown 表格。
        # 原因：KV 日志行含 | 分隔符（uuid=xxx|name=yyy|...），放进表格后
        # | 被当作列分隔符，整行被切成多列，界面只显示第一个 | 之前的内容。
        # 代码块内 | 不被解析，完整样例原样可见。
        for _d in details:
            feature_val = str(_d.get("logtype", ""))
            real_samples = _d.get("real_samples", [])
            if isinstance(real_samples, str):
                sample = real_samples
            elif real_samples:
                sample = real_samples[0] if isinstance(real_samples, list) else str(real_samples)
            else:
                sample = str(_d.get("sample", ""))
            lines.append(f"**{feature_val}**")
            lines.append(f"```\n{sample}\n```")
            lines.append("")

    lines.append("")
    lines.append("*以上结果由 LogParser Pipeline 直接生成*")
    return "\n".join(lines)
