"""事件名称判定与写入（PRD #124）。

职责：
1. 常量：21 个合法事件分类名 + 事件级别绑定查表（确定性，不经 LLM）。
2. ``classify_sub_rule_events``：单次 LLM 批量判定每条子规则的事件名称，
   输出经白名单校验；非法条目带反馈重试一次，仍非法则进入待人工确认列表
   （宁缺勿错：不写入错误值）。「其他告警」是威胁组的合法兜底类，由 LLM
   主动选择，而非代码强塞。
3. ``apply_event_fields_to_sub_rules``：确定性写入——filter 末尾追加
   addFields（与【日志类型】同构），normalize 末尾追加事件名称/事件级别
   两条目；入口规则不动，调用方只传子规则。
"""

from __future__ import annotations

import copy
import json
from typing import Any

from agent.prompts import load_event_classify_prompt
from agent.shared.llm_response import strip_code_fences
from agent.shared.logger import get_logger
from contracts.planner_models import THREAT_TYPE_FIELD

logger = get_logger("event_classify")

# ---------------------------------------------------------------------------
# 常量：21 个合法事件分类名与事件级别绑定表
# ---------------------------------------------------------------------------

THREAT_EVENT_NAMES: tuple[str, ...] = (
    "网络攻击",
    "病毒检测",
    "邮件告警",
    "终端告警",
    "蜜罐告警",
    "其他告警",
)
"""威胁组 6 值：事件级别绑定「提醒」；「其他告警」为组内兜底类。"""

NON_THREAT_EVENT_NAMES: tuple[str, ...] = (
    "登录事件",
    "审计事件",
    "会话操作",
    "进程操作",
    "用户操作",
    "资源监控",
    "邮件操作",
    "dns查询",
    "dns响应",
    "数据库操作",
    "ssh连接",
    "认证事件",
    "telnet连接",
    "网络连接",
    "web访问",
)
"""非威胁组 15 值：事件级别绑定「信息」；无兜底类，判定失败不写入。"""

THREAT_EVENT_LEVEL = "提醒"
NON_THREAT_EVENT_LEVEL = "信息"

EVENT_NAME_LEVEL_BINDING: dict[str, str] = {
    **{name: THREAT_EVENT_LEVEL for name in THREAT_EVENT_NAMES},
    **{name: NON_THREAT_EVENT_LEVEL for name in NON_THREAT_EVENT_NAMES},
}
"""事件名称 → 事件级别 的确定性查表；绑定关系不由 LLM 决定。"""

EVENT_LEVEL_CODE_BINDING: dict[str, str] = {
    "信息": "0",
    "提醒": "1",
    "警告": "2",
    "严重": "3",
    "紧急": "4",
}
"""事件级别显示值 → 整型码值；标准目录声明 event_level 为整型（标准字段.txt）。"""

OPERATION_TYPE_FIELD = "操作类型"
OPERATION_TYPE_FALLBACK = "其他"
EVENT_NAME_OPERATION_ENUM_BINDING: dict[str, tuple[str, ...]] = {
    "登录事件": ("登录", "登出", "其他", "未映射"),
    "审计事件": (
        "其他", "打印审计", "数据库审计", "登出", "登录",
        "移动存储审计", "终端入网", "访客入网", "超时", "远程桌面",
    ),
    "会话操作": ("其他", "开始", "未映射", "终止"),
    "进程操作": (
        "API调用", "其他", "其他属性修改", "创建", "唤醒", "快照",
        "挂起", "未映射", "权限提升", "注入", "篡改", "终止", "访问",
    ),
    "用户操作": (
        "修改", "其他", "其他属性修改", "切换", "创建", "删除", "密码修改",
        "所属组修改", "未映射", "权限修改", "枚举", "激活", "登出", "登录",
        "禁用", "解锁", "重命名", "锁定",
    ),
    "资源监控": ("其他", "故障", "未映射", "正常", "警告"),
    "邮件操作": ("其他", "删除", "发送", "接收", "未映射", "附件下载"),
}
"""事件名称 → 操作类型合法枚举（#395）。

仅 event_classify.md 定义了操作类型枚举的 7 个非威胁类参与绑定；
威胁组与其余协议类不写操作类型。枚举值与提示词逐字一致。
"""

EVENT_NAME_FIELD = "事件名称"
EVENT_LEVEL_FIELD = "事件级别"
# 威胁类型字段名单一来源在 contracts（application 核心层不得依赖 agent）；
# 此处 re-export 保持既有导入路径不变。

ALL_EVENT_NAMES = frozenset(EVENT_NAME_LEVEL_BINDING)


def read_entity_event_name(entity: Any) -> str | None:
    """读取单条 entity 已标注的事件名称（addFields 固定值优先，normalize 兜底）。

    值不在 21 名绑定表内（含空值）视为未标注，返回 None。
    skill_ops 威胁分组与 session_facts 事件标注事实共用此读取逻辑。
    """
    parser = entity.get("parser") or {}
    for filter_item in parser.get("filter") or []:
        if (
            isinstance(filter_item, dict)
            and filter_item.get("name") == "addFields"
            and filter_item.get("id") == ""
            and isinstance(filter_item.get("fields"), dict)
            and EVENT_NAME_FIELD in filter_item["fields"]
        ):
            value = filter_item["fields"][EVENT_NAME_FIELD]
            if value in EVENT_NAME_LEVEL_BINDING:
                return str(value)
    for entry in entity.get("normalize") or []:
        if isinstance(entry, dict) and entry.get("index") == EVENT_NAME_FIELD:
            result = entry.get("result") or [""]
            value = str(result[0]) if result else ""
            if value in EVENT_NAME_LEVEL_BINDING:
                return value
    return None

# 判定输入的规模约束：样本截断与字段数上限，防止单条子规则撑爆 prompt
_SAMPLE_MAX_CHARS = 600
_FIELD_LIST_LIMIT = 30


# ---------------------------------------------------------------------------
# 信号组装与 LLM 判定
# ---------------------------------------------------------------------------


def _build_rule_signals(sub_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把每条子规则压缩为判定信号：规则名、日志类型、样本、字段列表。"""
    signals: list[dict[str, Any]] = []
    for rule in sub_rules:
        normalize = rule.get("normalize") or []
        indexes = [
            str(entry.get("index"))
            for entry in normalize
            if isinstance(entry, dict) and entry.get("index")
        ]
        logtype = ""
        for entry in normalize:
            if isinstance(entry, dict) and entry.get("index") == "日志类型":
                result = entry.get("result") or [""]
                logtype = str(result[0]) if result else ""
                break
        sample = str(rule.get("sample", "") or "")[:_SAMPLE_MAX_CHARS]
        signals.append(
            {
                "rule_name": str(rule.get("name", "")),
                "日志类型": logtype,
                "样本日志": sample,
                "字段列表": indexes[:_FIELD_LIST_LIMIT],
            }
        )
    return signals


def _extract_results(raw_text: str) -> list[dict[str, Any]]:
    """从 LLM 响应提取 results 数组；容忍 markdown 代码块包装。

    json.loads 的异常上抛语义保持不变（调用方依赖异常触发重试），
    围栏剥离统一走共享原语。
    """
    text = strip_code_fences(raw_text)
    data = json.loads(text)
    if isinstance(data, dict):
        results = data.get("results")
    else:
        results = data
    if not isinstance(results, list):
        raise ValueError("LLM 判定输出缺少 results 数组")
    return [item for item in results if isinstance(item, dict)]


def _validate_results(
    results: list[dict[str, Any]], expected_names: set[str]
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """校验白名单与组一致性，返回 (合法判定表, 操作类型表, 非法项描述列表)。

    操作类型（#395）：仅绑定类校验类内枚举，非法/缺失降级「其他」，
    不参与重试反馈；未绑定类（威胁组与协议类）不产出操作类型。
    """
    accepted: dict[str, str] = {}
    operations: dict[str, str] = {}
    invalid: list[str] = []
    for item in results:
        rule_name = str(item.get("rule_name", ""))
        event_name = str(item.get("event_name", ""))
        group = str(item.get("group", ""))
        if rule_name not in expected_names:
            invalid.append(f"未知规则名: {rule_name}")
            continue
        if event_name not in ALL_EVENT_NAMES:
            invalid.append(f"{rule_name}: 非法事件名称 '{event_name}'")
            continue
        expected_group = "threat" if event_name in THREAT_EVENT_NAMES else "non_threat"
        if group and group not in {expected_group, expected_group.replace("_", "-")}:
            invalid.append(f"{rule_name}: 分组 {group} 与 {event_name} 不一致")
            continue
        accepted[rule_name] = event_name
        legal_operations = EVENT_NAME_OPERATION_ENUM_BINDING.get(event_name)
        if legal_operations:
            operation = str(item.get("operation_type", "") or "")
            if operation not in legal_operations:
                operation = OPERATION_TYPE_FALLBACK
            operations[rule_name] = operation
    return accepted, operations, invalid


async def classify_sub_rule_events(
    sub_rules: list[dict[str, Any]],
    *,
    llm_client: Any = None,
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """LLM 批量判定每条子规则的事件名称与操作类型。

    Args:
        sub_rules: 子规则列表（读 name/sample/normalize，不修改）。
        llm_client: 依赖注入接缝；缺省走工具门面 ``call_llm_direct``。
            测试传同步或异步假件均可。

    Returns:
        (judgments, operations, uncertain)：judgments 为 rule_name → 合法事件
        名称；operations 为 rule_name → 类内合法操作类型（仅绑定类，非法/缺
        失已降级「其他」）；uncertain 为重试后仍无法判定的规则名列表。
    """

    async def _call(prompt: str) -> str:
        if llm_client is not None:
            response = llm_client(prompt)
            if hasattr(response, "__await__"):
                response = await response
            return str(response)
        from agent.tools import call_llm_direct

        return await _run_in_executor(call_llm_direct, prompt)

    signals = _build_rule_signals(sub_rules)
    if not signals:
        return {}, {}, []

    expected_names = {signal["rule_name"] for signal in signals}
    template = load_event_classify_prompt()
    base_prompt = (
        f"{template}\n\n## 待判定子规则\n```json\n"
        f"{json.dumps(signals, ensure_ascii=False, indent=1)}\n```\n"
    )

    prompt = base_prompt
    accepted: dict[str, str] = {}
    operations: dict[str, str] = {}
    for _attempt in range(2):
        raw = await _call(prompt)
        try:
            results = _extract_results(raw)
        except (json.JSONDecodeError, ValueError) as parse_error:
            invalid = [f"输出不是合法 JSON: {parse_error}"]
            results = []
        attempt_accepted, attempt_operations, invalid = _validate_results(
            results, expected_names
        )
        # 跨轮合并：重试只补缺口，不因第二轮遗漏而丢失首轮已判定条目
        accepted.update(attempt_accepted)
        operations.update(attempt_operations)
        missing = sorted(expected_names - set(accepted))
        if not missing and not invalid:
            return accepted, operations, []
        # 带错误反馈重试一次
        prompt = (
            f"{base_prompt}\n上一次输出存在以下问题，必须修正：\n"
            + "\n".join(f"- {item}" for item in invalid)
            + "\n- 缺少判定: " + ", ".join(missing)
            + "\n请重新输出完整 JSON。"
        )

    uncertain = sorted(expected_names - set(accepted))
    if uncertain:
        logger.warning(
            "[EVENT_CLASSIFY] 以下子规则事件名称重试后仍无法判定，待人工确认: %s",
            uncertain,
        )
    return accepted, operations, uncertain


async def _run_in_executor(func: Any, *args: Any) -> Any:
    """把同步直连调用放到线程池，避免阻塞事件循环。"""
    import asyncio
    import functools

    return await asyncio.get_running_loop().run_in_executor(
        None, functools.partial(func, *args)
    )


# ---------------------------------------------------------------------------
# 确定性写入
# ---------------------------------------------------------------------------


def make_event_name_normalize_entry(
    event_name: str, sample_count: int = 1
) -> dict[str, Any]:
    """构建【事件名称】normalize 条目（仿 make_log_type_entry 形态）。

    对象归属「事件」（#177）：标准字段目录中 event_name/event_level 的对象
    均为「事件」；此前的「日志」是与目录冲突的过时决策，目标平台无法解析。
    恒等 EQUAL 映射 + value 默认值（#392）：导出平台按 mappings/value 取值，
    空值会让事件名称解析为空。result 每份日志一条。
    """
    return {
        "mappings": [
            {"mappingType": "EQUAL", "mappingValue": event_name, "orgValue": event_name}
        ],
        "field": "event_name",
        "sim": True,
        "result": [event_name] * sample_count,
        "info": None,
        "entity": "事件",
        "required": False,
        "core": False,
        "value": event_name,
        "index": EVENT_NAME_FIELD,
    }


def make_event_level_normalize_entry(
    event_level: str, sample_count: int = 1
) -> dict[str, Any]:
    """构建【事件级别】normalize 条目（对象归属「事件」，#177）。

    标准目录声明 event_level 为整型（#392）：value 写码值，mappings 记录
    显示值→码值的 EQUAL 变换；addFields filter 与 result 保持显示值。
    """
    code = EVENT_LEVEL_CODE_BINDING[event_level]
    return {
        "mappings": [
            {"mappingType": "EQUAL", "mappingValue": code, "orgValue": event_level}
        ],
        "field": "event_level",
        "sim": True,
        "result": [event_level] * sample_count,
        "info": None,
        "entity": "事件",
        "required": False,
        "core": False,
        "value": code,
        "index": EVENT_LEVEL_FIELD,
    }


def apply_event_fields_to_sub_rules(
    sub_rules: list[dict[str, Any]],
    judgments: dict[str, str],
) -> list[dict[str, Any]]:
    """把判定结果写入每条子规则（深拷贝，不修改原数据）。

    对每条有合法判定的子规则：
    - parser.filter 末尾追加 addFields：{"事件名称": <分类名>, "事件级别": <绑定级别>}；
    - normalize 末尾追加事件名称、事件级别两条目。
    无判定（待人工确认）的子规则保持不变。
    """
def make_operation_type_normalize_entry(
    operation: str, sample_count: int = 1
) -> dict[str, Any]:
    """构建【操作类型】normalize 条目（#395，形态与事件名称/级别一致）。"""
    return {
        "mappings": [
            {"mappingType": "EQUAL", "mappingValue": operation, "orgValue": operation}
        ],
        "field": "event_operation_type",
        "sim": True,
        "result": [operation] * sample_count,
        "info": None,
        "entity": "事件",
        "required": False,
        "core": False,
        "value": operation,
        "index": OPERATION_TYPE_FIELD,
    }


def _rule_sample_count(rule: dict[str, Any]) -> int:
    """按子规则既有 normalize 条目的 result 长度推导样本数（无条目回退 1）。"""
    for entry in rule.get("normalize") or []:
        result = entry.get("result") if isinstance(entry, dict) else None
        if isinstance(result, list) and result:
            return len(result)
    return 1


def apply_event_fields_to_sub_rules(
    sub_rules: list[dict[str, Any]],
    judgments: dict[str, str],
    operations: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """把判定结果写入每条子规则（深拷贝，不修改原数据）。

    对每条有合法判定的子规则：
    - parser.filter 末尾追加 addFields：{"事件名称": <分类名>, "事件级别": <绑定级别>}；
    - normalize 末尾追加事件名称、事件级别两条目，result 按该子规则样本数复制；
    - 事件名称在操作类型绑定表内时（#395），addFields 追加 "操作类型"，并
      写第三条目（缺失/非法已由判定层降级，此处再兜底「其他」）。
    无判定（待人工确认）的子规则保持不变。
    """
    operations = operations or {}
    updated = copy.deepcopy(sub_rules)
    for rule in updated:
        event_name = judgments.get(str(rule.get("name", "")))
        if event_name not in ALL_EVENT_NAMES:
            continue
        event_level = EVENT_NAME_LEVEL_BINDING[event_name]
        sample_count = _rule_sample_count(rule)

        add_fields: dict[str, Any] = {
            EVENT_NAME_FIELD: event_name,
            EVENT_LEVEL_FIELD: event_level,
        }
        if event_name in EVENT_NAME_OPERATION_ENUM_BINDING:
            add_fields[OPERATION_TYPE_FIELD] = operations.get(
                str(rule.get("name", "")), OPERATION_TYPE_FALLBACK
            )

        parser = rule.get("parser") or {}
        filters = parser.get("filter") or []
        filters.append(
            {
                "fields": add_fields,
                "name": "addFields",
                "id": "",
            }
        )
        parser["filter"] = filters
        rule["parser"] = parser

        normalize = rule.get("normalize") or []
        normalize.append(make_event_name_normalize_entry(event_name, sample_count))
        normalize.append(make_event_level_normalize_entry(event_level, sample_count))
        if OPERATION_TYPE_FIELD in add_fields:
            normalize.append(
                make_operation_type_normalize_entry(
                    add_fields[OPERATION_TYPE_FIELD], sample_count
                )
            )
        rule["normalize"] = normalize
    return updated
