"""枚举映射附件生命周期测试（#400）。

覆盖：
- 解析规则（主数据）上传保留枚举映射附件，其余派生状态照旧清空；
- 显式清空命令全清（含枚举附件）；
- 同消息两顺序上传后枚举表均可用、一次填充成功；
- 填充目标字段与配置零匹配时稳定失败且不写配置。
"""

from __future__ import annotations

import asyncio

from application.session_state import PrimaryDatasetSnapshot, SessionState
from application.enum_mapping_attachments import commit_enum_mapping_attachment
from application.file_input import commit_primary_dataset
from application.request_runtime import clear_session_data
from application.execution import ExecutionContext
from application.session_projection import build_session_facts
from application.adapters.enum_fill import EnumFillAdapter
from contracts.planner_models import FillStep, StepStatus


def _parser_snapshot(file_name: str) -> PrimaryDatasetSnapshot:
    return PrimaryDatasetSnapshot(
        decoded_data=[{"name": file_name, "normalize": []}],
        decoded_fields=["a"],
        original_log=None,
        simplified_data={},
        decoded_text="",
        uploaded_file_name=file_name,
        uploaded_file_time="00:00:00",
    )


def _enum_sheets(target_field: str = "威胁类型") -> dict[str, list[dict]]:
    return {
        target_field: [
            {"mappingType": "EQUAL", "orgValue": f"org{i}", "mappingValue": f"map{i}"}
            for i in range(3)
        ]
    }


def _config_with_target() -> list[dict]:
    return [
        {
            "name": "规则一",
            "normalize": [{"index": "威胁类型", "field": "threat_type", "mappings": []}],
            "parser": {"filter": []},
        }
    ]


def _upload_parser(session: SessionState, file_name: str = "规则.txt") -> None:
    commit_primary_dataset(session, _parser_snapshot(file_name))


def _upload_enum(session: SessionState, target_field: str = "威胁类型") -> None:
    commit_enum_mapping_attachment(session, "枚举.xlsx", _enum_sheets(target_field))


def _run_fill(session: SessionState, target_fields=("威胁类型",)):
    step = FillStep(
        step_id="enum-fill", type="fill", fill_kind="enum",
        target_fields=tuple(target_fields),
        source_ref="session.enum_mapping_table",
        config_ref="session.decoded_config",
    )
    return asyncio.run(EnumFillAdapter().execute(
        step,
        ExecutionContext(session=session, session_facts=build_session_facts(session)),
        {},
    ))


def test解析规则上传保留枚举映射附件():
    """#400：主数据替换只清主数据派生状态，枚举映射附件独立保留。"""
    session = SessionState()
    _upload_enum(session)
    _upload_parser(session, "新规则.txt")

    assert session.enum_preview
    assert session.enum_mapping_sheets == _enum_sheets()
    assert session.decoded_data == [{"name": "新规则.txt", "normalize": []}]
    # 主数据派生状态照旧清空（#101 语义收窄而非回退）
    session.last_mapping_data = {"old": True}
    session.last_threat_data = [{"old": True}]
    session.last_enum_extract_result = {"old": True}
    _upload_parser(session, "再新规则.txt")
    assert session.last_mapping_data is None
    assert session.last_threat_data is None
    assert session.last_enum_extract_result is None


def test同消息两顺序上传后一次填充成功():
    """#400：解析规则先/后两种顺序，枚举表都可用且一次填充生效。"""
    for order in ("parser_first", "excel_first"):
        session = SessionState()
        if order == "parser_first":
            _upload_parser(session)
            _upload_enum(session)
        else:
            _upload_enum(session)
            _upload_parser(session)
        assert len(session.enum_preview) == 3

        session.decoded_data = _config_with_target()
        result = _run_fill(session)
        assert result.status == StepStatus.SUCCESS, (order, result)
        assert result.changed_count == 3
        entry = session.decoded_data[0]["normalize"][0]
        assert len(entry["mappings"]) == 3


def test显式清空命令清除枚举映射附件():
    """#400：清空数据/切换文件的显式重置保留全清语义。"""
    session = SessionState()
    _upload_enum(session)
    clear_session_data(session)
    assert session.enum_preview is None
    assert session.enum_mapping_sheets == {}
    assert session.enum_excel_path is None
    assert session.enum_fill_contributions == {}


def test填充目标字段与配置零匹配时稳定失败不写配置():
    """#400：Sheet 名在配置中无同名字段时稳定失败，绝不静默错位写入。"""
    session = SessionState()
    session.decoded_data = _config_with_target()
    _upload_enum(session, target_field="威胁信息")

    before = [dict(e) for e in session.decoded_data[0]["normalize"]]
    result = _run_fill(session, target_fields=("威胁信息",))

    assert result.status == StepStatus.FAILED
    assert result.error_code == "enum_target_field_mismatch"
    assert session.decoded_data[0]["normalize"] == before
