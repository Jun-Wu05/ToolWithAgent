"""#435：助手消息携带下一步建议（对话式引导芯片的数据源与占位回填）。"""
from test_log_parse_slice import setup as parse_setup, upload
from test_field_mapping_slice import setup as mapping_setup, enqueue, mappings


def _assistant_messages(client, conversation):
    detail = client.get(f"/api/v2/conversations/{conversation}").json()
    return [m for m in detail["messages"] if m["actor"] == "assistant"]


def test_upload_validated_message_offers_intent_suggestions(tmp_path):
    client, store, conversation, worker = parse_setup(tmp_path)
    file_id = upload(client, conversation, worker)
    suggestions = next(m["payload"]["suggestions"] for m in _assistant_messages(client, conversation)
                       if m["payload"].get("suggestions"))
    ids = [item["id"] for item in suggestions]
    # 分叉②定稿（#435）：上传后不提供映射入口（映射需先提取），枚举可直提。
    assert "enum_extract" in ids and "log_parse" in ids and "field_mapping" not in ids
    log_parse = next(item for item in suggestions if item["id"] == "log_parse")
    assert log_parse["type"] == "action" and log_parse["file_id"] == file_id
    prompt = next(item for item in suggestions if item["id"] == "enum_extract")
    assert prompt["type"] == "prompt" and prompt["text"]
    assert len(suggestions) <= 4


def test_mapping_without_classification_is_rejected_with_guidance(tmp_path):
    client, store, conversation, worker = parse_setup(tmp_path)
    file_id = upload(client, conversation, worker)
    response = client.post(f"/api/v2/conversations/{conversation}/field-mapping",
                           json={"file_id": file_id, "product": "p", "log_vendor": "v"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "classification_required"


def test_classification_done_suggestions_use_artifact_entry(tmp_path):
    client, store, conversation, worker = parse_setup(tmp_path)
    file_id = upload(client, conversation, worker)
    client.post(f"/api/v2/conversations/{conversation}/log-parse", json={"file_id": file_id})
    assert worker.once()
    detail = client.get(f"/api/v2/conversations/{conversation}").json()
    classification = next(a for a in detail["artifacts"] if a["kind"] == "log_classification")
    suggestions = next(m["payload"]["suggestions"] for m in detail["messages"]
                       if m["actor"] == "assistant" and m["payload"].get("suggestions")
                       and any(s["id"] == "field_mapping" and s.get("classification_artifact_id")
                               for s in m["payload"]["suggestions"]))
    mapping = next(item for item in suggestions if item["id"] == "field_mapping")
    assert mapping["classification_artifact_id"] == classification["id"]
    open_results = next(item for item in suggestions if item["id"] == "open_results")
    assert open_results["artifact_id"] == classification["id"]


def test_mapping_done_and_failed_suggestions(tmp_path):
    client, store, conversation, worker, business, file_id = mapping_setup(tmp_path)
    assert enqueue(client, conversation, file_id, key="suggest-ok").status_code == 201
    assert worker.once()
    detail = client.get(f"/api/v2/conversations/{conversation}").json()
    artifact = mappings(store, conversation)[0]
    done = next(m["payload"]["suggestions"] for m in detail["messages"]
                if m["actor"] == "assistant" and m["payload"].get("suggestions")
                and any(s["id"] == "mapping_edit" for s in m["payload"]["suggestions"]))
    open_results = next(item for item in done if item["id"] == "open_results")
    assert open_results["artifact_id"] == artifact["id"]

    business.fail = True
    failed_run = enqueue(client, conversation, file_id, key="suggest-fail").json()["run"]["id"]
    assert worker.once()
    detail = client.get(f"/api/v2/conversations/{conversation}").json()
    failed_message = next(m for m in detail["messages"]
                          if m["actor"] == "assistant" and m.get("run_id") == failed_run
                          and m["payload"].get("suggestions"))
    assert {item["id"] for item in failed_message["payload"]["suggestions"]} == {"retry", "open_trace"}
    assert client.get(f"/api/v2/runs/{failed_run}").json()["status"] == "failed"
