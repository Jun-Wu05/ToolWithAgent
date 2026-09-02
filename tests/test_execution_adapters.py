"""执行适配器对真实领域数据变更的回归测试。"""

import asyncio
import base64
import copy
import json
from datetime import datetime
from types import SimpleNamespace

from application.adapters import (
    EnumFillAdapter,
    ExportAdapter,
    FieldMappingExecutionPolicy,
    ProfessionalAgentAdapter,
    create_default_adapters,
)
from application.execution import ExecutionContext, PlanExecutor
from contracts.planner_models import ExportStep, FieldMappingStep, FillStep, PlanDecision, StepStatus
from application.session_projection import build_session_facts


def test枚举映射表上下文执行填充而非枚举提取():
    session = {
        "mapped_sub_rules": [
            {"name": "rule-1", "normalize": [{"index": "event_type3", "mappings": []}]}
        ],
        "enum_preview": [
            {
                "目标字段": "event_type3",
                "mappingType": "EQUAL",
                "orgValue": "attack",
                "mappingValue": "攻击",
            }
        ],
        "raw_base64": "存在即可，不能写入 Planner 输入",
    }
    step = FillStep(
        step_id="enum-fill",
        type="fill",
        fill_kind="enum",
        target_fields=("event_type3",),
        source_ref="session.enum_mapping_table",
        config_ref="session.mapped_sub_rules",
    )

    result = asyncio.run(
        EnumFillAdapter().execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.changed_count == 1
    mappings = session["mapped_sub_rules"][0]["normalize"][0]["mappings"]
    assert mappings == [
        {"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "攻击"}
    ]
    assert result.artifact.artifact_type == "config_export"
    assert result.artifact.download_kind == "enummapping_config"


def test真实Base64上传状态可直接填充完整解码配置():
    """复现上传只产生 decoded_data 时被错误要求先生成 mapped_sub_rules 的回归。"""
    session = {
        "decoded_data": {
            "name": "uploaded-rule",
            "normalize": [{"index": "event_type3", "mappings": []}],
        },
        "decoded_fields": ["event_type3"],
        "raw_base64": "present",
        "enum_preview": [
            {
                "目标字段": "event_type3",
                "mappingType": "EQUAL",
                "orgValue": "attack",
                "mappingValue": "攻击",
            }
        ],
    }
    step = FillStep(
        step_id="enum-fill",
        type="fill",
        fill_kind="enum",
        target_fields=("event_type3",),
        source_ref="session.enum_mapping_table",
        config_ref="session.decoded_config",
    )

    result = asyncio.run(
        EnumFillAdapter().execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.changed_count == 1
    assert session["decoded_data"]["normalize"][0]["mappings"] == [
        {"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "攻击"}
    ]
    assert result.artifact.artifact_type == "config_export"

def test真实Base64状态通过PlanExecutor完成枚举填充():
    """覆盖上传状态、事实投影、前置校验和真实填充适配器的完整链路。"""
    session = {
        "decoded_data": {
            "name": "uploaded-rule",
            "normalize": [{"index": "event_type3", "mappings": []}],
        },
        "decoded_fields": ["event_type3"],
        "raw_base64": "present",
        "enum_preview": [
            {
                "目标字段": "event_type3",
                "mappingType": "EQUAL",
                "orgValue": "attack",
                "mappingValue": "攻击",
            }
        ],
    }
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "base64-enum-fill",
            "steps": [
                {
                    "step_id": "fill",
                    "type": "fill",
                    "fill_kind": "enum",
                    "target_fields": ["event_type3"],
                    "source_ref": "session.enum_mapping_table",
                    "config_ref": "session.decoded_config",
                }
            ],
        }
    )

    report = asyncio.run(
        PlanExecutor(create_default_adapters(team=None)).execute(
            decision,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )

    assert report.status == StepStatus.SUCCESS
    assert report.results[0].changed_count == 1
    assert session["decoded_data"]["normalize"][0]["mappings"][0]["orgValue"] == "attack"
    assert report.results[0].artifact.content

def test同一枚举映射重复填充返回零变更供执行器拦截():
    existing_mapping = {"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "攻击"}
    session = {
        "mapped_sub_rules": [
            {"normalize": [{"index": "event_type3", "mappings": [existing_mapping]}]}
        ],
        "enum_preview": [{"目标字段": "event_type3", **existing_mapping}],
        "raw_base64": "present",
    }
    step = FillStep(
        step_id="enum-fill",
        type="fill",
        fill_kind="enum",
        target_fields=("event_type3",),
        source_ref="session.enum_mapping_table",
        config_ref="session.mapped_sub_rules",
    )

    result = asyncio.run(
        EnumFillAdapter().execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.changed_count == 0


def test真实PlanExecutor将枚举删除计为变化():
    """新版规则删除多于新增时仍成功，避免总数减少被误判为零变化。"""
    session = {
        "decoded_data": {
            "name": "uploaded-rule",
            "normalize": [{"index": "event_type3", "mappings": []}],
        },
        "decoded_fields": ["event_type3"],
        "raw_base64": "present",
        "enum_preview": [
            {
                "目标字段": "event_type3",
                "mappingType": "EQUAL",
                "orgValue": "attack",
                "mappingValue": "攻击",
            },
            {
                "目标字段": "event_type3",
                "mappingType": "EQUAL",
                "orgValue": "obsolete",
                "mappingValue": "旧规则",
            },
        ],
    }
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "delete-enum-mapping",
            "steps": [
                {
                    "step_id": "fill",
                    "type": "fill",
                    "fill_kind": "enum",
                    "target_fields": ["event_type3"],
                    "source_ref": "session.enum_mapping_table",
                    "config_ref": "session.decoded_config",
                }
            ],
        }
    )
    executor = PlanExecutor(create_default_adapters(team=None))
    first_report = asyncio.run(
        executor.execute(
            decision,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )
    assert first_report.status == StepStatus.SUCCESS

    session["enum_preview"] = [session["enum_preview"][0]]
    session["enum_pending_refills"] = {"session.decoded_config": {"event_type3"}}
    session["stale_enum_config_refs"] = {"session.decoded_config"}
    replacement_report = asyncio.run(
        executor.execute(
            decision,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )

    assert replacement_report.status == StepStatus.SUCCESS
    assert replacement_report.results[0].changed_count == 1
    assert session["decoded_data"]["normalize"][0]["mappings"] == [
        {"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "攻击"}
    ]


class _MappingMember:
    """返回与当前批次字段一一对应的结构化映射结果。"""

    name = "FieldMappingAgent"

    def __init__(self):
        """记录每次专业 Agent 调用。"""
        self.calls = []

    def run(self, model_input):
        """从批次输入中读取字段列表并生成稳定测试结果。"""
        import json
        import re

        self.calls.append(model_input)
        match = re.search(r"字段列表（.*?）：\n(\[.*?\])", model_input, re.S)
        fields = json.loads(match.group(1))
        return [
            {
                "原始字段名": field,
                "系统属性名称": f"标准_{field}",
                "匹配状态": "匹配成功",
            }
            for field in fields
        ]


class _Team:
    """提供测试用专业 Agent 成员列表。"""

    def __init__(self, member):
        """保存单个字段映射成员。"""
        self.members = [member]


def test字段映射批次只消费原始字段候选池():
    """标准名保留在 Planner 词典中，但不得再次送入映射 LLM。"""
    from application.adapters.field_mapping import FieldMappingAdapter
    from contracts.session_facts import SessionFacts

    class RecordingBatchRunner:
        def __init__(self) -> None:
            self.fields = []

        async def run(self, fields, **kwargs):
            self.fields = list(fields)
            return [
                {
                    "原始字段名": field,
                    "系统属性名称": f"标准_{field}",
                    "匹配状态": "匹配成功",
                }
                for field in fields
            ]

    runner = RecordingBatchRunner()
    facts = SessionFacts(
        available_fields=("src_ip", "源IP"),
        mappable_fields=("src_ip",),
    )

    result = asyncio.run(
        FieldMappingAdapter(team=None, batch_runner=runner).execute(
            FieldMappingStep(
                step_id="mapping-pool",
                type="field_mapping",
                source_ref="session.fields",
            ),
            ExecutionContext(session={}, session_facts=facts),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert runner.fields == ["src_ip"]


def test字段映射超过25个字段时分批并回写子规则(monkeypatch):
    """验证批处理能力保留，且映射结果真正更新 mapped_sub_rules。"""
    import application.field_mapping_input as input_builder

    import agent.tools.rule_generator as rule_generator
    import agent.tools.standard_mapper as standard_mapper
    import application.field_source as field_source

    fields = tuple(f"field_{index}" for index in range(26))
    generated_sub_rules = [
        {
            "name": "rule-1",
            "normalize": [{"index": field, "field": ""} for field in fields],
        }
    ]
    monkeypatch.setattr(
        field_source,
        "extract_log_fields_for_mapping",
        lambda classification, raw_log_lines: list(fields),
    )
    monkeypatch.setattr(
        rule_generator,
        "generate_sub_rules",
        lambda classification, all_logs_str, rule_source_fields: generated_sub_rules,
    )
    monkeypatch.setattr(standard_mapper, "_load_object_mapping", lambda path: {})
    session = {
        "log_classification": {"类型A": {}},
        "raw_log_lines": ["field_0=value"],
        "rule_source_fields": {
            "product": "产品",
            "log_vendor": "厂商",
            "data_source": "产品(厂商)",
        },
    }
    member = _MappingMember()
    step = FieldMappingStep(
        step_id="mapping",
        type="field_mapping",
        source_ref="session.fields",
    )

    result = asyncio.run(
        ProfessionalAgentAdapter(_Team(member), candidate_retriever=lambda fields: "").execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.artifact.item_count == 26
    assert len(member.calls) == 2
    normalized_fields = [item["field"] for item in session["mapped_sub_rules"][0]["normalize"]]
    assert normalized_fields == [f"标准_{field}" for field in fields]


def testExcel日志字段映射导出映射后子规则而不是Excel记录配置(monkeypatch):
    """Excel 行数据不是解析配置，自动下载必须来自本次生成的 mapped_sub_rules。"""
    import agent.tools.rule_generator as rule_generator
    import agent.tools.standard_mapper as standard_mapper
    import application.field_source as field_source

    monkeypatch.setattr(
        field_source,
        "extract_log_fields_for_mapping",
        lambda classification, raw_log_lines: ["alarm_name"],
    )
    monkeypatch.setattr(
        rule_generator,
        "generate_sub_rules",
        lambda classification, all_logs_str, rule_source_fields: [
            {
                "name": "AUDIT",
                "normalize": [
                    {"index": "alarm_name", "field": "", "mappings": []}
                ],
            }
        ],
    )
    monkeypatch.setattr(standard_mapper, "_load_object_mapping", lambda path: {})
    excel_rows = [{"原始日志": 'alarm_name="attack"', "设备": "ips"}]
    session = {
        "decoded_data": copy.deepcopy(excel_rows),
        "raw_log_lines": ['alarm_name="attack"'],
        "log_classification": {
            "status": "SUCCESS",
            "classification_details": [{"logtype": "AUDIT"}],
        },
        "rule_source_fields": {
            "product": "产品",
            "log_vendor": "厂商",
            "data_source": "产品(厂商)",
        },
    }
    facts = build_session_facts(session)
    assert facts.available_config_refs == ()

    result = asyncio.run(
        ProfessionalAgentAdapter(_Team(_MappingMember()), candidate_retriever=lambda fields: "").execute(
            FieldMappingStep(
                step_id="mapping-excel",
                type="field_mapping",
                source_ref="session.fields",
            ),
            ExecutionContext(session=session, session_facts=facts),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.artifact.download_kind == "mapped_sub_rules"
    decoded_download = json.loads(
        base64.b64decode(result.artifact.download_content).decode("utf-8")
    )
    assert decoded_download == session["mapped_sub_rules"]
    downloaded_normalize = decoded_download[0]["normalize"][0]
    assert downloaded_normalize["index"] == "alarm_name"
    assert downloaded_normalize["field"] == "标准_alarm_name"
    assert downloaded_normalize["mappings"] == []
    assert session["decoded_data"] == excel_rows
    assert "原始日志" not in json.dumps(decoded_download, ensure_ascii=False)


def test字段映射无可回填目标时不产出下载(monkeypatch):
    """既无真实配置也无子规则来源时，产物不得携带任何下载契约字段。"""

    session = {"decoded_fields": ["alpha", "beta"]}
    facts = build_session_facts(session)
    assert facts.available_config_refs == ()

    result = asyncio.run(
        ProfessionalAgentAdapter(_Team(_MappingMember()), candidate_retriever=lambda fields: "").execute(
            FieldMappingStep(
                step_id="mapping-only",
                type="field_mapping",
                source_ref="session.fields",
            ),
            ExecutionContext(session=session, session_facts=facts),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.artifact.download_kind is None
    assert result.artifact.download_content is None
    assert "mapped_sub_rules" not in session


class _AsyncMappingMember:
    """通过 Agno 风格异步事件流返回当前批次映射。"""

    name = "FieldMappingAgent"

    def __init__(self) -> None:
        """初始化并发调用统计。"""
        self.active_calls = 0
        self.max_active_calls = 0
        self.call_count = 0

    async def arun(self, model_input, *, stream, stream_events):
        """产生完成事件，并记录同时运行的模型调用数量。"""
        import re

        assert stream is True
        assert stream_events is True
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self.call_count += 1
        match = re.search(r"字段列表（.*?）：\n(\[.*?\])", model_input, re.S)
        fields = json.loads(match.group(1))
        await asyncio.sleep(0.02)
        self.active_calls -= 1
        mappings = [
            {
                "原始字段名": field,
                "系统属性名称": f"标准_{field}",
                "匹配状态": "匹配成功",
            }
            for field in fields
        ]
        yield SimpleNamespace(event="RunCompleted", content=json.dumps(mappings, ensure_ascii=False))


def test字段映射通过异步事件流并发执行三个批次(monkeypatch):
    """51 个字段应形成三个并发批次，且结果按原字段顺序合并。"""

    fields = [f"field_{index:02d}" for index in reversed(range(51))]
    session = {"decoded_fields": fields}
    member = _AsyncMappingMember()
    step = FieldMappingStep(
        step_id="mapping",
        type="field_mapping",
        source_ref="session.fields",
    )
    adapter = ProfessionalAgentAdapter(
        _Team(member),
        candidate_retriever=lambda fields: "",
        mapping_policy=FieldMappingExecutionPolicy(
            batch_size=25,
            max_concurrency=3,
            watchdog_timeout_seconds=1,
            max_retries=0,
            retry_delay_seconds=0,
        ),
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert member.call_count == 3
    assert member.max_active_calls == 3
    assert [row.original_field for row in result.artifact.mappings] == fields


class _BackfillMappingMember:
    """主批次（多字段）漏掉指定字段，补查（单字段）时返回，模拟 LLM 漏字段后补查成功。"""

    name = "FieldMappingAgent"

    def __init__(self, drop_field: str) -> None:
        self.drop_field = drop_field
        self.call_count = 0

    async def arun(self, model_input, *, stream, stream_events):
        import re

        self.call_count += 1
        match = re.search(r"字段列表（.*?）：\n(\[.*?\])", model_input, re.S)
        fields = json.loads(match.group(1))
        if len(fields) > 1:
            fields = [field for field in fields if field != self.drop_field]
        mappings = [
            {"原始字段名": field, "系统属性名称": f"标准_{field}", "匹配状态": "匹配成功"}
            for field in fields
        ]
        yield SimpleNamespace(event="RunCompleted", content=json.dumps(mappings, ensure_ascii=False))


def test字段映射漏字段时补查缺失项后成功(monkeypatch):
    """模型在主批次漏 1 个字段时，补查该字段并合并，整步仍成功（回归 #48）。"""

    fields = [f"field_{index:02d}" for index in range(26)]
    member = _BackfillMappingMember(drop_field="field_01")
    step = FieldMappingStep(step_id="mapping", type="field_mapping", source_ref="session.fields")
    adapter = ProfessionalAgentAdapter(
        _Team(member),
        candidate_retriever=lambda fields: "",
        mapping_policy=FieldMappingExecutionPolicy(
            batch_size=25,
            max_concurrency=3,
            watchdog_timeout_seconds=1,
            max_retries=0,
            retry_delay_seconds=0,
            backfill_max_attempts=2,
        ),
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(
                session={"decoded_fields": fields},
                session_facts=build_session_facts({"decoded_fields": fields}),
            ),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.artifact.item_count == 26
    assert [row.original_field for row in result.artifact.mappings] == fields
    backfilled = next(row for row in result.artifact.mappings if row.original_field == "field_01")
    assert backfilled.standard_field == "标准_field_01"
    assert backfilled.match_status == "匹配成功"


class _AlwaysDroppingMappingMember:
    """总是漏掉指定字段（补查也漏），验证兜底为「未匹配」而非整步失败。"""

    name = "FieldMappingAgent"

    def __init__(self, drop_field: str) -> None:
        self.drop_field = drop_field
        self.call_count = 0

    async def arun(self, model_input, *, stream, stream_events):
        import re

        self.call_count += 1
        match = re.search(r"字段列表（.*?）：\n(\[.*?\])", model_input, re.S)
        fields = json.loads(match.group(1))
        fields = [field for field in fields if field != self.drop_field]
        mappings = [
            {"原始字段名": field, "系统属性名称": f"标准_{field}", "匹配状态": "匹配成功"}
            for field in fields
        ]
        yield SimpleNamespace(event="RunCompleted", content=json.dumps(mappings, ensure_ascii=False))


def test字段映射补查仍缺时兜底未匹配(monkeypatch):
    """补查 backfill_max_attempts 次仍漏字段时，该字段兜底为「未匹配」，整步仍成功。"""

    member = _AlwaysDroppingMappingMember(drop_field="lonely")
    step = FieldMappingStep(step_id="mapping", type="field_mapping", source_ref="session.fields")
    adapter = ProfessionalAgentAdapter(
        _Team(member),
        candidate_retriever=lambda fields: "",
        mapping_policy=FieldMappingExecutionPolicy(
            batch_size=25,
            max_concurrency=3,
            watchdog_timeout_seconds=1,
            max_retries=0,
            retry_delay_seconds=0,
            backfill_max_attempts=2,
        ),
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(
                session={"decoded_fields": ["lonely"]},
                session_facts=build_session_facts({"decoded_fields": ["lonely"]}),
            ),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.artifact.item_count == 1
    row = result.artifact.mappings[0]
    assert row.original_field == "lonely"
    assert row.standard_field == "未匹配"
    assert row.match_status == "未匹配"
    # 主调用 1 次 + 补查 2 次 = 3 次
    assert member.call_count == 3


class _ReorderedMappingMember:
    """返回全部字段但乱序，验证不再因顺序不一致而误判失败。"""

    name = "FieldMappingAgent"

    def __init__(self) -> None:
        self.call_count = 0

    async def arun(self, model_input, *, stream, stream_events):
        import re

        self.call_count += 1
        match = re.search(r"字段列表（.*?）：\n(\[.*?\])", model_input, re.S)
        fields = json.loads(match.group(1))
        mappings = [
            {"原始字段名": field, "系统属性名称": f"标准_{field}", "匹配状态": "匹配成功"}
            for field in reversed(fields)
        ]
        yield SimpleNamespace(event="RunCompleted", content=json.dumps(mappings, ensure_ascii=False))


def test字段映射乱序返回不再判为失败(monkeypatch):
    """旧校验对返回顺序敏感会误判失败；现按集合归一、按输入顺序输出。"""
    import application.field_mapping_input as input_builder

    fields = ["alpha", "beta", "gamma"]
    member = _ReorderedMappingMember()
    step = FieldMappingStep(step_id="mapping", type="field_mapping", source_ref="session.fields")
    adapter = ProfessionalAgentAdapter(
        _Team(member),
        candidate_retriever=lambda fields: "",
        mapping_policy=FieldMappingExecutionPolicy(
            batch_size=25,
            max_concurrency=3,
            watchdog_timeout_seconds=1,
            max_retries=0,
            retry_delay_seconds=0,
            backfill_max_attempts=0,
        ),
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(
                session={"decoded_fields": fields},
                session_facts=build_session_facts({"decoded_fields": fields}),
            ),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert [row.original_field for row in result.artifact.mappings] == fields
    assert member.call_count == 1


class _DuplicateMappingMember:
    """把首个字段重复返回一次，验证去重（保留首条）且不失败。"""

    name = "FieldMappingAgent"

    async def arun(self, model_input, *, stream, stream_events):
        import re

        match = re.search(r"字段列表（.*?）：\n(\[.*?\])", model_input, re.S)
        fields = list(json.loads(match.group(1)))
        if fields:
            fields.append(fields[0])
        mappings = [
            {"原始字段名": field, "系统属性名称": f"标准_{field}", "匹配状态": "匹配成功"}
            for field in fields
        ]
        yield SimpleNamespace(event="RunCompleted", content=json.dumps(mappings, ensure_ascii=False))


def test字段映射重复字段去重后不失败(monkeypatch):
    """模型把某字段重复返回时去重，整步成功且数量与输入一致。"""
    import application.field_mapping_input as input_builder

    fields = ["alpha", "beta"]
    member = _DuplicateMappingMember()
    step = FieldMappingStep(step_id="mapping", type="field_mapping", source_ref="session.fields")
    adapter = ProfessionalAgentAdapter(
        _Team(member),
        candidate_retriever=lambda fields: "",
        mapping_policy=FieldMappingExecutionPolicy(
            batch_size=25,
            max_concurrency=3,
            watchdog_timeout_seconds=1,
            max_retries=0,
            retry_delay_seconds=0,
            backfill_max_attempts=0,
        ),
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(
                session={"decoded_fields": fields},
                session_facts=build_session_facts({"decoded_fields": fields}),
            ),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.artifact.item_count == 2
    assert [row.original_field for row in result.artifact.mappings] == ["alpha", "beta"]


def test字段映射回填解码配置并产出下载(monkeypatch):
    """有真实 decoded_config 时，字段映射回填配置并标记为 mapped_config（回归 #51）。"""
    import agent.tools.standard_mapper as standard_mapper

    monkeypatch.setattr(standard_mapper, "_load_object_mapping", lambda path: {})
    session = {
        "decoded_fields": ["alpha", "beta"],
        # simple_decode 的真实 decoded_json 根对象是规则列表，而不是包装字典。
        "decoded_data": [
            {"name": "r", "normalize": [{"index": "alpha"}, {"index": "beta"}]}
        ],
    }
    member = _AsyncMappingMember()
    step = FieldMappingStep(step_id="mapping", type="field_mapping", source_ref="session.fields")
    adapter = ProfessionalAgentAdapter(
        _Team(member),
        candidate_retriever=lambda fields: "",
        mapping_policy=FieldMappingExecutionPolicy(
            batch_size=25,
            max_concurrency=3,
            watchdog_timeout_seconds=1,
            max_retries=0,
            retry_delay_seconds=0,
            backfill_max_attempts=0,
        ),
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(
                session=session,
                session_facts=build_session_facts(session),
            ),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.artifact.download_kind == "mapped_config"
    assert result.artifact.download_content is not None
    norm = {entry["index"]: entry for entry in session["decoded_data"][0]["normalize"]}
    assert norm["alpha"]["field"] == "标准_alpha"
    assert norm["beta"]["field"] == "标准_beta"
    downloaded = json.loads(
        base64.b64decode(result.artifact.download_content).decode("utf-8")
    )
    assert isinstance(downloaded, list)
    assert downloaded == session["decoded_data"]


def test上传规则字段映射仅处理未映射字段并报告差分():
    """纯上传路径的 LLM 输入、写回与用户消息共用同一语义。"""
    session = {
        "decoded_fields": ["alpha", "beta"],
        "decoded_data": [
            {
                "name": "r",
                "normalize": [
                    {
                        "index": "alpha",
                        "field": "外部标准",
                        "entity": "外部对象",
                        "sim": False,
                        "core": True,
                    },
                    {"index": "beta", "field": ""},
                ],
            }
        ],
    }
    member = _MappingMember()
    adapter = ProfessionalAgentAdapter(
        _Team(member),
        candidate_retriever=lambda fields: "",
        object_map_loader=lambda path: {},
    )

    result = asyncio.run(
        adapter.execute(
            FieldMappingStep(
                step_id="mapping-uploaded",
                type="field_mapping",
                source_ref="session.fields",
            ),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert len(member.calls) == 1
    assert '"beta"' in member.calls[0]
    assert '"alpha"' not in member.calls[0]
    normalized = {entry["index"]: entry for entry in session["decoded_data"][0]["normalize"]}
    assert normalized["alpha"]["field"] == "外部标准"
    assert normalized["alpha"]["entity"] == "外部对象"
    assert normalized["alpha"]["sim"] is False
    assert normalized["alpha"]["core"] is True
    assert normalized["beta"]["field"] == "标准_beta"
    assert "新增映射 1 个" in (result.message or "")
    assert "跳过已映射 1 个（保留原映射）" in (result.message or "")


def test上传规则全部已映射时直接成功且不调模型():
    """全已映射不是无数据，Executor 应放行 Adapter 返回零调用成功。"""
    session = {
        "decoded_fields": ["alpha", "beta"],
        "decoded_data": {
            "normalize": [
                {"index": "alpha", "field": "标准_alpha"},
                {"index": "beta", "field": "标准_beta"},
            ]
        },
        "log_classification": {"classification_details": [{"logtype": "旧分类"}]},
    }
    member = _MappingMember()
    adapter = ProfessionalAgentAdapter(
        _Team(member),
        candidate_retriever=lambda fields: "",
        object_map_loader=lambda path: {},
    )
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "all-mapped",
            "steps": [
                {
                    "step_id": "mapping-all",
                    "type": "field_mapping",
                    "source_ref": "session.fields",
                }
            ],
        }
    )

    report = asyncio.run(
        PlanExecutor({"field_mapping": adapter}).execute(
            decision,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )

    assert report.status == StepStatus.SUCCESS
    assert member.calls == []
    assert report.results[0].artifact is None
    assert "所有字段均已映射，无需再次执行" in (report.results[0].message or "")


def test字段映射一对一冲突裁决后仅写回保留者():
    """Adapter 在任何 apply 前裁决，并让 Session、Artifact 与消息保持一致。"""
    class CollisionMember:
        name = "FieldMappingAgent"

        def __init__(self):
            self.calls = []

        def run(self, model_input):
            self.calls.append(model_input)
            return [
                {"原始字段名": "src", "系统属性名称": "源IP", "匹配状态": "匹配成功"},
                {"原始字段名": "client", "系统属性名称": "源IP", "匹配状态": "匹配成功"},
            ]

    candidate_calls = []

    def retrieve(fields):
        candidate_calls.append(tuple(fields))
        return "\n".join(
            [
                "## 标准字段候选（语义检索 top-5，按相似度降序）：",
                "src → 源IP(0.91, source_ip)",
                "client → 源IP(1.00, client)",
            ]
        )

    session = {
        "decoded_fields": ["src", "client"],
        "decoded_data": {
            "normalize": [
                {"index": "src", "field": ""},
                {"index": "client", "field": ""},
            ]
        },
    }
    member = CollisionMember()
    result = asyncio.run(
        ProfessionalAgentAdapter(
            _Team(member),
            candidate_retriever=retrieve,
            object_map_loader=lambda _path: {},
        ).execute(
            FieldMappingStep(
                step_id="mapping-conflict", type="field_mapping", source_ref="session.fields"
            ),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert len(member.calls) == 1
    assert candidate_calls == [("src", "client"), ("src", "client")]
    assert [row["匹配状态"] for row in session["last_mapping_data"]] == [
        "未匹配",
        "匹配成功",
    ]
    normalized = {entry["index"]: entry for entry in session["decoded_data"]["normalize"]}
    assert normalized["src"].get("field", "") == ""
    assert normalized["client"]["field"] == "源IP"
    assert [row.match_status for row in result.artifact.mappings] == ["未匹配", "匹配成功"]
    assert "检测到 1 组占用冲突，保留 1 个、1 个置未匹配" in (result.message or "")
    assert "源IP：保留 client；落选 src；依据：精确命中（1.00）" in (result.message or "")


def test字段映射新行撞上传配置既有标准字段时落选():
    """#163 跳过的既有映射是只读占用方，新行即使精确命中也不能覆盖或撞入。"""
    from application.adapters.field_mapping import FieldMappingAdapter

    class ExistingCollisionRunner:
        async def run(self, fields, **_kwargs):
            assert list(fields) == ["client_ip"]
            return [
                {
                    "原始字段名": "client_ip",
                    "系统属性名称": "源IP",
                    "匹配状态": "匹配成功",
                }
            ]

    session = {
        "decoded_fields": ["external_src", "client_ip"],
        "decoded_data": {
            "normalize": [
                {
                    "index": "external_src",
                    "field": "源IP",
                    "entity": "外部对象",
                    "sim": False,
                    "core": True,
                },
                {"index": "client_ip", "field": ""},
            ]
        },
    }
    result = asyncio.run(
        FieldMappingAdapter(
            team=None,
            batch_runner=ExistingCollisionRunner(),
            candidate_retriever=lambda fields: "client_ip → 源IP(1.00, client_ip)",
            object_map_loader=lambda _path: {},
        ).execute(
            FieldMappingStep(
                step_id="mapping-existing-conflict",
                type="field_mapping",
                source_ref="session.fields",
            ),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    normalized = {entry["index"]: entry for entry in session["decoded_data"]["normalize"]}
    assert result.status == StepStatus.SUCCESS
    assert normalized["external_src"] == {
        "index": "external_src",
        "field": "源IP",
        "entity": "外部对象",
        "sim": False,
        "core": True,
    }
    assert normalized["client_ip"].get("field", "") == ""
    assert session["last_mapping_data"][0]["匹配状态"] == "未匹配"
    assert "保留 external_src；落选 client_ip；依据：既有上传映射占用" in (
        result.message or ""
    )


def test威胁映射依赖产物不是枚举值时失败():
    """依赖步骤产物不是 EnumValuesArtifact 时返回 dependency_type_mismatch（回归 #38）。"""
    from contracts.planner_models import ConfigExportArtifact, StepResult, ThreatMappingStep

    step = ThreatMappingStep(
        step_id="threat",
        type="threat_mapping",
        source_ref="step:enum",
        depends_on=("enum",),
    )
    bad_dependency = StepResult(
        step_id="enum",
        operation_type="enum_extract",
        status=StepStatus.SUCCESS,
        artifact=ConfigExportArtifact(content="e30=", item_count=1),
    )
    adapter = ProfessionalAgentAdapter(_Team(None))
    session = {}

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {"enum": bad_dependency},
        )
    )

    assert result.status == StepStatus.FAILED
    assert result.error_code == "dependency_type_mismatch"


def test三步复合真实链路依次传递账本并产出唯一导出(monkeypatch):
    """enum_extract→threat_mapping→threat_fill 经真实执行器链式传递本次账本，
    威胁填充真实改变配置，最终一次汇总 + 一个下载文件（回归 #39）。"""
    import agent.tools.pipeline.llm_client as llm_client
    import web.plan_renderer as renderer
    from application.execution import ExecutionContext, PlanExecutor
    from contracts.planner_models import (
        ConfigExportArtifact,
        EnumValuesArtifact,
        PlanDecision,
        ThreatMappingArtifact,
    )
    from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot

    monkeypatch.setattr(
        llm_client,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps(
            {"field": "event_type3", "regex": r"event_type3=(\w+)"}, ensure_ascii=False
        ),
    )

    class _ThreatMember:
        """同步返回预设威胁映射的测试替身。"""

        name = "ThreatAgent"

        def __init__(self, response):
            self._response = response

        def run(self, model_input):
            return self._response

    team = _Team(
        _ThreatMember(
            json.dumps(
                [
                    {"mappingType": "EQUAL", "orgValue": "attack", "mappingValue": "恶意活动"},
                    {"mappingType": "EQUAL", "orgValue": "scan", "mappingValue": "扫描"},
                ],
                ensure_ascii=False,
            )
        )
    )
    session = {
        "raw_log_lines": ["event_type3=attack src=10.0.0.1", "event_type3=scan src=10.0.0.2"],
        "decoded_fields": ["event_type3"],
        "decoded_data": [{"name": "rule-1", "normalize": [{"index": "event_type3", "mappings": []}]}],
    }
    decision = PlanDecision.model_validate(
        {
            "decision": "execute",
            "plan_id": "composite",
            "steps": [
                {
                    "step_id": "extract",
                    "type": "enum_extract",
                    "target_field": "event_type3",
                    "source_ref": "session.logs",
                },
                {
                    "step_id": "threat",
                    "type": "threat_mapping",
                    "source_ref": "step:extract",
                    "depends_on": ["extract"],
                },
                {
                    "step_id": "fill",
                    "type": "fill",
                    "fill_kind": "threat",
                    "target_fields": ["event_type3"],
                    "source_ref": "step:threat",
                    "config_ref": "session.decoded_config",
                    "depends_on": ["threat"],
                },
            ],
        }
    )

    report = asyncio.run(
        PlanExecutor(create_default_adapters(team)).execute(
            decision,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
        )
    )

    # 三步全部成功，账本依次传递正确类型的产物（威胁映射消费枚举值、填充消费威胁映射）。
    assert report.status == StepStatus.SUCCESS
    assert [result.operation_type for result in report.results] == [
        "enum_extract",
        "threat_mapping",
        "fill",
    ]
    assert isinstance(report.results[0].artifact, EnumValuesArtifact)
    assert set(report.results[0].artifact.values) == {"attack", "scan"}
    assert report.results[0].artifact.field == "event_type3"
    assert report.results[0].artifact.regex
    assert report.results[0].artifact.original_log
    assert isinstance(report.results[1].artifact, ThreatMappingArtifact)
    assert isinstance(session["latest_enum_artifact"], EnumArtifactSlot)
    assert session["latest_enum_artifact"].source_field == "event_type3"
    assert isinstance(session["latest_threat_artifact"], ThreatArtifactSlot)
    assert session["latest_threat_artifact"].source_field == "event_type3"
    assert isinstance(report.results[2].artifact, ConfigExportArtifact)
    assert report.results[2].artifact.download_kind == "threatmapping_config"
    assert report.results[2].changed_count == 2
    # 威胁填充真实写回目标字段 mappings。
    mappings = session["decoded_data"][0]["normalize"][0]["mappings"]
    assert {mapping["orgValue"] for mapping in mappings} == {"attack", "scan"}

    # 渲染：复合计划的全部产物进入同一条汇总消息（无字段映射回填的第二条消息）。
    sent_messages = []
    dataframe_count = {"count": 0}

    class _File:
        def __init__(self, *, name, content, mime, **_kwargs):
            self.name = name

    class _Message:
        def __init__(self, *, content, elements):
            self.content = content
            self.elements = elements

        async def send(self):
            sent_messages.append(self)

    def _dataframe(**_kwargs):
        dataframe_count["count"] += 1
        return SimpleNamespace()

    monkeypatch.setattr(renderer.cl, "File", _File)
    monkeypatch.setattr(renderer.cl, "Message", _Message)
    monkeypatch.setattr(renderer.cl, "Dataframe", _dataframe)
    monkeypatch.setattr(
        renderer,
        "datetime",
        SimpleNamespace(now=lambda: datetime(2026, 8, 18, 10, 6)),
    )
    asyncio.run(renderer.render_execution_report(report))

    # 一条汇总消息；枚举值/威胁映射落表，配置导出附下载文件。
    assert len(sent_messages) == 1
    assert dataframe_count["count"] == 2
    file_names = {element.name for element in sent_messages[0].elements if hasattr(element, "name")}
    assert file_names == {
        "enumvalues_20260818_1006.json",
        "threatmapping_20260818_1006.xlsx",
        "threatmapping_config_20260818_1006.txt",
    }


class _TimeoutMappingMember:
    """模拟永不在超时前完成的专业 Agent。"""

    name = "FieldMappingAgent"

    def __init__(self) -> None:
        """初始化调用与取消计数。"""
        self.call_count = 0
        self.cancel_count = 0

    async def arun(self, model_input, *, stream, stream_events):
        """等待取消，用于验证超时和原子失败。"""
        self.call_count += 1
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancel_count += 1
            raise
        if False:
            yield SimpleNamespace(event="RunCompleted", content="[]")


def test字段映射禁用拆分时批次超时且不写入部分结果(monkeypatch):
    """任一批次超时应取消剩余任务，并保持 session 原子不变。"""
    import application.field_mapping_input as input_builder

    session = {"decoded_fields": [f"field_{index:02d}" for index in range(51)]}
    member = _TimeoutMappingMember()
    adapter = ProfessionalAgentAdapter(
        _Team(member),
        candidate_retriever=lambda fields: "",
        mapping_policy=FieldMappingExecutionPolicy(
            batch_size=25,
            max_concurrency=3,
            watchdog_timeout_seconds=0.02,
            max_retries=1,
            retry_delay_seconds=0,
            max_timeout_split_depth=0,
        ),
    )
    step = FieldMappingStep(
        step_id="mapping-timeout",
        type="field_mapping",
        source_ref="session.fields",
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.FAILED
    assert result.error_code == "field_mapping_timeout"
    assert member.call_count == 3
    assert member.cancel_count == 3
    assert "last_mapping_data" not in session
    assert "mapped_sub_rules" not in session



def test字段映射291字段形成12批且最大并发为3(monkeypatch):
    """291 个字段必须按 25 个一批执行，且并发上限固定为三批。"""
    import application.field_mapping_input as input_builder

    fields = [f"field_{index:03d}" for index in range(291)]
    session = {"decoded_fields": fields}
    member = _AsyncMappingMember()
    adapter = ProfessionalAgentAdapter(
        _Team(member),
        candidate_retriever=lambda fields: "",
        mapping_policy=FieldMappingExecutionPolicy(
            batch_size=25,
            max_concurrency=3,
            watchdog_timeout_seconds=1,
            max_retries=0,
            retry_delay_seconds=0,
        ),
    )
    step = FieldMappingStep(
        step_id="mapping-291",
        type="field_mapping",
        source_ref="session.fields",
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert member.call_count == 12
    assert member.max_active_calls == 3
    assert [row.original_field for row in result.artifact.mappings] == fields


class _PermanentMappingErrorMember:
    """模拟不应重试的本地结构错误。"""

    name = "FieldMappingAgent"

    def __init__(self) -> None:
        """初始化调用计数。"""
        self.call_count = 0

    async def arun(self, model_input, *, stream, stream_events):
        """立即抛出不可重试的 ValueError。"""
        self.call_count += 1
        raise ValueError("invalid local response")
        if False:
            yield None


def test字段映射不可重试错误只调用一次(monkeypatch):
    """非连接、限流、服务端或超时错误不得浪费第二次模型调用。"""
    import application.field_mapping_input as input_builder

    session = {"decoded_fields": ["field_a"]}
    member = _PermanentMappingErrorMember()
    adapter = ProfessionalAgentAdapter(
        _Team(member),
        candidate_retriever=lambda fields: "",
        mapping_policy=FieldMappingExecutionPolicy(
            watchdog_timeout_seconds=1,
            max_retries=1,
            retry_delay_seconds=0,
        ),
    )
    step = FieldMappingStep(
        step_id="mapping-invalid",
        type="field_mapping",
        source_ref="session.fields",
    )

    result = asyncio.run(
        adapter.execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.FAILED
    assert result.error_code == "field_mapping_model_failed"
    assert member.call_count == 1

def test字段映射写回阶段异常时不留下部分状态(monkeypatch):
    """子规则计算失败时不得提前写入 last_mapping_data 或中间映射结果。"""
    import agent.tools.rule_generator.field_mapping as field_mapping_module


    def fail_writeback(*args, **kwargs):
        """模拟写回前的领域计算异常。"""
        raise RuntimeError("writeback failed")

    monkeypatch.setattr(
        field_mapping_module,
        "apply_field_mapping_to_sub_rules",
        fail_writeback,
    )
    session = {
        "decoded_fields": ["field_a"],
        "mapped_sub_rules": [
            {"name": "rule-a", "normalize": [{"index": "field_a", "field": ""}]}
        ],
    }
    member = _AsyncMappingMember()
    step = FieldMappingStep(
        step_id="mapping-writeback-failed",
        type="field_mapping",
        source_ref="session.fields",
    )

    try:
        asyncio.run(
            ProfessionalAgentAdapter(_Team(member), candidate_retriever=lambda fields: "").execute(
                step,
                ExecutionContext(session=session, session_facts=build_session_facts(session)),
                {},
            )
        )
    except RuntimeError as error:
        assert str(error) == "writeback failed"
    else:
        raise AssertionError("预期子规则计算异常向执行核心传播")

    assert "last_mapping_data" not in session
    assert "sub_rule_mapping_results" not in session
    assert session["mapped_sub_rules"][0]["normalize"][0]["field"] == ""

def test字段映射Agent不再挂载业务工具(monkeypatch):
    """字段映射 Agent 应只生成结构化映射，不在模型循环中回写配置。"""
    from agno.models.deepseek import DeepSeek
    from agent.core import team as team_module

    monkeypatch.setattr(
        team_module.ModelConfig,
        "get_main_model",
        lambda: DeepSeek(id="deepseek-chat", api_key="test-key"),
    )

    agent = team_module.create_field_mapping_agent()

    assert not agent.tools
    assert agent.output_schema is team_module.FieldMappingList

def test入口规则导出按钮与自然语言共用ExportAdapter(monkeypatch):
    """验证日志分类导出由类型化来源决定，不在按钮回调内执行领域函数。"""
    import agent.tools.rule_generator as rule_generator

    calls = []
    monkeypatch.setattr(
        rule_generator,
        "generate_rules",
        lambda classification, mode, rule_source_fields: calls.append(
            (mode, rule_source_fields)
        )
        or {"success": True, "rules": [{"name": "entry"}]},
    )
    monkeypatch.setattr(
        rule_generator,
        "rules_to_base64_text",
        lambda rules: "encoded-entry-rules",
    )
    from contracts.rule_source import RuleSourceFields

    source_fields = RuleSourceFields.create(product="产品", log_vendor="厂商")
    session = {
        "log_classification": {"类型A": {}},
        "rule_source_fields": source_fields,
    }
    step = ExportStep(
        step_id="export-entry",
        type="export",
        source_ref="session.log_classification.entry_rules",
    )

    result = asyncio.run(
        ExportAdapter().execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.artifact.content == "encoded-entry-rules"
    assert result.artifact.item_count == 1
    assert result.artifact.download_kind == "mappedconfig_mainrules"
    assert calls == [("entry", source_fields)]


def test日志分类规则导出缺少数据源字段时统一gate并记住步骤():
    """按钮和自然语言入口必须共享同一 needs_input 与续跑状态。"""
    session = {"log_classification": {"类型A": {}}}
    step = ExportStep(
        step_id="export-entry-missing-source",
        type="export",
        source_ref="session.log_classification.entry_rules",
    )

    result = asyncio.run(
        ExportAdapter().execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.NEEDS_INPUT
    assert result.error_code == "data_source_fields_required"
    assert session["pending_rule_source_step"] is step
    assert result.artifact is None


def test未映射子规则导出保留明确下载语义(monkeypatch):
    """日志分类子规则导出使用未映射子规则文件名语义。"""
    import agent.tools.rule_generator as rule_generator

    calls = []
    monkeypatch.setattr(
        rule_generator,
        "generate_rules",
        lambda classification, mode, rule_source_fields: calls.append(
            (mode, rule_source_fields)
        )
        or {"success": True, "rules": [{"name": "sub"}]},
    )
    monkeypatch.setattr(
        rule_generator,
        "rules_to_base64_text",
        lambda rules: "encoded-sub-rules",
    )
    from contracts.rule_source import RuleSourceFields

    source_fields = RuleSourceFields.create(product="产品", log_vendor="厂商")
    session = {
        "log_classification": {"类型A": {}},
        "rule_source_fields": source_fields,
    }
    step = ExportStep(
        step_id="export-sub",
        type="export",
        source_ref="session.log_classification.sub_rules",
    )

    result = asyncio.run(
        ExportAdapter().execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    assert result.artifact.content == "encoded-sub-rules"
    assert result.artifact.download_kind == "unmappedconfig_subrules"
    assert calls == [("sub", source_fields)]


def test标准字段映射生成日志子规则前要求数据源字段():
    """缺值时必须在模型调用前停止，并保存可续跑的原步骤。"""
    from application.adapters.field_mapping import FieldMappingAdapter

    class NeverRun:
        async def run(self, *args, **kwargs):
            raise AssertionError("缺少数据源字段时不应调用字段映射模型")

    session = {
        "decoded_fields": ["src_ip"],
        "log_classification": {"classification_details": [{"logtype": "审计"}]},
    }
    step = FieldMappingStep(
        step_id="mapping-missing-source",
        type="field_mapping",
        source_ref="session.fields",
    )

    result = asyncio.run(
        FieldMappingAdapter(team=None, batch_runner=NeverRun()).execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.NEEDS_INPUT
    assert result.error_code == "data_source_fields_required"
    assert session["pending_rule_source_step"] is step


def test已有映射结果时白板子规则导出被统一gate拦截(monkeypatch):
    """按钮与 Planner 共用的导出接缝不得重建并下载白板子规则。"""
    import agent.tools.rule_generator as rule_generator

    calls = []
    monkeypatch.setattr(
        rule_generator,
        "generate_rules",
        lambda classification, mode: calls.append((classification, mode)),
    )
    session = {
        "log_classification": {"类型A": {}},
        "mapped_sub_rules": [
            {
                "name": "类型A",
                "normalize": [{"index": "alarm_name", "field": "事件名称"}],
            }
        ],
    }
    step = ExportStep(
        step_id="export-whiteboard",
        type="export",
        source_ref="session.log_classification.sub_rules",
    )

    result = asyncio.run(
        ExportAdapter().execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.NEEDS_INPUT
    assert result.error_code == "mapped_sub_rules_present"
    assert "映射" in result.message
    assert "事件标注" in result.message
    assert "手动调整" in result.message
    assert "生成映射后子规则" in result.message
    assert result.artifact is None
    assert calls == []


def test映射后子规则导出消费mapped_sub_rules而不是重新生成配置(monkeypatch):
    """映射后子规则导出应保留字段映射结果，并通过统一配置产物编码。"""
    import base64
    import json

    session = {
        "mapped_sub_rules": [
            {
                "name": "AUDIT",
                "normalize": [{"index": "alarm_name", "field": "事件名称"}],
            }
        ]
    }
    step = ExportStep(
        step_id="export-mapped",
        type="export",
        source_ref="session.mapped_sub_rules",
    )

    result = asyncio.run(
        ExportAdapter().execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )

    assert result.status == StepStatus.SUCCESS
    decoded = json.loads(base64.b64decode(result.artifact.content).decode("utf-8"))
    assert decoded[0]["normalize"][0]["field"] == "事件名称"
    assert result.artifact.download_kind == "mappedconfig_subrules"
