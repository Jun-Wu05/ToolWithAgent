"""
路由关键词配置 — 从 config/route_keywords.json 加载

提供模块级常量：MAPPING_KEYWORDS, THREAT_KEYWORDS, ENUM_KEYWORDS, ENUM_EXTRACT_KEYWORDS
以及带消歧规则的意图检测函数 detect_intent。
"""
import os
import json as _json

from agent.shared.logger import get_logger

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
        "log_parser_keywords": ["日志类型", "特征提取", "识别日志", "日志格式", "日志解析"],
    }
    try:
        with open(_config_path, "r", encoding="utf-8") as _f:
            _data = _json.load(_f)
        return (
            _data.get("mapping_keywords", _defaults["mapping_keywords"]),
            _data.get("threat_keywords", _defaults["threat_keywords"]),
            _data.get("enum_keywords", _defaults["enum_keywords"]),
            _data.get("enum_extract_keywords", _defaults["enum_extract_keywords"]),
            _data.get("log_parser_keywords", _defaults["log_parser_keywords"]),
        )
    except Exception as _e:
        logger.warning(f"[CONFIG] 加载 route_keywords.json 失败: {_e}，使用默认关键词")
        return (
            _defaults["mapping_keywords"],
            _defaults["threat_keywords"],
            _defaults["enum_keywords"],
            _defaults["enum_extract_keywords"],
            _defaults["log_parser_keywords"],
        )


MAPPING_KEYWORDS, THREAT_KEYWORDS, ENUM_KEYWORDS, ENUM_EXTRACT_KEYWORDS, LOG_PARSER_KEYWORDS = _load_route_keywords()



def detect_intent(user_text: str, user_session=None) -> tuple:
    """快路径预筛器：只处理高置信度单关键词命中。

    设计原则：Python 只做确定性高、无需思考的快速判断；
    涉及理解、消歧、状态感知的决策全部交给 RouterAgent。
    状态前置检查（有无数据）和意图消歧由 RouterAgent 的 prompt 处理。

    - 单关键词命中 → 快路径直调 MemberAgent（省1次LLM调用）
    - 多关键词冲突 / 无关键词 → general（交 RouterAgent 全权路由+引导）

    Args:
        user_text: 用户原始输入文本
        user_session: 会话状态（用于填充模式强制）

    Returns:
        (intent, reason)：intent 为 mapping/threat/enum/log_parser/fill/general
    """
    lower = user_text.lower()

    # 填充模式强制（按钮驱动的两阶段流程内部消息）
    if user_session is not None:
        if user_session.get("threat_fill_mode", False):
            return "threat", "threat_fill_mode 开启，强制 threat"
        if user_session.get("enum_fill_mode", False):
            return "enum", "enum_fill_mode 开启，强制 enum"

    # 填充动作识别 → fill_dispatcher
    if any(p in lower for p in ("填充到", "填充", "填入", "填到")):
        return "fill", "填充动作，交 fill_dispatcher 决定类型"

    # 基础子串匹配
    is_enum_extract = any(kw in lower for kw in ENUM_EXTRACT_KEYWORDS)
    is_threat = any(kw in lower for kw in THREAT_KEYWORDS)
    is_mapping = any(kw in lower for kw in MAPPING_KEYWORDS)
    is_enum = any(kw in lower for kw in ENUM_KEYWORDS)
    is_log_parser = any(kw in lower for kw in LOG_PARSER_KEYWORDS)

    # 枚举提取和枚举是同一操作域，合并为一个标志
    is_enum_domain = is_enum_extract or is_enum

    # 统计命中的意图域数量（枚举域算一个，用于判断是否多域冲突）
    hit_count = sum([is_enum_domain, is_threat, is_mapping, is_log_parser])

    # 多关键词冲突 → 交 RouterAgent 消歧（不再有 ambiguous）
    if hit_count > 1:
        return "general", f"多关键词冲突（{hit_count}个），交 RouterAgent 语义判断"

    # 单关键词域命中 → 快路径
    if is_enum_extract:
        return "enum", "命中枚举提取关键词"
    if is_threat:
        return "threat", "命中威胁关键词"
    if is_mapping:
        return "mapping", "命中映射关键词"
    if is_enum:
        return "enum", "命中枚举关键词"
    if is_log_parser:
        return "log_parser", "命中日志解析关键词"
    # 无关键词 → RouterAgent

    # 无关键词 → RouterAgent
    return "general", "无关键词命中，走通用路由"
