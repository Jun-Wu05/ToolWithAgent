r"""
正则提取字段脚本 - 在解析规则中新增 customFunction 正则提取过滤器

CLI 用法:
    python extract_field.py '<json_array>' 'newclient' 'original_log' '<pattern>' '[keyword]'

import 用法:
    from extract_field import extract_field
    result = extract_field(
        data, "newclient", "original_log",
        r'[\S\s]*client="(.*?)"[\S\s]*', keyword="client",
    )
"""

import json
import re
import sys
import copy
from typing import Optional

# 运行时 OGNL 提取语句（固定；arg2=被提取字段，arg3=正则）
_OGNL_TEMPLATE = (
    '<%@com.hansight.dataviewer.utils.ognl.OgnlUtils@regexExtraction(arg2,"arg3")%>'
)


def _normalize_entry(index: str, result_value: str) -> dict:
    """构建正则提取新增字段的 normalize 条目（result 为样本预览值）。"""
    return {
        "mappings": [],
        "field": None,
        "sim": None,
        "result": [result_value] if result_value else [],
        "info": None,
        "entity": None,
        "required": False,
        "core": None,
        "value": None,
        "index": index,
    }


def _build_function_item(new_field: str, source_field: str, pattern: str) -> dict:
    """构建一个 extractRegexField 函数条目（args 三元组结构与设计文档一致）。"""
    return {
        "functionName": "extractRegexField",
        "ognl": _OGNL_TEMPLATE,
        "functionViewName": "正则提取",
        "fieldName": "",
        "args": [
            {
                "name": "新增字段",
                "args": "arg1",
                "detail": "新增字段名称",
                "type": "field",
                "value": new_field,
            },
            {
                "name": "被提取字段",
                "args": "arg2",
                "detail": "字符格式字段",
                "type": "args",
                "value": source_field,
            },
            {
                "name": "正则表达式",
                "args": "arg3",
                "detail": "只提取第一个匹配项",
                "type": "args",
                "value": pattern,
            },
        ],
    }


def extract_field(
    data: list,
    new_field: Optional[str],
    source_field: str,
    pattern: str,
    keyword: Optional[str] = None,
) -> dict:
    """
    对 mapping entity 列表新增正则提取字段。

    双写：parser.filter 追加（或合并进）customFunction 过滤器；
    normalize 末尾追加新字段条目。当被提取字段有样本值时，用样本
    验证正则必须**全匹配**整条样本（设计约束：非全匹配不生效），
    预览值取第一个捕获组。

    Args:
        data: 解码后的 JSON 数组（mapping entities）
        new_field: 新字段名；None 时按 keyword（提取目标关键词）自动
            命名——关键词已存在则加 new 前缀；keyword 也缺省时退回
            被提取字段名尾段。
        source_field: 被提取字段（必须为 normalize 里的 index）
        pattern: 正则表达式（必须可全匹配样本整条）
        keyword: 提取目标关键词（如 "client"、"Referer"），缺省命名用

    Returns:
        {"status": "success"|"error", "data": [...], "message": "..."}
    """
    if not data:
        return {"status": "error", "message": "输入数据为空"}

    if not source_field:
        return {"status": "error", "message": "未指定被提取字段"}

    if not pattern:
        return {"status": "error", "message": "未指定正则表达式"}

    try:
        compiled = re.compile(pattern)
    except re.error as error:
        return {"status": "error", "message": f"正则表达式不合法: {error}"}

    results = []
    applied = 0
    skipped = 0
    resolved_name = new_field
    for entity in data:
        entity = copy.deepcopy(entity)

        normalize = entity.get("normalize") or []
        if not normalize:
            skipped += 1
            results.append(entity)
            continue

        norm_map = {item.get("index"): item for item in normalize if item.get("index")}
        if source_field not in norm_map:
            return {
                "status": "error",
                "message": (
                    f"被提取字段 '{source_field}' 不存在，"
                    f"可用字段: {sorted(norm_map)}"
                ),
            }

        # 新字段名解析：显式传入优先；缺省按提取关键词命名，冲突加 new 前缀
        if not resolved_name:
            resolved_name = _default_field_name(keyword, source_field, norm_map)
        if resolved_name in norm_map:
            return {
                "status": "error",
                "message": f"新增字段 '{resolved_name}' 已存在，请先删除或更换名称",
            }

        # 样本验证：正则必须全匹配整条样本（设计约束）
        sample_entry = norm_map.get(source_field, {})
        sample_result = sample_entry.get("result") or []
        sample_text = str(sample_result[0]) if sample_result else ""
        preview_value = ""
        if sample_text:
            matched = compiled.fullmatch(sample_text)
            if matched is None:
                return {
                    "status": "error",
                    "message": (
                        f"正则无法全匹配「{source_field}」的样本（必须整条匹配才能生效），"
                        "请调整正则或样本"
                    ),
                }
            preview_value = matched.group(1) if matched.groups() else matched.group(0)

        # 1. 追加（或合并进）customFunction 过滤器
        parser = entity.get("parser") or {}
        filters = parser.get("filter") or []
        custom_filter = next(
            (f for f in filters if f.get("name") == "customFunction" and f.get("id") == ""),
            None,
        )
        if custom_filter is None:
            custom_filter = {
                "custom_name": "extractRegexField",
                "fields": [],
                "name": "customFunction",
                "id": "",
            }
            filters.append(custom_filter)

        function_item = _build_function_item(resolved_name, source_field, pattern)
        existing_index = next(
            (
                i for i, item in enumerate(custom_filter.get("fields") or [])
                if isinstance(item, dict)
                and any(
                    arg.get("args") == "arg1" and arg.get("value") == resolved_name
                    for arg in item.get("args", [])
                    if isinstance(arg, dict)
                )
            ),
            None,
        )
        if existing_index is not None:
            custom_filter["fields"][existing_index] = function_item
        else:
            custom_filter["fields"].append(function_item)

        parser["filter"] = filters
        entity["parser"] = parser

        # 2. normalize 双写（预览值）
        if existing_index is None:
            normalize.append(_normalize_entry(resolved_name, preview_value))
            entity["normalize"] = normalize

        applied += 1
        results.append(entity)

    message = (
        f"成功为 {applied} 个 entity 添加正则提取字段 '{resolved_name}'"
        f"（来源: {source_field}）"
    )
    if skipped:
        message += f"（跳过 {skipped} 个无 normalize 的 entity）"
    return {"status": "success", "data": results, "message": message}


def _default_field_name(
    keyword: Optional[str], source_field: str, norm_map: dict
) -> str:
    """缺省命名：提取关键词优先（冲突加 new 前缀），无关键词时退回源字段尾段。"""
    base = (keyword or "").strip() or source_field.rsplit(".", 1)[-1]
    if base not in norm_map:
        return base
    return f"new{base}"


def main():
    """CLI 入口"""
    if len(sys.argv) < 4:
        print(json.dumps({
            "status": "error",
            "message": (
                "用法: python extract_field.py '<json>' '[new_field]' "
                "'<source_field>' '<pattern>' '[keyword]'"
            ),
        }, ensure_ascii=False))
        sys.exit(1)

    data = json.loads(sys.argv[1])
    new_field = sys.argv[2] or None
    source_field = sys.argv[3]
    pattern = sys.argv[4] if len(sys.argv) > 4 else ""
    keyword = sys.argv[5] if len(sys.argv) > 5 else None

    result = extract_field(data, new_field, source_field, pattern, keyword=keyword)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
