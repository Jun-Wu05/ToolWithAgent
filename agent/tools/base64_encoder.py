"""
Base64 编码工具
"""
import base64
import json
from typing import Any, Union


def base64_encode(data: Union[dict, str, list]) -> dict:
    """
    Agno Tool: 将数据编码为 Base64
    
    Args:
        data: 要编码的数据，可以是 dict, str, 或 list
        
    Returns:
        dict: 包含编码结果
            - base64_encoded: Base64 编码字符串
            - decoded_preview: 前 200 字符预览
            - status: "success" 或 "error"
    """
    try:
        # 如果是 dict 或 list，先转为 JSON 字符串
        if isinstance(data, (dict, list)):
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
        elif isinstance(data, str):
            json_str = data
        else:
            return {
                "status": "error",
                "error_message": f"不支持的数据类型: {type(data)}"
            }
        
        # Base64 编码
        encoded_bytes = base64.b64encode(json_str.encode("utf-8"))
        base64_encoded = encoded_bytes.decode("ascii")
        
        # 生成预览
        decoded_preview = json_str[:200] + "..." if len(json_str) > 200 else json_str
        
        return {
            "status": "success",
            "base64_encoded": base64_encoded,
            "decoded_preview": decoded_preview,
            "original_length": len(json_str),
            "encoded_length": len(base64_encoded)
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"Base64 编码失败: {str(e)}"
        }


def json_to_base64(json_data: Any) -> str:
    """
    将 JSON 数据编码为 Base64 字符串
    
    Args:
        json_data: JSON 数据 (dict, list, 或 JSON 字符串)
        
    Returns:
        str: Base64 编码字符串
    """
    if isinstance(json_data, str):
        json_str = json_data
    else:
        json_str = json.dumps(json_data, ensure_ascii=False)
    
    encoded_bytes = base64.b64encode(json_str.encode("utf-8"))
    return encoded_bytes.decode("ascii")


def base64_to_json(base64_str: str) -> Any:
    """
    将 Base64 字符串解码为 JSON 数据
    
    Args:
        base64_str: Base64 编码字符串
        
    Returns:
        Any: 解码后的 JSON 数据
    """
    decoded_bytes = base64.b64decode(base64_str)
    return json.loads(decoded_bytes.decode("utf-8"))
