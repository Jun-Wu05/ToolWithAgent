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


# 威胁类型的「强信号」短语 — 命中时高置信度判定为 threat（优先级高于 mapping）
# 这些短语明确表示用户要做威胁类型标准化，而非字段映射
_THREAT_STRONG_PHRASES = ("威胁类型", "威胁种类", "threat_type", "threat type")
# 威胁类型处理的「动作」短语 — 与强信号组合时锁定 threat
_THREAT_ACTION_PHRASES = ("标准化", "归一化", "映射", "处理", "转换", "识别")


def _has_data_for_mapping(session) -> bool:
    """检查是否有可供映射的数据（decoded_data/decoded_fields 或 simplified_data.fields）。

    用于状态前置检查：用户说「映射」但没上传文件时，不应直调 FieldMappingAgent
    （会报错重试），而应交 RouterAgent 引导上传。
    """
    if session is None:
        return False
    has_decoded = bool(session.get("decoded_data") or session.get("decoded_fields"))
    simplified = session.get("simplified_data", {})
    has_fields = bool(simplified.get("fields", [])) if isinstance(simplified, dict) else False
    return has_decoded or has_fields


def detect_intent(user_text: str, user_session=None) -> tuple:
    """带消歧规则的意图检测，返回 (intent, reason)。

    相比裸 any(kw in text) 子串匹配，本函数处理多意图冲突：
    - 威胁 vs 映射：「威胁字段映射」应走 mapping（用户要做字段映射），
      但「我想标准化威胁类型」应走 threat（明确做威胁类型标准化）。
    - 判定规则：含威胁强信号短语（威胁类型/threat_type）+ 威胁动作词（标准化/映射）
      且不含字段映射动作（字段映射/生成映射表）时 → threat，否则 mapping。

    Args:
        user_text: 用户原始输入文本
        user_session: 会话状态（用于上下文辅助，如 threat_fill_mode 开启时强制 threat）

    Returns:
        (intent, reason)：intent 为 mapping/threat/enum/log_parser/general，
        reason 为人类可读的判定依据（用于日志）。
    """
    lower = user_text.lower()

    # 上下文辅助：威胁/枚举填充模式开启时，强制对应意图（填充流程内部消息）
    if user_session is not None:
        if user_session.get("threat_fill_mode", False):
            return "threat", "threat_fill_mode 开启，强制 threat"
        if user_session.get("enum_fill_mode", False):
            return "enum", "enum_fill_mode 开启，强制 enum"

    # 基础子串匹配（各意图独立检测）
    is_enum_extract = any(kw in lower for kw in ENUM_EXTRACT_KEYWORDS)
    is_threat = any(kw in lower for kw in THREAT_KEYWORDS)
    is_mapping = any(kw in lower for kw in MAPPING_KEYWORDS)
    is_enum = any(kw in lower for kw in ENUM_KEYWORDS)
    is_log_parser = any(kw in lower for kw in LOG_PARSER_KEYWORDS)

    # 填充动作识别：「填充」「填充到」是枚举/威胁填充的明确信号，
    # 必须在枚举提取和 mapping 之前拦截（否则「枚举值填充进子规则」会被「枚举值」抢到提取）
    is_fill_action = any(p in lower for p in ("填充到", "填充", "填入", "填到"))

    # 填充动作优先级最高：含「填充」且已有映射表时，走填充流程（先于枚举提取）
    if is_fill_action and user_session is not None:
        has_enum_excel = bool(user_session.get("enum_excel_path"))
        has_mapped_sub = bool(user_session.get("mapped_sub_rules"))
        has_threat_table = bool(user_session.get("threat_mapping_table"))
        if has_enum_excel or has_mapped_sub:
            return "enum", "填充动作 + 已有枚举映射表/子规则，走枚举填充"
        if has_threat_table:
            return "threat", "填充动作 + 已有威胁映射表，走威胁填充"

    # 枚举提取（精确动作词，填充之后）
    if is_enum_extract:
        return "enum", f"命中枚举提取关键词"

    # 日志解析（独立，与其他意图冲突少）
    if is_log_parser and not is_threat and not is_mapping:
        return "log_parser", f"命中日志解析关键词"

    # ====== 核心：威胁 vs 映射消歧 ======
    # 含威胁强信号（威胁类型/threat_type）+ 威胁动作词（标准化/处理）→ threat
    has_threat_strong = any(p in lower for p in _THREAT_STRONG_PHRASES)
    has_threat_action = any(p in lower for p in _THREAT_ACTION_PHRASES)
    # 字段映射的强信号（明确要做字段映射，不是威胁类型映射）
    has_mapping_strong = any(p in lower for p in ("字段映射", "生成映射表", "标准字段处理", "字段标准化", "映射字段"))

    if is_threat and is_mapping:
        # 冲突消歧
        if has_mapping_strong:
            return "mapping", f"含字段映射强信号，优先 mapping（尽管命中威胁词）"
        if has_threat_strong and has_threat_action:
            return "threat", f"含威胁类型强信号+动作词，判定 threat"
        # 无法消歧 → 交 RouterAgent 判断（而非默认 mapping）
        return "ambiguous", "威胁+映射冲突无法消歧，交 RouterAgent"

    if is_threat:
        return "threat", f"命中威胁关键词"

    if is_enum:
        return "enum", f"命中枚举关键词"

    # 状态前置检查：mapping 意图但无数据 → 改为 general（交 RouterAgent 引导上传）
    if is_mapping and not _has_data_for_mapping(user_session):
        return "general", "映射意图但无数据，交 RouterAgent 引导上传"

    if is_mapping:
        return "mapping", f"命中映射关键词"

    if is_log_parser:
        return "log_parser", f"命中日志解析关键词"

    return "general", "无关键词命中，走通用路由"
