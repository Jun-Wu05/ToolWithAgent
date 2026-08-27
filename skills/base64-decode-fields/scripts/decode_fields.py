"""
Base64 解码字段脚本 - 在解析规则中对指定字段启用运行时 base64 解码

CLI 用法:
    python decode_fields.py '<json_array>' 'req_header,req_body'

import 用法:
    from decode_fields import decode_fields
    result = decode_fields(data, ["req_header", "req_body"])
"""

import json
import sys
import copy
from typing import List, Optional

# 运行时 OGNL 解码语句模板：值原地覆盖原字段（key=字段名）
_OGNL_TEMPLATE = "<%@com.hansight.dataviewer.utils.Base64@Base64Decode({field})%>"


def _is_decode_filter(filter_item: dict) -> bool:
    """判断 addFields filter 是否为 base64 解码过滤器（全部值都是解码 OGNL）。"""
    if filter_item.get("name") != "addFields" or filter_item.get("id") != "":
        return False
    fields = filter_item.get("fields")
    if not isinstance(fields, dict) or not fields:
        return False
    return all(
        isinstance(value, str) and "Base64Decode(" in value
        for value in fields.values()
    )


def decode_fields(
    data: list,
    field_names: List[str],
    target_names: Optional[List[str]] = None,
) -> dict:
    """
    对 mapping entity 列表的指定字段启用 base64 解码。

    只改 parser.filter：在（或新建的）解码 addFields 过滤器中写入
    ``{字段名: Base64Decode OGNL}``，运行时由解析器原地覆盖字段值；
    不改 normalize（与添加字段的双写语义不同）。

    Args:
        data: 解码后的 JSON 数组（mapping entities）
        field_names: 需要 base64 解码的字段名列表
        target_names: 目标 entity 名单（按 name 精确匹配，#126）；
                      None 表示全部 entity。名单外的 entity 原样透传。

    Returns:
        {"status": "success"|"error", "data": [...], "message": "..."}
    """
    if not data:
        return {"status": "error", "message": "输入数据为空"}

    if not field_names:
        return {"status": "error", "message": "未指定要解码的字段"}

    targets = set(target_names) if target_names else None
    results = []
    applied = 0
    skipped_empty = 0
    skipped_reasons: list[tuple[str, str]] = []
    for entity in data:
        entity = copy.deepcopy(entity)

        if targets is not None and entity.get("name") not in targets:
            results.append(entity)
            continue

        normalize = entity.get("normalize") or []
        name = entity.get("name") or "<未命名>"
        if not normalize:
            skipped_empty += 1
            results.append(entity)
            continue

        norm_indexes = {item.get("index") for item in normalize if item.get("index")}
        missing = [f for f in field_names if f not in norm_indexes]
        if missing:
            # 子规则字段集不同：缺字段的 entity 跳过并按名报告（#147）
            skipped_reasons.append((name, f"缺 {'、'.join(missing)}"))
            results.append(entity)
            continue

        parser = entity.get("parser") or {}
        filters = parser.get("filter") or []

        # 合并进已有的解码过滤器，保持幂等（重复调用不重复追加）
        decode_filter = next((f for f in filters if _is_decode_filter(f)), None)
        if decode_filter is None:
            decode_filter = {"fields": {}, "name": "addFields", "id": ""}
            filters.append(decode_filter)

        for field_name in field_names:
            decode_filter["fields"][field_name] = _OGNL_TEMPLATE.format(field=field_name)

        parser["filter"] = filters
        entity["parser"] = parser

        applied += 1
        results.append(entity)

    message = f"成功为 {applied} 个 entity 启用 base64 解码: {', '.join(field_names)}"
    if targets is not None:
        message += f"（目标 {len(targets)} 个）"
    if skipped_reasons:
        # 所有目标 entity 都缺字段 → 真错误（#147：与 merge 的全缺行为一致）
        if applied == 0:
            return {
                "status": "error",
                "message": f"字段 {field_names} 不存在于任何（目标）子规则",
            }
        detail = "；".join(f"{n}（{r}）" for n, r in skipped_reasons[:5])
        more = f" 等 {len(skipped_reasons)} 条" if len(skipped_reasons) > 5 else ""
        message += f"；跳过：{detail}{more}"
    if skipped_empty:
        message += f"（跳过 {skipped_empty} 个无 normalize 的 entity）"
    return {"status": "success", "data": results, "message": message}


def main():
    """CLI 入口"""
    if len(sys.argv) < 3:
        print(json.dumps({
            "status": "error",
            "message": "用法: python decode_fields.py '<json>' '<field1,field2>'",
        }, ensure_ascii=False))
        sys.exit(1)

    data = json.loads(sys.argv[1])
    field_names = [name for name in sys.argv[2].split(",") if name.strip()]

    result = decode_fields(data, field_names)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
