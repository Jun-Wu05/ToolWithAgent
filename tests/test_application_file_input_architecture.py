"""Issue #141：Application 文件输入与上传解码契约。"""

from __future__ import annotations

import ast
import base64
import json
from pathlib import Path

import pytest


def _import_roots(path: Path) -> set[str]:
    """读取静态导入根，阻止 Application 反向依赖界面或 Agent 实现。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test上传解码由application唯一实现且web直接调用() -> None:
    """Web 直接跨 Application 接缝，迁移入口不再重导出。"""
    root = Path(__file__).parents[1]
    module_path = root / "application/file_input.py"
    assert module_path.exists()
    assert _import_roots(module_path).isdisjoint({"agent", "web", "chainlit"})

    agent_source = (root / "agent/core/agent.py").read_text(encoding="utf-8")
    web_source = (root / "web/file_handler.py").read_text(encoding="utf-8")
    upload_source = (root / "web/file_handlers.py").read_text(encoding="utf-8")
    assert "def simple_decode" not in agent_source
    assert "simple_decode" not in agent_source
    assert "simple_decode" not in web_source
    assert "simple_decode" in upload_source
    assert "def _commit_primary_dataset" not in upload_source


@pytest.mark.parametrize("encoded", (False, True))
def test文件输入接受直接json与base64_json且保持根结构(encoded: bool) -> None:
    """只有解码后可验证为 JSON 的 Base64 才进入配置路径。"""
    from application.file_input import simple_decode

    payload = [
        {
            "name": "规则一",
            "normalize": [
                {"index": "src_ip"},
                {"index": "original_log", "result": ["源日志"]},
            ],
        }
    ]
    text = json.dumps(payload, ensure_ascii=False)
    content = (
        base64.b64encode(text.encode("utf-8")).decode("ascii") if encoded else text
    )

    result = simple_decode(content)

    assert result == {
        "status": "success",
        "decoded_json": payload,
        "decoded_text": text,
        "fields": ["src_ip", "original_log"],
        "original_log": ["源日志"],
        "field_count": 2,
    }


def testapplication文件输入原子替换主数据并保留模型配置() -> None:
    """成功快照使附件与派生结果失效，但不影响会话级模型配置。"""
    from application.file_input import commit_primary_dataset
    from application.session_state import PrimaryDatasetSnapshot
    from factories import make_session_state
    from contracts.planner_models import EnumValuesArtifact, ExportStep
    from contracts.rule_source import RuleSourceFields
    from contracts.session_artifacts import EnumArtifactSlot

    session = make_session_state(
        team=object(),
        current_provider="deepseek",
        api_key="configured",
        model_name="model-a",
        decoded_data={"name": "old"},
        enum_excel_path="old.xlsx",
        enum_preview=[{"目标字段": "old"}],
        mapped_sub_rules=[{"name": "old"}],
        latest_enum_artifact=EnumArtifactSlot(
            artifact=EnumValuesArtifact(values=("old",), item_count=1, field="old"),
            source_field="old",
        ),
        rule_source_fields=RuleSourceFields.create(
            product="旧产品", log_vendor="旧厂商"
        ),
        pending_rule_source_step=ExportStep(
            step_id="old-export",
            type="export",
            source_ref="session.log_classification.entry_rules",
        ),
    )
    team = session.team
    snapshot = PrimaryDatasetSnapshot(
        decoded_data={"normalize": [{"index": "src_ip"}]},
        decoded_fields=["src_ip"],
        original_log=["src_ip=1"],
        simplified_data={"fields": ["src_ip"], "original_log_sample": "src_ip=1"},
        decoded_text='{"normalize":[{"index":"src_ip"}]}',
        uploaded_file_name="new.txt",
        uploaded_file_time="12:00:00",
        raw_base64="encoded",
    )

    commit_primary_dataset(session, snapshot)

    assert session.decoded_data == snapshot.decoded_data
    assert session.enum_excel_path is None
    assert session.enum_preview is None
    assert session.mapped_sub_rules is None
    assert session.latest_enum_artifact is None
    assert session.rule_source_fields is None
    assert session.pending_rule_source_step is None
    assert session.team is team
    assert (session.current_provider, session.api_key, session.model_name) == (
        "deepseek",
        "configured",
        "model-a",
    )


def testbase64解码结果不是json时按原始文本回退() -> None:
    """可解码不等于配置；非 JSON Base64 必须保留编码原文。"""
    from application.file_input import simple_decode

    encoded = base64.b64encode("src_ip=1.1.1.1".encode()).decode("ascii")

    result = simple_decode(encoded)

    assert result["status"] == "success"
    assert result["decoded_text"] == encoded
    assert result["decoded_json"] == {"raw_text": encoded}
    assert result["original_log"] == [encoded]


def test纯文本过滤空行和分隔线并限制日志行与预览长度() -> None:
    """纯文本主数据保留前 5000 条有效行，raw_text 预览保持 1000 字符。"""
    from application.file_input import simple_decode

    text = "\n".join(["---", "", *(f"log-{index}" for index in range(5002))])

    result = simple_decode(text)

    assert result["status"] == "success"
    assert result["decoded_json"] == {"raw_text": text[:1000]}
    assert len(result["original_log"]) == 5000
    assert result["original_log"][0] == "log-0"
    assert result["original_log"][-1] == "log-4999"


def test空白文件保持稳定错误且不产生部分结果() -> None:
    """空输入在提交主数据前失败关闭。"""
    from application.file_input import simple_decode

    assert simple_decode(" \r\n\t ") == {
        "status": "error",
        "error_message": "输入为空",
    }


def test历史simple_encode保持独立字典与默认json字节契约() -> None:
    """本次迁移不得建立通用 Codec 或改变其他编码入口。"""
    from agent.core.agent import simple_encode

    payload = {"中文": "值", "items": [1, 2]}
    expected_text = json.dumps(payload, ensure_ascii=False)

    assert simple_encode(payload) == {
        "status": "success",
        "encoded": base64.b64encode(expected_text.encode("utf-8")).decode("utf-8"),
    }
    assert "simple_encode" not in Path(
        __file__
    ).parents[1].joinpath("application/file_input.py").read_text(encoding="utf-8")
