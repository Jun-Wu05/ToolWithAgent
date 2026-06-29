"""
通用辅助函数 - 从 chainlit_app.py 提取

本模块包含纯辅助函数，无 Chainlit 依赖，可以在后台线程中安全调用。
"""

import json
from typing import Set, Optional, List, Dict, Any

from agent.shared.logger import get_logger

logger = get_logger("web.utils")


# === 枚举映射表列头关键词（用于区分枚举映射表 vs 数据表格）===
_ENUM_HEADER_KEYWORDS: Set[str] = {
    "mappingtype", "orgvalue", "mappingvalue",
    "原始值", "映射值", "映射类型",
    "目标字段", "target_field", "targetfield"
}


def is_enum_mapping_excel(excel_path: str) -> bool:
    """
    通过列头判断 Excel 是否为枚举映射表（而非数据表格）。

    Args:
        excel_path: Excel 文件路径

    Returns:
        True 如果列头匹配枚举映射表关键词，False 表示是普通数据表格

    Raises:
        无，异常时返回 False 并记录警告日志
    """
    try:
        from openpyxl import load_workbook
        wb = load_workbook(excel_path, read_only=True)
        try:
            if not wb.sheetnames:
                return False
            ws = wb[wb.sheetnames[0]]
            # 读取第一行列头
            row1_cells = [cell for cell in ws[1] if cell.value is not None]
            if not row1_cells:
                return False
            row1_headers = {str(cell.value).strip().lower() for cell in row1_cells if str(cell.value).strip()}
            # 判断是否包含枚举映射表关键词
            return bool(row1_headers & _ENUM_HEADER_KEYWORDS)
        finally:
            wb.close()
    except Exception as e:
        logger.warning(f"[ENUM_DETECT] 枚举表头检测异常，回退为数据表格: {e}")
        return False


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


def parse_mapping_results(llm_output: str) -> Optional[List[Dict[str, Any]]]:
    """
    从 LLM 输出中解析映射结果 JSON 数组（健壮解析）。

    尝试顺序：
    1. 直接 json.loads（LLM 理想输出）
    2. 去除 markdown 代码块后再解析
    3. 正则提取 [...] JSON 数组

    Args:
        llm_output: LLM 返回的文本

    Returns:
        解析后的字典列表，失败返回 None

    Examples:
        >>> parse_mapping_results('[{"field": "name"}]')
        [{"field": "name"}]

        >>> parse_mapping_results('```json\\n[{"field": "name"}]\\n```')
        [{"field": "name"}]
    """
    if not llm_output or not llm_output.strip():
        return None

    text = llm_output.strip()

    # 尝试 1: 直接解析
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    # 尝试 2: 去除 markdown 代码块
    import re as _re
    code_block_match = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, _re.DOTALL)
    if code_block_match:
        try:
            parsed = json.loads(code_block_match.group(1).strip())
            if isinstance(parsed, list) and parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    # 尝试 3: 正则提取最外层 [...]
    bracket_match = _re.search(r"\[.*\]", text, _re.DOTALL)
    if bracket_match:
        try:
            parsed = json.loads(bracket_match.group())
            if isinstance(parsed, list) and parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    return None


def load_object_entity_map() -> Dict[str, str]:
    """
    从 config/对象.xlsx 加载 系统属性名称→对象 映射。

    Returns:
        系统属性名称到对象的映射字典

    Raises:
        无，异常时返回空字典并记录警告日志
    """
    try:
        from agent.tools.standard_mapper import _load_object_mapping
        import os
        excel_path = os.path.join(os.getcwd(), "config", "对象.xlsx")
        return _load_object_mapping(excel_path)
    except Exception as e:
        logger.warning(f"[MAP] 加载对象映射失败: {e}，使用默认 '事件'")
        return {}


def render_mapping_result(
    mapping_results: List[Dict[str, Any]], total_rule_count: int
) -> str:
    """
    渲染标准字段映射结果（Markdown 表格）。

    默认只展示第 1 条子规则，其余折叠提示。

    Args:
        mapping_results: 映射结果列表
        total_rule_count: 总子规则数量

    Returns:
        Markdown 格式的映射结果字符串
    """
    lines: List[str] = []
    lines.append(f"## 📋 子规则字段映射结果（共 {total_rule_count} 条子规则）")
    lines.append("")

    for idx, mr in enumerate(mapping_results):
        rule_name = mr.get("rule_name", "未知")
        mappings = mr.get("mappings", [])
        is_first = idx == 0

        if is_first:
            lines.append(f"### 子规则 {idx + 1}：{rule_name}")
        else:
            lines.append(f"<details><summary>▶ 子规则 {idx + 1}：{rule_name}（点击展开）</summary>\n")

        lines.append("")
        lines.append("| 原始字段 | 标准字段 | 匹配状态 |")
        lines.append("|----------|---------|---------|")
        for m in mappings:
            orig = m.get("原始字段名", "")
            std = m.get("系统属性名称", "")
            status = m.get("匹配状态", "")
            status_icon = "✅" if "匹配成功" in status else "❌"
            lines.append(f"| {orig} | {std} | {status_icon} {status} |")

        # 统计
        matched = sum(1 for m in mappings if "匹配成功" in m.get("匹配状态", ""))
        total = len(mappings)
        lines.append(f"\n> 匹配率：{matched}/{total}")

        if not is_first:
            lines.append("\n</details>\n")

    lines.append("\n💡 点击上方 **📥 导出映射后子规则** 下载带标准字段映射的子规则文件。")
    return "\n".join(lines)


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
    feature_identifier = classification.get("feature_identifier", "")
    overall_summary = classification.get("overall_summary", "")
    categorical_features = classification.get("categorical_features", "")
    diversion_method = classification.get("Diversion_method", "")
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

    if overall_summary:
        lines.append("")
        lines.append(f"### 📝 综合描述")
        lines.append(overall_summary)

    if details:
        lines.append("")
        lines.append(f"### 📊 分类详情（{len(details)} 类）")
        lines.append("")
        lines.append("| 特征值 | 真实样例 |")
        lines.append("|---|---|")
        for _d in details:
            # CHANGED: 字段值与特征值列重复，已移除冗余列
            feature_val = str(_d.get("logtype", ""))
            real_samples = _d.get("real_samples", [])
            if isinstance(real_samples, str):
                sample = real_samples
            elif real_samples:
                sample = real_samples[0] if isinstance(real_samples, list) else str(real_samples)
            else:
                sample = str(_d.get("sample", ""))
            lines.append(f"| {feature_val} | {sample} |")

    lines.append("")
    lines.append("*以上结果由 LogParser Pipeline 直接生成*")
    return "\n".join(lines)