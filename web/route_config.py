"""
路由关键词配置 — 从 config/route_keywords.json 加载

提供模块级常量：MAPPING_KEYWORDS, THREAT_KEYWORDS, ENUM_KEYWORDS, ENUM_EXTRACT_KEYWORDS
"""
import os
import json as _json

from src.logger import get_logger

logger = get_logger("route_config")

# 获取项目根目录
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)


def _load_route_keywords():
    """从 config/route_keywords.json 加载路由关键词"""
    _config_path = os.path.join(_project_root, "config", "route_keywords.json")
    _defaults = {
        "mapping_keywords": ["映射", "字段", "标准字段", "字段映射"],
        "threat_keywords": ["威胁类型", "threat_type", "威胁类型标准化", "威胁类型映射"],
        "enum_keywords": ["枚举", "枚举字段", "enum"],
        "enum_extract_keywords": ["提取枚举", "枚举值", "列举枚举", "列出枚举"],
    }
    try:
        with open(_config_path, "r", encoding="utf-8") as _f:
            _data = _json.load(_f)
        return (
            _data.get("mapping_keywords", _defaults["mapping_keywords"]),
            _data.get("threat_keywords", _defaults["threat_keywords"]),
            _data.get("enum_keywords", _defaults["enum_keywords"]),
            _data.get("enum_extract_keywords", _defaults["enum_extract_keywords"]),
        )
    except Exception as _e:
        logger.warning(f"[CONFIG] 加载 route_keywords.json 失败: {_e}，使用默认关键词")
        return (
            _defaults["mapping_keywords"],
            _defaults["threat_keywords"],
            _defaults["enum_keywords"],
            _defaults["enum_extract_keywords"],
        )


MAPPING_KEYWORDS, THREAT_KEYWORDS, ENUM_KEYWORDS, ENUM_EXTRACT_KEYWORDS = _load_route_keywords()