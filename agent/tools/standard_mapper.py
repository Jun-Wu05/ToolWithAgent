"""
标准字段映射工具

Agno Tool版本
"""
import json
import base64
import os
from typing import Any, Optional

from agno.tools import tool
from openpyxl import load_workbook

from agent.prompts import load_standard_fields
from agent.shared.logger import get_logger

logger = get_logger("standard_mapper")

# ===== 标准字段名白名单（惰性加载，首次调用时从 标准字段.txt 构建） =====
_valid_field_names: Optional[set] = None


def _get_valid_field_names() -> set:
    """
    从标准字段表加载所有合法的「系统属性名称」集合。

    构建一次后缓存，避免每次映射都读文件解析。
    """
    global _valid_field_names
    if _valid_field_names is None:
        try:
            raw = load_standard_fields()
            names: set = set()
            for line in raw.strip().split("\n")[1:]:  # 跳过表头
                cols = line.strip().split("\t")
                if cols and cols[0]:
                    # 去除 BOM 字符
                    name = cols[0].lstrip("\ufeff").strip()
                    if name:
                        names.add(name)
            _valid_field_names = names
            logger.info(f"[VALIDATOR] 标准字段白名单已加载：{len(names)} 个合法系统属性名称")
        except Exception as e:
            logger.warning(f"[VALIDATOR] 加载标准字段白名单失败: {e}，跳过校验")
            _valid_field_names = set()  # 空集合 = 跳过校验
    return _valid_field_names


def _validate_and_correct_mapping(mapping: dict) -> dict:
    """
    校验单条映射的「系统属性名称」是否在标准字段表中。

    - 若"未匹配"则跳过校验（合法状态）
    - 若匹配成功但名称不在白名单中 → 强制改为"未匹配"并记录警告

    Returns:
        校验/修正后的映射 dict（可能是原始引用或新 dict）
    """
    system_property = mapping.get("系统属性名称", "")
    match_status = mapping.get("匹配状态", "")

    # "未匹配" 是合法终态，无需校验
    if system_property == "未匹配":
        return mapping

    valid_names = _get_valid_field_names()
    if not valid_names:
        # 白名单为空（加载失败），跳过校验
        return mapping

    if system_property not in valid_names:
        logger.warning(
            f"[VALIDATOR] 非法字段名 → 强制降级为未匹配: "
            f"原始字段={mapping.get('原始字段名', '?')}, "
            f"非法名称='{system_property}'"
        )
        # 创建新 dict 避免修改调用方的原始数据
        return {
            "原始字段名": mapping.get("原始字段名", ""),
            "系统属性名称": "未匹配",
            "匹配状态": "未匹配",
            "_校正原因": f"LLM 输出了不在标准字段表中的名称 '{system_property}'",
        }

    return mapping


@tool(name="field_mapping", description="执行标准字段映射")
def field_mapping_tool(
    decoded_json: str,
    field_mapping_table: str,
    excel_template_path: Optional[str] = None
) -> str:
    """
    执行标准字段映射
    
    当需要将原始字段映射到标准字段时使用：
    1. 接收解码后的 JSON 和映射表
    2. 应用字段映射
    3. 管理 simEntities 数组
    4. 返回映射后的 JSON
    
    Args:
        decoded_json: 解码后的 JSON 对象（字符串格式）
        field_mapping_table: 字段映射表（JSON 字符串格式）
            [
                {"原始字段名": "content.srcip", "系统属性名称": "源地址", "匹配状态": "匹配成功"},
                ...
            ]
        excel_template_path: 可选，Excel 模板路径
    
    Returns:
        映射结果
    """
    logger.info(
        f"[TOOL_CALL] field_mapping 被调用: decoded_json_len={len(decoded_json) if decoded_json else 0}, "
        f"mapping_table_len={len(field_mapping_table) if field_mapping_table else 0}"
    )
    try:
        # 解析输入
        json_obj = json.loads(decoded_json) if isinstance(decoded_json, str) else decoded_json
        mapping_table = json.loads(field_mapping_table) if isinstance(field_mapping_table, str) else field_mapping_table
        
        # 默认 Excel 模板路径
        if excel_template_path is None:
            excel_template_path = os.path.join(
                os.getcwd(), "config", "对象.xlsx"
            )
        
        # 读取 Excel 模板
        object_mapping = {}
        if os.path.exists(excel_template_path):
            object_mapping = _load_object_mapping(excel_template_path)
        
        # 解析字段映射表（带字段名合法性校验）
        field_to_object = {}
        field_to_new_value = {}
        corrected_count = 0
        
        for mapping in mapping_table:
            # 校验/修正映射的字段名合法性
            mapping = _validate_and_correct_mapping(mapping)
            
            original_field = mapping.get("原始字段名", "")
            system_property = mapping.get("系统属性名称", "")
            match_status = mapping.get("匹配状态", "")
            
            if "匹配成功" in match_status:
                obj = object_mapping.get(system_property, "事件")
                field_to_object[original_field] = obj
                field_to_new_value[original_field] = system_property
        
        if corrected_count := sum(
            1 for m in mapping_table
            if m.get("_校正原因", "")
        ):
            logger.warning(
                f"[VALIDATOR] 本批共 {corrected_count} 条映射被强制修正为'未匹配'"
                f"（LLM 输出了不在标准字段表中的名称）"
            )
        
        # 应用映射
        processed_json = _apply_field_mapping(json_obj, field_to_new_value, field_to_object)
        
        # 管理 simEntities
        entities_added = _manage_sim_entities(processed_json, field_to_object)
        
        result = {
            "status": "success",
            "processed_json": processed_json,
            "fields_mapped": len(field_to_new_value),
            "entities_added": list(set(entities_added)),
            "message": f"成功映射 {len(field_to_new_value)} 个字段"
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error_message": f"标准字段映射失败: {str(e)}"
        }, ensure_ascii=False)


@tool(name="generate_mapping_table", description="生成字段映射表")
def generate_mapping_table_tool(
    decoded_json: str,
    fields: str
) -> str:
    """
    生成字段映射表
    
    根据解码后的 JSON 和提取的字段，生成建议的映射表：
    1. 接收 JSON 和字段列表
    2. 分析每个字段的可能含义
    3. 生成映射建议
    4. 返回 Markdown 格式的映射表
    
    Args:
        decoded_json: 解码后的 JSON 对象（字符串格式）
        fields: 提取的字段列表（JSON 数组字符串）
    
    Returns:
        Markdown 格式的映射表
    """
    try:
        # 解析输入
        json_obj = json.loads(decoded_json) if isinstance(decoded_json, str) else decoded_json
        field_list = json.loads(fields) if isinstance(fields, str) else fields
        
        # 生成映射表
        mapping_lines = [
            "| 原始字段 | 建议标准字段 | 匹配状态 | 匹配理由 |",
            "|----------|-------------|---------|---------|"
        ]
        
        # 常见字段映射规则
        field_rules = {
            "srcip": ("源地址", "IP地址字段"),
            "dstip": ("目的地址", "IP地址字段"),
            "srcport": ("源端口", "端口字段"),
            "dstport": ("目的端口", "端口字段"),
            "protocol": ("协议", "协议字段"),
            "threat_type": ("威胁类型", "安全相关字段"),
            "action": ("动作", "处理动作字段"),
            "time": ("时间", "时间字段"),
            "content": ("内容", "内容字段"),
        }
        
        for field in field_list:
            field_str = str(field).strip()
            
            # 尝试匹配规则
            matched = False
            for pattern, (std_field, reason) in field_rules.items():
                if pattern in field_str.lower():
                    mapping_lines.append(f"| {field_str} | {std_field} | 匹配成功 | {reason} |")
                    matched = True
                    break
            
            if not matched:
                mapping_lines.append(f"| {field_str} | 需确认 | 待匹配 | 需要根据上下文判断 |")
        
        return "\n".join(mapping_lines)
        
    except Exception as e:
        return f"生成映射表失败: {str(e)}"


def _load_standard_fields_list() -> list[dict]:
    """Load standard fields table as structured list"""
    raw_text = load_standard_fields()
    lines = raw_text.strip().split("\n")
    header = None
    fields = []
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if header is None:
            # Strip BOM from the first column header if present
            raw_cols = [col.strip() for col in line.split("\t")]
            if raw_cols:
                raw_cols[0] = raw_cols[0].lstrip('\ufeff')
            header = raw_cols
            continue
        cols = [col.strip() for col in line.split("\t")]
        if len(cols) >= len(header):
            entry = dict(zip(header, cols))
            fields.append(entry)
    
    return fields


import re


def _split_compound_field(raw_field: str) -> list[str]:
    """自动拆分复合字段名为子部分，支持多种命名风格。

    拆分策略（零硬编码）：
    1. 点号拆分: detail.srcIp → ["detail", "srcIp"]
    2. 下划线拆分: src_ip → ["src", "ip"]
    3. 驼峰拆分（递归应用到每个子部分）: srcIp → ["src", "Ip"]

    Returns:
        包含原字段 + 所有拆分后子部分的列表（去重保序）
    """
    parts: list[str] = [raw_field]

    # 1. 点号拆分（嵌套字段 a.b.c）
    if "." in raw_field:
        parts.extend(raw_field.split("."))

    # 2. 下划线拆分（snake_case）
    if "_" in raw_field:
        parts.extend(raw_field.split("_"))

    # 3. 驼峰拆分（对每个已有部分递归拆分）
    camel_parts: list[str] = []
    for p in list(parts):  # 复制一份避免遍历时修改
        camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", p)
        if "_" in camel_split and camel_split != p:
            camel_parts.extend(camel_split.split("_"))
    parts.extend(camel_parts)

    # 去重保序，过滤空串
    seen: set[str] = set()
    result: list[str] = []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            result.append(p)

    return result


# ===== Synonyms 缓存（惰性加载） =====
_synonyms_cache: Optional[dict[str, list[str]]] = None


def _load_synonyms() -> dict[str, list[str]]:
    """从 config/field_synonyms.json 加载缩写→中文映射表（惰性加载，带缓存）。

    Returns:
        {"src": ["源", "source"], "dst": ["目的", "destination"], ...}
    """
    global _synonyms_cache
    if _synonyms_cache is not None:
        return _synonyms_cache

    synonyms_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config", "field_synonyms.json"
    )
    try:
        if os.path.exists(synonyms_path):
            with open(synonyms_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _synonyms_cache = data
            logger.info(f"[SYNONYMS] 加载缩写映射表：{len(data)} 条（已缓存）")
            return _synonyms_cache
    except Exception as e:
        logger.warning(f"[SYNONYMS] 加载缩写映射表失败: {e}")
    _synonyms_cache = {}
    return _synonyms_cache


def query_field_candidates(
    raw_field: str,
    fields_table: list[dict[str, Any]],
    top_k: int = 3,
    min_score: float = 0.15,
) -> list[tuple[float, str]]:
    """统一候选查询入口（封装拆分 + synonyms + 相似度匹配）。

    优化层：
    - Layer 1: 复合词自动拆分（_split_compound_field）
    - Layer 2: 缩写→中文扩展（field_synonyms.json）
    - Layer 3: 多维度相似度计算（字段名 / 系统属性名 / 描述）

    Args:
        raw_field: 原始字段名（如 "src_ip", "detail.srcPort"）
        fields_table: 标准字段表（_load_standard_fields_list() 的返回值）
        top_k: 返回 top-K 候选
        min_score: 最低相似度阈值

    Returns:
        [(score, 系统属性名称), ...] 按 score 降序，去重
    """
    # Layer 1: 复合词拆分
    parts = _split_compound_field(raw_field)

    # Layer 2: 缩写扩展
    synonyms = _load_synonyms()
    expanded_parts: list[str] = list(parts)
    for part in parts:
        part_lower = part.lower()
        if part_lower in synonyms:
            expanded_parts.extend(synonyms[part_lower])

    # 对每个扩展后的部分 + 原字段，分别计算相似度
    scored: list[tuple[float, str]] = []
    for entry in fields_table:
        system_name = entry.get("系统属性名称", "")
        eng_name = entry.get("字段名称", "")
        desc = entry.get("描述", "")

        # === 策略 A：原字段完整匹配 ===
        best_score = max(
            _calculate_similarity(raw_field, eng_name),
            _calculate_similarity(raw_field, system_name) * 0.85,
            _calculate_similarity(raw_field, desc) * 0.6,
        )

        # === 策略 B：拆分后子部分逐个匹配 ===
        for part in expanded_parts:
            if part == raw_field:
                continue

            part_lower = part.lower()
            eng_score = _calculate_similarity(part_lower, eng_name.lower())
            is_chinese = any('\u4e00' <= c <= '\u9fff' for c in part)
            if is_chinese:
                cn_score = max(
                    _calculate_similarity(part, system_name),
                    _calculate_similarity(part, desc) * 0.8,
                )
                part_score = max(eng_score, cn_score) * 0.88
            else:
                part_score = max(
                    eng_score,
                    _calculate_similarity(part_lower, system_name.lower()) * 0.7,
                    _calculate_similarity(part_lower, desc.lower()) * 0.5,
                ) * 0.75

            best_score = max(best_score, part_score)

        # === 策略 C：双向 part-to-part 共现加分 ===
        # 拆分标准字段英文名，与输入字段拆分部分做 part-to-part 精确匹配
        eng_parts = _split_compound_field(eng_name)
        input_parts_lower = {p.lower() for p in expanded_parts if p != raw_field and not any('\u4e00' <= c <= '\u9fff' for c in p)}

        if eng_parts and input_parts_lower:
            eng_lower = {p.lower() for p in eng_parts if p.lower() != eng_name.lower()}
            # 精确匹配的 part 数量
            matched_parts = input_parts_lower & eng_lower
            if matched_parts:
                # 匹配率 = 匹配的 part 数 / 输入拆分后的总 part 数
                coverage = len(matched_parts) / max(len(input_parts_lower), 1)
                # 共现加分：匹配的 part 越多、覆盖率越高，加分越大
                # 最多 0.92（不超过完整匹配的 1.0）
                cooccurrence_bonus = 0.65 + 0.27 * coverage
                best_score = max(best_score, cooccurrence_bonus)

        if best_score > min_score:
            scored.append((best_score, system_name))

    scored.sort(key=lambda x: x[0], reverse=True)

    # 去重（按系统属性名称，保留最高分）
    seen: set[str] = set()
    result: list[tuple[float, str]] = []
    for score, name in scored:
        if name not in seen:
            seen.add(name)
            result.append((score, name))
        if len(result) >= top_k:
            break

    return result


def _calculate_similarity(a: str, b: str) -> float:
    """Simple normalized Levenshtein similarity (0.0 - 1.0, higher = more similar)"""
    a_lower = a.lower()
    b_lower = b.lower()
    
    # Direct exact match
    if a_lower == b_lower:
        return 1.0

    # Containment with length-ratio penalty:
    # "src_ip" in "src_ip_list" → ratio=0.5 → 0.70 (penalized)
    # "源地址" in "源地址" → exact → 1.0 (handled above)
    if a_lower in b_lower or b_lower in a_lower:
        shorter_len = min(len(a_lower), len(b_lower))
        longer_len = max(len(a_lower), len(b_lower))
        ratio = shorter_len / longer_len
        return max(0.40, 0.40 + 0.55 * ratio)
    
    # Levenshtein distance
    len_a, len_b = len(a_lower), len(b_lower)
    if len_a == 0 or len_b == 0:
        return 0.0
    
    # Use two-row DP for efficiency
    prev = list(range(len_b + 1))
    curr = [0] * (len_b + 1)
    
    for i in range(1, len_a + 1):
        curr[0] = i
        for j in range(1, len_b + 1):
            cost = 0 if a_lower[i - 1] == b_lower[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev, curr = curr, prev
    
    distance = prev[len_b]
    max_len = max(len_a, len_b)
    return 1.0 - (distance / max_len)


@tool(name="lookup_standard_field", description="Query standard field table by field name keyword, returns top matching system property names")
def lookup_standard_field_tool(keyword: str, limit: int = 5) -> str:
    """
    Query the standard field table for matching system property names.
    
    Use this tool when you need to find standard field mappings for a given
    original field name (e.g., "srcip", "dstport", "eventType").
    Returns top candidates sorted by similarity score.
    
    Args:
        keyword: The original field name to look up (e.g., "srcip", "dstport")
        limit: Maximum number of candidates to return (default: 5)
    
    Returns:
        JSON array of matching candidates with system property name, description, and object
    """
    try:
        fields = _load_standard_fields_list()
        if not fields:
            return json.dumps({"status": "error", "message": "Standard field table is empty"}, ensure_ascii=False)
        
        # Score each field entry against the keyword
        scored = []
        for entry in fields:
            system_name = entry.get("系统属性名称", "")
            field_name = entry.get("字段名称", "")  # English field name (e.g., src_address)
            description = entry.get("描述", "")
            obj = entry.get("对象", "")
            
            # Primary score: match against English field name (most precise)
            field_name_score = _calculate_similarity(keyword, field_name)
            # Secondary score: match against Chinese system name
            name_score = _calculate_similarity(keyword, system_name) * 0.85
            # Tertiary score: match against description
            desc_score = _calculate_similarity(keyword, description) * 0.6
            # Best score wins
            score = max(field_name_score, name_score, desc_score)
            
            if score > 0.15:  # Minimum threshold
                scored.append((score, {
                    "系统属性名称": system_name,
                    "字段名称": field_name,
                    "描述": description,
                    "对象": obj,
                    "相似度": round(score, 3)
                }))
        
        # Sort by similarity descending, deduplicate by system_name
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # Deduplicate: keep highest score for each system_name
        seen_system_names = set()
        deduped = []
        for score, item in scored:
            name = item.get("系统属性名称", "")
            if name not in seen_system_names:
                seen_system_names.add(name)
                deduped.append((score, item))
        
        # Return top-N
        candidates = [item for _, item in deduped[:limit]]
        return json.dumps(candidates, ensure_ascii=False, indent=2)
    
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error_message": f"Standard field lookup failed: {str(e)}"
        }, ensure_ascii=False)


def _load_object_mapping(excel_path: str) -> dict:
    """读取 Excel 模板的"对应关系"Sheet，只取第一个对象"""
    mapping = {}
    try:
        wb = load_workbook(excel_path, data_only=True)
        if "对应关系" in wb.sheetnames:
            ws = wb["对应关系"]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if len(row) >= 3 and row[0] and row[2]:
                    system_property = str(row[0]).strip()
                    obj = str(row[2]).strip()
                    # 🔧 修复：只取第一个对象（逗号分隔）
                    obj = obj.split(',')[0].strip()
                    mapping[system_property] = obj
    except Exception:
        pass
    return mapping


def _apply_field_mapping(json_obj: dict, field_mapping: dict, field_to_object: dict = None) -> dict:
    """应用字段映射到 JSON 对象"""
    result = json_obj.copy()
    
    def traverse(obj, path=""):
        if isinstance(obj, dict):
            if "normalize" in obj and isinstance(obj["normalize"], list):
                for item in obj["normalize"]:
                    if isinstance(item, dict):
                        original_index = str(item.get("index", "") or "").strip().lower()
                        result_values = item.get("result", [])
                        if isinstance(result_values, list):
                            result_values_lower = [str(v).strip().lower() for v in result_values if v is not None]
                        else:
                            result_values_lower = [str(result_values).strip().lower()]
                        
                        matched = False
                        for original_field, mapped_field in field_mapping.items():
                            original_lower = str(original_field).strip().lower()
                            
                            if (original_lower == original_index or 
                                original_lower in original_index or
                                original_lower in result_values_lower):
                                
                                final_field = mapped_field
                                entity = "事件"
                                
                                if field_to_object and final_field in field_to_object:
                                    entity = field_to_object[final_field]
                                
                                item["field"] = final_field
                                item["entity"] = entity
                                item["core"] = False
                                item["sim"] = True
                                matched = True
                                break
                        
                        if not matched and original_index in field_mapping:
                            mapped_field = field_mapping[original_index]
                            final_field = mapped_field
                            entity = "事件"
                            
                            if field_to_object and final_field in field_to_object:
                                entity = field_to_object[final_field]
                            
                            item["field"] = final_field
                            item["entity"] = entity
                            item["core"] = False
                            item["sim"] = True
            
            for key, value in obj.items():
                if key != "normalize":
                    traverse(value, f"{path}.{key}" if path else key)
                    
        elif isinstance(obj, list):
            for item in obj:
                traverse(item, path)
    
    traverse(result)
    return result


def _manage_sim_entities(json_obj: dict, field_to_object: dict) -> list:
    """管理 simEntities 数组"""
    entities_added = []
    objects_needed = set(field_to_object.values())
    
    def find_or_create_sim_entities(obj):
        nonlocal entities_added
        
        if isinstance(obj, dict):
            if "simEntities" in obj and isinstance(obj["simEntities"], list):
                sim_entities = obj["simEntities"]
                existing_objects = {e.get("object") for e in sim_entities if isinstance(e, dict)}
                
                for obj_type in objects_needed:
                    if obj_type not in existing_objects:
                        new_entity = {
                            "object": obj_type,
                            "fields": []
                        }
                        sim_entities.append(new_entity)
                        entities_added.append(obj_type)
            
            for value in obj.values():
                find_or_create_sim_entities(value)
                
        elif isinstance(obj, list):
            for item in obj:
                find_or_create_sim_entities(item)
    
    find_or_create_sim_entities(json_obj)
    return entities_added
