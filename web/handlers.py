"""
业务处理器模块 - 处理标准字段和威胁类型映射
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import streamlit as st
from agent.agent import simple_decode, simple_encode, create_agent
from agent.tools.standard_mapper import apply_mapping_to_json
from agent.tools.threat_type_tool import (
    apply_threat_type_mapping,
    load_threat_types_from_config,
    extract_threat_values
)
from agent.tools.enum_field_tool import (
    decode_enum_config,
    load_mapping_from_excel,
    apply_enum_mapping
)
from agent.tools.extract_field_tool import (
    extract_field_values,
    generate_mapping_table,
    save_mapping_to_excel
)
from web.parsers import parse_markdown_to_dataframe, parse_threat_markdown_to_dataframe
from web.utils import log_info, log_error


# ============= 字段提取前置处理 =============

def process_log_upload(uploaded_log) -> dict:
    """
    处理日志文件上传
    
    Args:
        uploaded_log: Streamlit 上传的文件对象
        
    Returns:
        dict: {
            "status": "success" | "error",
            "message": str,
            "log_content": str,
            "log_name": str
        }
    """
    try:
        # 尝试多种编码
        log_content = None
        for encoding in ("utf-8-sig", "utf-8", "gbk", "cp936", "latin-1"):
            try:
                log_content = uploaded_log.read().decode(encoding)
                break
            except (UnicodeDecodeError, AttributeError):
                uploaded_log.seek(0)
                continue
        
        if log_content is None:
            log_content = uploaded_log.read().decode("utf-8", errors="ignore")
        
        log_info(f"日志文件上传成功: {uploaded_log.name}, 大小: {len(log_content)} 字符")
        
        return {
            "status": "success",
            "message": f"✅ 已上传日志：{uploaded_log.name}",
            "log_content": log_content,
            "log_name": uploaded_log.name
        }
    except Exception as e:
        log_error(f"日志文件处理失败: {str(e)}")
        return {
            "status": "error",
            "message": f"❌ 处理日志文件失败: {str(e)}",
            "log_content": None,
            "log_name": None
        }


def extract_log_field(log_content: str, field_key: str, pattern: str = None) -> dict:
    """
    从日志内容提取字段值
    
    Args:
        log_content: 日志内容
        field_key: 字段名
        pattern: 正则表达式（可选）
        
    Returns:
        dict: {
            "status": "success" | "error",
            "extract_result": dict,
            "mapping_table": list[dict]
        }
    """
    try:
        result = extract_field_values(log_content, field_key, pattern)
        
        if result["status"] == "success":
            mapping_table = generate_mapping_table(
                field_key,
                result["unique_values"],
                "EQUAL"
            )
            return {
                "status": "success",
                "extract_result": result,
                "mapping_table": mapping_table
            }
        else:
            return {
                "status": "error",
                "message": result.get("error_message", "提取失败")
            }
    except Exception as e:
        log_error(f"字段提取失败: {str(e)}")
        return {
            "status": "error",
            "message": f"❌ 字段提取失败: {str(e)}"
        }


# ============= 标准字段处理 =============

def process_standard_field(b64_content: str) -> dict:
    """处理标准字段映射 - 使用 Agent 和提示词"""
    try:
        log_info("开始处理标准字段...")
        
        result = simple_decode(b64_content)
        if result["status"] == "success":
            st.session_state.decoded_data = result["decoded_json"]
            st.session_state.fields = result["fields"]
            st.session_state.original_log = result["original_log"]
            
            log_info(f"解码成功，提取到 {len(st.session_state.fields)} 个字段")
            
            if st.session_state.api_key_configured:
                agent = create_agent(user_id="streamlit_user")
                
                fields_str = ", ".join(st.session_state.fields) if st.session_state.fields else "无"
                decoded_json_str = json.dumps(st.session_state.decoded_data, ensure_ascii=False, indent=2)
                
                # 构建提示词，让 Agent 输出 Markdown 表格
                prompt = f"""根据以下信息完成字段映射：

**原始日志 JSON：**
```json
{decoded_json_str}
```

**提取的字段列表：**
{fields_str}

请严格按照 field_weak.md 提示词的要求，输出标准字段映射表（Markdown 格式）。
只输出映射表，不输出解释、分析或备注。"""
                
                response = agent.run(prompt)
                log_info(f"Agent 返回结果: {response.content[:1000]}...")
                
                # 解析 Agent 返回的 Markdown 表格
                st.session_state.mapping_df = parse_markdown_to_dataframe(response.content)
                
                log_info(f"解析后 DataFrame 列: {list(st.session_state.mapping_df.columns)}")
                log_info(f"解析后 DataFrame 行数: {len(st.session_state.mapping_df)}")
                if len(st.session_state.mapping_df) > 0:
                    log_info(f"第一行数据: {st.session_state.mapping_df.iloc[0].to_dict()}")
                
                if len(st.session_state.mapping_df) > 0:
                    return {
                        "status": "success",
                        "message": f"✅ 已生成映射表，共 {len(st.session_state.mapping_df)} 个字段。\n\n请在下方编辑映射表，或告诉我修改意见，例如：'将 xxx 改为 yyy'，然后告诉我'确认映射'来完成处理。"
                    }
                else:
                    return {
                        "status": "error",
                        "message": "❌ Agent 返回的映射表格式不正确，请重试。"
                    }
            else:
                return {
                    "status": "warning",
                    "message": "⚠️ API Key 未配置，无法使用 AI 生成映射表。"
                }
        else:
            return {
                "status": "error",
                "message": f"❌ 解码失败: {result.get('error_message', '未知错误')}"
            }
    except Exception as e:
        log_error(f"处理失败: {str(e)}")
        return {
            "status": "error",
            "message": f"❌ 处理失败: {str(e)}"
        }


def confirm_standard_mapping() -> dict:
    """确认标准字段映射并输出结果"""
    try:
        if st.session_state.mapping_df is None:
            return {"status": "error", "message": "❌ 没有可确认的映射表"}
        
        # 应用映射
        mappings = []
        for _, row in st.session_state.mapping_df.iterrows():
            original = row["原始字段名"]
            mapped = row["系统属性名称"]
            status = row["匹配状态/说明"]
            
            if original and mapped and "未匹配" not in str(status):
                mappings.append({
                    "原始字段名": original,
                    "系统属性名称": mapped
                })
        
        if mappings:
            st.session_state.processed_data = apply_mapping_to_json(
                st.session_state.decoded_data,
                mappings
            )
        
        # 编码输出
        result = simple_encode(st.session_state.processed_data or st.session_state.decoded_data)
        if result["status"] == "success":
            st.session_state.final_result = result["base64_encoded"]
            st.session_state.mapping_confirmed = True
            
            return {
                "status": "success",
                "message": f"✅ 映射完成！\n\n**输出长度：** {len(st.session_state.final_result)} 字符\n\n点击下方按钮下载结果。"
            }
        else:
            return {
                "status": "error",
                "message": f"❌ 编码失败: {result.get('error_message')}"
            }
    except Exception as e:
        log_error(f"确认映射失败: {str(e)}")
        return {"status": "error", "message": f"❌ 处理失败: {str(e)}"}


# ============= 威胁类型处理 =============

def apply_threat_mapping_to_json(json_obj: dict, mapping_table: list, target_field: str) -> dict:
    """
    将威胁类型映射应用到 JSON 对象的指定字段
    
    Args:
        json_obj: 解码后的 JSON 对象
        mapping_table: 映射表
        target_field: 目标字段名（如 threat_type、alertType 等）
        
    Returns:
        dict: 修改后的 JSON 对象
    """
    result = json_obj.copy()
    
    # 构建映射索引：orgValue -> mappingValue
    mapping_dict = {}
    for item in mapping_table:
        org_value = item.get("orgValue", "")
        mapping_value = item.get("mappingValue", "")
        if org_value and mapping_value:
            mapping_dict[org_value] = mapping_value
    
    if not mapping_dict:
        log_info("[WARNING] 映射表为空，无需处理")
        return result
    
    def traverse(obj, path=""):
        if isinstance(obj, dict):
            # 检查是否包含目标字段
            if target_field in obj and obj[target_field]:
                original_value = str(obj[target_field])
                
                # 精确匹配
                if original_value in mapping_dict:
                    obj[target_field] = mapping_dict[original_value]
                    log_info(f"威胁类型映射(精确): {original_value} -> {mapping_dict[original_value]}")
                    return
                
                # 模糊匹配
                for org_value, mapped_value in mapping_dict.items():
                    # 移除 .* 包裹，提取核心内容进行匹配
                    core_org = org_value
                    if core_org.startswith(".*"):
                        core_org = core_org[2:]
                    if core_org.endswith(".*"):
                        core_org = core_org[:-2]
                    
                    if core_org and (core_org in original_value or original_value in core_org):
                        obj[target_field] = mapped_value
                        log_info(f"威胁类型映射(模糊): {original_value} -> {mapped_value}")
                        return
            
            # 继续遍历
            for key, value in obj.items():
                traverse(value, f"{path}.{key}" if path else key)
                
        elif isinstance(obj, list):
            for item in obj:
                traverse(item, path)
    
    traverse(result)
    return result


def process_threat_type(b64_content: str) -> dict:
    """处理威胁类型（通过文件上传）- 使用 Agent 生成映射表"""
    try:
        log_info("开始处理威胁类型（文件模式）...")
        
        result = simple_decode(b64_content)
        if result["status"] == "success":
            st.session_state.threat_decoded_data = result["decoded_json"]
            
            # 提取威胁类型值
            threat_values = extract_threat_values(result["decoded_json"])
            all_threat_types = load_threat_types_from_config()
            
            if not threat_values:
                return {
                    "status": "error",
                    "message": "❌ 未从数据中提取到威胁类型值"
                }
            
            # 使用 Agent 生成映射表
            if st.session_state.api_key_configured:
                agent = create_agent(user_id="streamlit_user")
                
                prompt = f"""根据以下威胁类型值，生成标准化的威胁类型映射表：

**从数据中提取的威胁类型：**
{', '.join(threat_values)}

**可用标准威胁类型列表：**
{', '.join(all_threat_types)}

请根据以下规则生成映射表：
1. 分析每个威胁类型值
2. 从标准列表中找到最匹配的威胁类型
3. 输出 Markdown 格式的映射表，包含以下列：
   - 原始威胁类型
   - mappingType（固定为 REGULAR）
   - orgValue（格式为 .*原始值.*）
   - mappingValue（标准化的威胁类型名称）
   - 匹配状态（已匹配/未匹配）

只输出映射表，不输出解释、分析或备注。"""
                
                response = agent.run(prompt)
                log_info(f"Agent 返回结果: {response.content[:1000]}...")
                
                # 解析 Agent 返回的 Markdown 表格
                threat_df = parse_threat_markdown_to_dataframe(response.content)
                
                if threat_df is not None and len(threat_df) > 0:
                    st.session_state.threat_mapping_df = threat_df
                    st.session_state.threat_types_list = all_threat_types
                    
                    return {
                        "status": "success",
                        "message": f"✅ 已生成威胁类型映射表，共 {len(threat_df)} 个映射。\n\n请在下方编辑映射表。\n\n**请告诉我您要将这些映射填充到哪个字段？**\n\n然后告诉我'确认映射'来完成处理并输出结果。"
                    }
                else:
                    return {
                        "status": "error",
                        "message": "❌ Agent 返回的映射表格式不正确，请重试。"
                    }
            else:
                return {
                    "status": "warning",
                    "message": "⚠️ API Key 未配置，无法使用 AI 生成映射表。"
                }
        else:
            return {
                "status": "error",
                "message": f"❌ 解码失败: {result.get('error_message', '未知错误')}"
            }
    except Exception as e:
        log_error(f"处理失败: {str(e)}")
        return {
            "status": "error",
            "message": f"❌ 处理失败: {str(e)}"
        }


def find_normalize_item(decoded_data, user_input: str) -> tuple:
    """
    从 decoded_data 的 normalize 数组中查找匹配的项
    
    Args:
        decoded_data: 解码后的 JSON 对象（可能是列表或字典）
        user_input: 用户输入的目标字段（如 "original_log"、"threat_type"）
    
    Returns:
        tuple: (matched_item, available_fields) 
               - matched_item: 找到的 normalize 项，未找到则为 None
               - available_fields: 所有可用的 index/result 值列表
    """
    # 处理 decoded_data 可能是列表的情况
    if isinstance(decoded_data, list):
        # 如果是列表，取第一个元素（通常是配置对象）
        if len(decoded_data) > 0:
            decoded_data = decoded_data[0]
        else:
            return None, []
    
    if not isinstance(decoded_data, dict):
        return None, []
    
    normalize = decoded_data.get("normalize", [])
    available_fields = []
    matched_item = None
    
    for item in normalize:
        if not isinstance(item, dict):
            continue
        index_value = item.get("index", "")
        result = item.get("result", [])
        field_value = item.get("field", "")
        
        # 收集所有可用的 index 和 result 值
        if index_value:
            available_fields.append(index_value)
        if isinstance(result, list):
            available_fields.extend(result)
        if field_value:
            available_fields.append(field_value)
        
        # 检查是否匹配用户输入
        # 移除可能的引号进行比较
        clean_input = user_input.strip('"\'')
        clean_index = index_value.strip('"\'')
        
        if clean_input == clean_index:
            matched_item = item
            break
        elif clean_input in result:
            matched_item = item
            break
        elif clean_input == field_value:
            matched_item = item
            break
    
    return matched_item, available_fields


def extract_target_field(prompt: str) -> tuple:
    """
    从用户输入中提取目标字段名，并在 normalize 中验证
    
    Returns:
        tuple: (field_name, error_message)
               - field_name: 找到的字段名，未找到则为 None
               - error_message: 错误信息，未出错则为 None
    """
    import re
    
    # 提取可能的字段名
    field_candidates = []
    
    # 提取引号内的内容（优先）
    quoted_matches = re.findall(r'["\']([^"\']+)["\']', prompt)
    if quoted_matches:
        field_candidates.extend(quoted_matches)
    
    # 提取"填充到xxx"中的xxx
    fill_match = re.search(r'填充到\s*(\S+)', prompt)
    if fill_match:
        field_candidates.append(fill_match.group(1))
    
    # 在 decoded_data 的 normalize 中验证
    if st.session_state.threat_decoded_data:
        for candidate in field_candidates:
            matched_item, available_fields = find_normalize_item(
                st.session_state.threat_decoded_data, candidate
            )
            if matched_item:
                # 保存匹配的 normalize 项供后续使用
                st.session_state.threat_matched_normalize = matched_item
                return candidate, None
        
        # 没有找到匹配，返回可用字段列表
        if field_candidates:
            _, available_fields = find_normalize_item(
                st.session_state.threat_decoded_data, field_candidates[0]
            )
            available_str = ", ".join(set(available_fields[:20]))  # 最多显示20个
            return None, f"❌ 未找到匹配的 normalize 项！\n\n您输入的字段：{field_candidates[0]}\n\n可用的字段列表：\n{available_str}\n\n请从上述列表中选择正确的字段名。"
    
    return None, "❌ 无法验证字段，数据未加载"


def process_threat_type_by_input(b64_content: str, threat_text: str) -> dict:
    """根据用户输入的威胁类型生成映射表"""
    try:
        log_info(f"根据用户输入的威胁类型生成映射表: {threat_text}")
        
        # 解码 Base64 文件
        result = simple_decode(b64_content)
        if result["status"] != "success":
            return {"status": "error", "message": f"❌ 解码失败: {result.get('error_message', '未知错误')}"}
        
        st.session_state.threat_decoded_data = result["decoded_json"]
        
        # 加载标准威胁类型列表
        all_threat_types = load_threat_types_from_config()
        
        # 使用 Agent 根据用户输入生成映射表
        if st.session_state.api_key_configured:
            agent = create_agent(user_id="streamlit_user")
            
            # 加载提示词文件
            prompt_file = Path(__file__).parent.parent / "agent" / "prompts" / "threat_type.md"
            if prompt_file.exists():
                base_prompt = prompt_file.read_text(encoding='utf-8')
            else:
                base_prompt = ""
            
            prompt = f"""{base_prompt}

## Input Data
**用户输入的威胁类型：**
{threat_text}

**可用标准威胁类型列表：**
{', '.join(all_threat_types)}
"""
            
            response = agent.run(prompt)
            log_info(f"Agent 返回结果: {response.content[:1000]}...")
            
            # 解析 Agent 返回的 Markdown 表格
            threat_df = parse_threat_markdown_to_dataframe(response.content)
            
            if threat_df is not None and len(threat_df) > 0:
                st.session_state.threat_mapping_df = threat_df
                st.session_state.threat_types_list = all_threat_types
                
                return {
                    "status": "success",
                    "message": f"✅ 已根据您输入的威胁类型生成映射表，共 {len(threat_df)} 个映射。\n\n请在下方编辑映射表，确认无误后：\n1. 告诉我**填充到哪个字段**\n2. 然后告诉我**'确认映射'**来完成处理并输出结果。"
                }
            else:
                return {
                    "status": "error",
                    "message": "❌ Agent 返回的映射表格式不正确，请重试。"
                }
        else:
            return {
                "status": "warning",
                "message": "⚠️ API Key 未配置，无法使用 AI 生成映射表。"
            }
    except Exception as e:
        log_error(f"处理失败: {str(e)}")
        return {
            "status": "error",
            "message": f"❌ 处理失败: {str(e)}"
        }


def confirm_threat_mapping(target_field: str = None) -> dict:
    """
    确认威胁类型映射并应用到数据
    
    正确的填充逻辑（参考 feature5_mappingall.py）：
    1. 从 decoded_data 的 normalize 数组中找到匹配的项
    2. 把 mapping 表格添加到该 normalize 项的 'mappings' 字段中
    3. 如果找不到匹配的 normalize 项，返回错误
    """
    try:
        if st.session_state.threat_mapping_df is None:
            return {"status": "error", "message": "❌ 没有可确认的映射表"}
        
        # 获取目标字段
        field = target_field or st.session_state.threat_target_field
        
        # 检查是否已指定目标字段
        if not field:
            return {
                "status": "warning", 
                "message": "⚠️ 请先告诉我您要把映射填充到哪个字段！\n\n请使用引号包裹字段名，例如：\n填充到 \"xxx\""
            }
        
        # 检查是否有解码后的数据
        if st.session_state.threat_decoded_data is None:
            return {"status": "error", "message": "❌ 没有可处理的 Base64 数据"}
        
        # 在 normalize 数组中找到匹配的项
        matched_item = st.session_state.get("threat_matched_normalize")
        if not matched_item:
            # 尝试在 normalize 中查找
            matched_item, available_fields = find_normalize_item(
                st.session_state.threat_decoded_data, field
            )
            if not matched_item:
                available_str = ", ".join(set(available_fields[:20]))
                return {
                    "status": "error",
                    "message": f"❌ 未找到匹配的 normalize 项！\n\n您输入的字段：{field}\n\n可用的字段列表：\n{available_str}\n\n请从上述列表中选择正确的字段名。"
                }
        
        # 构建映射表（三列格式：mappingType, orgValue, mappingValue）
        mapping_table = []
        for _, row in st.session_state.threat_mapping_df.iterrows():
            mapping_type = row.get("mappingType", "REGULAR")
            org_value = row.get("orgValue", "")
            mapping_value = row.get("mappingValue", "")
            if mapping_type and org_value and mapping_value:
                mapping_table.append({
                    "mappingType": mapping_type,
                    "orgValue": org_value,
                    "mappingValue": mapping_value
                })
        
        if not mapping_table:
            return {"status": "error", "message": "❌ 映射表为空"}
        
        # 初始化 mappings 字段（如果不存在）
        if "mappings" not in matched_item:
            matched_item["mappings"] = []
        
        # 将 mapping 添加到 matched_item 的 mappings 字段中
        mappings_added = 0
        for mapping in mapping_table:
            # 检查是否已存在相同的 orgValue
            exists = any(
                m.get("orgValue") == mapping["orgValue"] 
                for m in matched_item["mappings"]
            )
            if not exists:
                matched_item["mappings"].append(mapping)
                mappings_added += 1
                log_info(f"添加映射: {mapping['mappingType']} | {mapping['orgValue']} -> {mapping['mappingValue']}")
        
        log_info(f"共添加 {mappings_added} 条映射到 normalize 项 (index={matched_item.get('index')}, field={matched_item.get('field')})")
        
        # 编码输出
        result = simple_encode(st.session_state.threat_decoded_data)
        if result["status"] == "success":
            st.session_state.threat_final_result = result["base64_encoded"]
            st.session_state.threat_confirmed = True
            
            return {
                "status": "success",
                "message": f"✅ 威胁类型映射完成！\n\n**目标 normalize 项：**\n- index: {matched_item.get('index')}\n- field: {matched_item.get('field')}\n\n**已添加 {mappings_added} 条映射到 mappings 字段**\n\n**输出长度：** {len(st.session_state.threat_final_result)} 字符\n\n点击下方按钮下载处理结果。"
            }
        else:
            return {
                "status": "error",
                "message": f"❌ 编码失败: {result.get('error_message')}"
            }
    except Exception as e:
        log_error(f"确认映射失败: {str(e)}")
        return {"status": "error", "message": f"❌ 处理失败: {str(e)}"}


# ============= 普通字段枚举批量处理 =============

def process_enum_field(b64_content: str, excel_file) -> dict:
    """
    处理普通字段枚举批量处理
    逻辑：上传 Base64 配置 + 映射表Excel → 用户确认 → 执行映射 → 输出 Base64 加密 txt
    """
    try:
        log_info("开始处理枚举字段...")
        
        # 1. 解码 Base64 配置
        decode_result = decode_enum_config(b64_content)
        if decode_result["status"] != "success":
            return {"status": "error", "message": f"❌ 解码失败: {decode_result.get('error_message', '未知错误')}"}
        
        st.session_state.enum_decoded_data = decode_result["decoded_json"]
        st.session_state.enum_fields = decode_result["normalize_fields"]
        st.session_state.enum_field_count = decode_result.get("field_count", 0)
        
        # 2. 加载 Excel 映射表
        if excel_file is None:
            return {"status": "error", "message": "❌ 请先上传映射表 Excel 文件（通过侧边栏上传）"}
        
        # 保存 Excel 文件到临时路径
        import tempfile
        import os as os_module
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(excel_file.getvalue())
            tmp_path = tmp.name
        
        try:
            mapping_table = load_mapping_from_excel(tmp_path)
        finally:
            os_module.unlink(tmp_path)
        
        if not mapping_table:
            return {"status": "error", "message": "❌ 映射表为空或格式不正确"}
        
        st.session_state.enum_mapping_table = mapping_table
        
        # 3. 按字段分组统计映射数量
        field_stats = {}
        for item in mapping_table:
            field = item.get("field", "未知")
            if field not in field_stats:
                field_stats[field] = 0
            field_stats[field] += 1
        
        stats_lines = ["**映射表摘要：**", ""]
        for field, count in sorted(field_stats.items()):
            stats_lines.append(f"- **{field}**：{count} 条映射")
        
        stats_text = "\n".join(stats_lines)
        
        return {
            "status": "success",
            "message": f"""✅ 已解码配置文件并加载映射表

**配置文件信息：**
- normalize 字段数量：{st.session_state.enum_field_count}

{stats_text}

**下一步：** 请确认是否执行映射？告诉我"确认映射"来完成处理。"""
        }
        
    except Exception as e:
        log_error(f"枚举字段处理失败: {str(e)}")
        return {"status": "error", "message": f"❌ 处理失败: {str(e)}"}


def confirm_enum_mapping(mapping_table: list = None) -> dict:
    """
    确认枚举字段映射并输出结果
    
    Args:
        mapping_table: 可选，传入映射表。如果为None，则使用session_state中的enum_mapping_table
    """
    try:
        # 获取映射表
        if mapping_table is None:
            mapping_table = st.session_state.get("enum_mapping_table")
        
        if mapping_table is None:
            return {"status": "error", "message": "❌ 没有可用的映射表"}
        
        # 解码 Base64
        if st.session_state.enum_decoded_data is None:
            if st.session_state.pending_file is None:
                return {"status": "error", "message": "❌ 没有可处理的配置数据"}
            
            decode_result = decode_enum_config(st.session_state.pending_file)
            if decode_result["status"] != "success":
                return {"status": "error", "message": f"❌ 解码失败: {decode_result.get('error_message', '未知错误')}"}
            
            st.session_state.enum_decoded_data = decode_result["decoded_json"]
        
        decoded_json = st.session_state.enum_decoded_data
        
        # 应用映射
        processed_json = apply_enum_mapping(decoded_json, mapping_table)
        
        # 编码输出
        result = simple_encode(processed_json)
        if result["status"] == "success":
            st.session_state.enum_final_result = result["base64_encoded"]
            st.session_state.enum_confirmed = True
            st.session_state.enum_mapping_table = mapping_table
            
            return {
                "status": "success",
                "message": f"""✅ 枚举字段映射完成！

**已应用 {len(mapping_table)} 条映射规则**

**输出长度：** {len(st.session_state.enum_final_result)} 字符

点击下方按钮下载处理结果。"""
            }
        else:
            return {"status": "error", "message": f"❌ 编码失败: {result.get('error_message')}"}
            
    except Exception as e:
        log_error(f"确认枚举映射失败: {str(e)}")
        return {"status": "error", "message": f"❌ 处理失败: {str(e)}"}


# ============= 消息处理 =============

def add_message(role: str, content: str):
    """添加消息到历史"""
    st.session_state.messages.append({"role": role, "content": content})


def display_chat_history():
    """显示聊天历史"""
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def get_mode_name(mode: str) -> str:
    """获取模式名称"""
    names = {
        "standard_field": "标准字段处理",
        "enum_field": "枚举字段处理",
        "threat_type": "威胁类型处理"
    }
    return names.get(mode, mode)


def get_help_message() -> str:
    """获取帮助信息"""
    return """
👋 **使用指南**

**操作很简单：**

1. 上传配置文件
2. 点击对应的处理按钮
3. 确认映射
4. 下载结果

**三种处理模式：**

📋 **标准字段** - 字段名标准化

⚠️ **威胁类型** - 输入威胁类型，自动生成映射

📝 **枚举字段** - 填写/上传映射表

**界面按钮已经包含所有操作，无需输入文字！**
"""


def handle_user_message(prompt: str) -> str:
    """处理用户消息"""
    prompt_lower = prompt.lower()
    has_file = st.session_state.pending_file is not None
    
    # 模式检测
    if st.session_state.current_mode is None:
        if "标准字段" in prompt or "字段映射" in prompt or "标准字段处理" in prompt_lower:
            st.session_state.current_mode = "standard_field"
            return "好的，我将帮助您处理标准字段映射。📁 请上传 Base64 编码的配置文件（通过侧边栏上传），然后告诉我'开始处理'。"
        
        elif "枚举" in prompt or "枚举字段" in prompt_lower:
            st.session_state.current_mode = "enum_field"
            return "好的，我将帮助您处理枚举字段。📁 请上传包含枚举值的配置文件（通过侧边栏上传），然后告诉我'开始处理'。"
        
        elif "威胁类型" in prompt or "威胁" in prompt_lower:
            st.session_state.current_mode = "threat_type"
            return "好的，我将帮助您处理威胁类型。\n\n📁 请上传 Base64 加密数据文件（通过侧边栏上传）。\n\n然后直接告诉我您想要处理的威胁类型，我会自动生成映射表。"
        
        elif "帮助" in prompt or "help" in prompt_lower or "怎么用" in prompt:
            return get_help_message()
        
        elif has_file:
            return "我看到您上传了文件。请告诉我您想要怎么处理：\n1. 处理标准字段\n2. 处理枚举字段\n3. 处理威胁类型"
        
        else:
            return "您好！我是数据映射解析助手。\n\n请告诉我您想要：\n1. 处理标准字段\n2. 处理枚举字段\n3. 处理威胁类型\n\n或者直接上传文件，我会自动识别。"
    
    # 已有模式，检查操作
    if "开始" in prompt or "处理" in prompt or "分析" in prompt:
        if has_file:
            # 先显示"正在处理中"状态
            st.session_state.is_processing = True
            st.session_state.processing_mode = st.session_state.current_mode
            add_message("assistant", "⏳ 正在处理中....")
            st.rerun()
        else:
            return "请先上传文件（通过侧边栏上传），然后告诉我'开始处理'。"
    
    elif "确认" in prompt or "完成" in prompt or "确定" in prompt:
        if st.session_state.current_mode == "standard_field":
            result = confirm_standard_mapping()
            return result["message"]
        elif st.session_state.current_mode == "threat_type":
            # 确认威胁类型映射
            result = confirm_threat_mapping()
            return result["message"]
        elif st.session_state.current_mode == "enum_field":
            # 确认枚举字段映射
            result = confirm_enum_mapping()
            return result["message"]
    
    elif "修改" in prompt or "改变" in prompt or "更新" in prompt:
        if st.session_state.current_mode == "standard_field" and st.session_state.mapping_df is not None:
            return "好的，请告诉我您想要如何修改映射表，例如：'将 xxx 改为 yyy'"
        elif st.session_state.current_mode == "threat_type" and st.session_state.threat_mapping_df is not None:
            return "好的，请告诉我您想要如何修改映射，例如：'SQL注入 -> SQL注入攻击'"
    
    elif st.session_state.current_mode == "threat_type":
        # 威胁类型模式下，检查是否是用户输入威胁类型
        if not has_file:
            return "📁 请先上传 Base64 加密数据文件（通过侧边栏上传），然后再告诉我您想要处理的威胁类型。"
        
        # 排除特殊指令关键字
        special_keywords = ["确认", "完成", "确定", "修改", "改变", "更新", "重新", "重置", "清除", "帮助", "填充", "字段", "开始"]
        if any(k in prompt for k in special_keywords):
            # 处理填充到字段指令
            if "填充" in prompt or "字段" in prompt:
                field_name, error_msg = extract_target_field(prompt)
                if error_msg:
                    return error_msg
                if field_name:
                    st.session_state.threat_target_field = field_name
                    matched_item = st.session_state.get("threat_matched_normalize")
                    if matched_item:
                        return f"✅ 已匹配到 normalize 项：\n- index: {matched_item.get('index')}\n- field: {matched_item.get('field')}\n\n映射将填充到该 normalize 项的 mappings 字段。\n\n请确认后告诉我'确认映射'来完成处理。"
                    return f"好的，我将把映射填充到字段 **{field_name}**。\n\n请确认后告诉我'确认映射'来完成处理。"
            return "请告诉我您想要处理的威胁类型。"
        
        # 用户输入了威胁类型，开始处理
        st.session_state.pending_threat_text = prompt
        st.session_state.is_processing = True
        st.session_state.processing_mode = "threat_type_by_input"
        add_message("assistant", "⏳ 正在根据您输入的威胁类型生成映射表....")
        st.rerun()
    
    elif "重新" in prompt or "重置" in prompt or "清除" in prompt:
        st.session_state.current_mode = None
        st.session_state.mapping_df = None
        st.session_state.mapping_confirmed = False
        st.session_state.threat_mapping_df = None
        st.session_state.threat_confirmed = False
        st.session_state.threat_final_result = None
        st.session_state.pending_file = None
        st.session_state.pending_file_name = None
        st.session_state.threat_target_field = None
        st.session_state.threat_target_field_specified = False
        return "好的，已重置。请告诉我您想要怎么处理数据。"
    
    elif "帮助" in prompt or "help" in prompt_lower or "怎么用" in prompt:
        return get_help_message()
    
    elif has_file and st.session_state.current_mode:
        return f"当前模式：{get_mode_name(st.session_state.current_mode)}\n文件已上传：{st.session_state.pending_file_name}\n\n请告诉我'开始处理'来继续。"
    
    else:
        return "抱歉，我不太理解。请告诉我'帮助'查看使用说明。"
