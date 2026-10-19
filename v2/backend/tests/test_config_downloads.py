"""配置卡自身下载与 Fill 独立导出的公开契约回归。"""
import base64
from datetime import datetime
import json

from contracts.download_naming import download_filename
from test_postprocessing import ROOT, Planner, current, excel, operation, rules, setup, upload


def test_pure_fill_keeps_independent_export_content_and_filename_contract(tmp_path):
    """配置卡自行编码时，不得改变纯 Fill 原生导出种类和文件名。"""
    planner = Planner()
    client, store, conversation, worker = setup(tmp_path, planner)
    rules(client, conversation, worker)
    upload(client, conversation, "enum.xlsx", excel("中文允许"), "enum_mapping")
    assert worker.once()
    run = operation(client, conversation, "fill", fill_kind="enum", target_fields=["事件结果"],
        source_ref="session.enum_mapping_table", config_ref="session.decoded_config")
    assert worker.once() and store.get_run("dev-user", run)["status"] == "succeeded"
    assert planner.calls == 0
    config = current(store, conversation, "field_mapping")
    exported = current(store, conversation, "config_export")
    config_payload = client.get(f"/api/v2/artifacts/{config['id']}/content").json()
    exported_payload = client.get(f"/api/v2/artifacts/{exported['id']}/content").json()
    root = json.loads(base64.b64decode(exported_payload["content"]))
    assert isinstance(root, dict) and root["meta"] == ROOT["meta"]
    assert any(row["mappingValue"] == "中文允许" for rule in root["rules"] for entry in rule["normalize"] for row in entry.get("mappings", []))
    assert json.loads(base64.b64decode(config_payload["download_content"])) == root
    assert exported_payload["download_kind"] == "enummapping_config"
    response = client.get(f"/api/v2/artifacts/{exported['id']}/download")
    assert response.status_code == 200 and json.loads(base64.b64decode(response.content)) == root
    timestamp = datetime.fromisoformat(exported["created_at"]).strftime("%Y%m%d_%H%M%S")
    assert download_filename("enummapping_config", timestamp) in response.headers["content-disposition"]
