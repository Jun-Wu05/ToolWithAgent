"""Regression for independent filled-config and entry-rule exports in one real Run."""
import base64
from datetime import datetime
from io import BytesIO
import json
from types import SimpleNamespace

from openpyxl import Workbook

from application.adapters.composition import create_default_adapters
from application.adapters.field_mapping import FieldMappingAdapter
from application.adapters.log_parse import LogParseAdapter
from contracts.download_naming import download_filename
from contracts.planner_models import PlanDecision
from toolwithagent_v2.runtime.business_application import BusinessApplication
from toolwithagent_v2.runtime.worker import Worker
from test_postprocessing import current, setup, upload
# Reuse the autouse fixture in addition to the offline runner's global deny.
from test_postprocessing_runtime_independent import forbid_production_planner_and_model_http


def test_fill_subrules_then_export_entry_keeps_configuration_download_independent(tmp_path):
    class CompoundPlanner:
        calls = 0
        async def plan(self, **kwargs):
            self.calls += 1
            return PlanDecision.model_validate({"decision": "execute", "plan_id": "separate-exports", "steps": [
                {"step_id": "fill", "type": "fill", "fill_kind": "enum", "target_fields": ["源地址"],
                 "source_ref": "session.enum_mapping_table", "config_ref": "session.mapped_sub_rules"},
                {"step_id": "entry", "type": "export", "source_ref": "session.log_classification.entry_rules"}]})

    class FieldMember:
        name = "FieldMappingAgent"
        async def arun(self, prompt, **kwargs):
            yield SimpleNamespace(event="RunCompleted", content=[
                {"原始字段名": "src", "系统属性名称": "源地址", "匹配状态": "匹配成功"},
                {"原始字段名": "kind", "系统属性名称": "未匹配", "匹配状态": "未匹配"}])

    classification = {"status": "SUCCESS", "log_format": "KV", "feature_field": "kind",
        "analysis": {"has_key_value_pairs": True, "delimit": " ", "tab": "="},
        "classification_details": [{"logtype": "a", "count": 3, "real_samples": "kind=a src=1"}],
        "fixture_metadata": {"unknown_key": "中文分类扩展"}}

    async def events(prompt):
        fence = chr(96) * 3
        rows = json.loads(prompt.split("## 待判定子规则\n" + fence + "json\n")[1].split("\n" + fence)[0])
        return json.dumps({"results": [{"rule_name": row["rule_name"], "event_name": "登录事件", "group": "non_threat"} for row in rows]}, ensure_ascii=False)

    def adapters(team):
        result = create_default_adapters(team)
        result["field_mapping"] = FieldMappingAdapter(team, candidate_retriever=lambda _: {}, event_classifier=events)
        result["log_parse"] = LogParseAdapter(
            format_identifier=lambda _: json.dumps({"format": "KV", "feature_field": "kind"}),
            classifier=lambda *args, **kwargs: json.dumps(classification),
            sample_filler=lambda data, _: data)
        return result

    planner = CompoundPlanner()
    client, store, conversation, _ = setup(tmp_path, planner)
    business = BusinessApplication(store.path, team_factory=lambda: SimpleNamespace(members=(FieldMember(),)),
        adapters_factory=adapters, planner=planner)
    worker = Worker(store, "worker", business_application=business)
    source = upload(client, conversation, "logs.txt", b"kind=a src=1\nkind=a src=2\nkind=a src=3\n")
    assert worker.once()
    response = client.post(f"/api/v2/conversations/{conversation}/log-parse", json={"file_id": source["file"]["id"]})
    assert response.status_code == 201, response.text
    assert worker.once()
    parsed = current(store, conversation, "log_classification")
    parsed_content = client.get(f"/api/v2/artifacts/{parsed['id']}/content").json()
    assert parsed_content["classification"]["fixture_metadata"]["unknown_key"] == "中文分类扩展"
    response = client.post(f"/api/v2/conversations/{conversation}/field-mapping",
        json={"classification_artifact_id": parsed["id"], "product": "中文设备", "log_vendor": "中文厂商"})
    assert response.status_code == 201, response.text
    assert worker.once()
    assert store.get_run("dev-user", response.json()["run"]["id"])["status"] == "succeeded"
    before = current(store, conversation, "field_mapping")
    before_config = client.get(f"/api/v2/artifacts/{before['id']}/content").json()["config"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "源地址"
    sheet.append(["mappingType", "orgValue", "mappingValue"])
    sheet.append(["EQUAL", "1", "中文地址甲"])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    upload(client, conversation, "enum.xlsx", output.getvalue(), "enum_mapping")
    assert worker.once()
    message = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "填充源地址枚举，然后单独导出入口规则"})
    assert message.status_code == 201, message.text
    assert worker.once()
    run = message.json()["run"]["id"]
    assert store.get_run("dev-user", run)["status"] == "succeeded"
    assert planner.calls == 1
    mapped = current(store, conversation, "field_mapping")
    exported = current(store, conversation, "config_export")
    assert mapped["run_id"] == exported["run_id"] == run
    payload = client.get(f"/api/v2/artifacts/{mapped['id']}/content").json()
    export_payload = client.get(f"/api/v2/artifacts/{exported['id']}/content").json()
    assert any(row["mappingValue"] == "中文地址甲" for rule in payload["config"] for entry in rule["normalize"] for row in entry.get("mappings", []))
    assert [{key: value for key, value in rule.items() if key != "normalize"} for rule in payload["config"]] == [
        {key: value for key, value in rule.items() if key != "normalize"} for rule in before_config]
    assert "中文设备" in json.dumps(payload["config"], ensure_ascii=False)
    mapping_download = client.get(f"/api/v2/artifacts/{mapped['id']}/download")
    entry_download = client.get(f"/api/v2/artifacts/{exported['id']}/download")
    assert mapping_download.status_code == entry_download.status_code == 200
    entry_root = json.loads(base64.b64decode(entry_download.content))
    assert entry_root == json.loads(base64.b64decode(export_payload["content"]))
    assert any("入口规则" in rule["name"] for rule in entry_root)
    assert entry_root != payload["config"]
    assert json.loads(base64.b64decode(payload["download_content"])) == payload["config"], "the configuration card's Base64 must encode its own filled subrules, never the independent entry export"
    assert json.loads(base64.b64decode(mapping_download.content)) == payload["config"]
    assert payload["download_kind"] in {"mappedconfig_subrules", "enummapping_config"}
    assert export_payload["download_kind"] == "mappedconfig_mainrules"
    mapping_time = datetime.fromisoformat(mapped["created_at"]).astimezone().strftime("%Y%m%d_%H%M")
    entry_time = datetime.fromisoformat(exported["created_at"]).strftime("%Y%m%d_%H%M%S")
    assert download_filename(payload["download_kind"], mapping_time) in mapping_download.headers["content-disposition"]
    assert download_filename("mappedconfig_mainrules", entry_time) in entry_download.headers["content-disposition"]
