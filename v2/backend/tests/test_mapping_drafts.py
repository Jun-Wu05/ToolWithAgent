import copy
import json
import pytest
from fastapi.testclient import TestClient
from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.infrastructure.db import connect
from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.runtime.business_application import BusinessApplication
from toolwithagent_v2.runtime.mapping_drafts import operation_key
from toolwithagent_v2.runtime.worker import Worker
from toolwithagent_v2.settings import Settings


class Business:
    apply_mapping_draft = BusinessApplication.apply_mapping_draft
    def __init__(self):
        self.fail = False
    async def field_mapping(self,path,snapshot,classification=None):
        if self.fail:
            return {"error":"field_mapping_failed"}
        config = [
            {"name":"duplicate", "normalize":[{"index":"a","field":"源地址","entity":"事件","result":["SECRET-A"],"mappings":[{"orgValue":"old","mappingValue":"old-target"}],"value":"old-default"},{"index":"b","field":"目的地址"},{"index":"c","field":None}]},
            {"name":"duplicate", "normalize":[{"index":"a","field":None},{"index":"b","field":"目的地址"},{"index":"nested.a","field":"源端口"},{"index":"c","field":None}]},
            {"name":"third", "normalize":[{"index":"a","field":"目的端口"},{"index":"b","field":"源地址"},{"index":"c","field":None}]}]
        return {"config":config,"mapping_rows":[{"原始字段名":source,"匹配状态":"匹配成功"} for source in ("a","b","c","nested.a")],
                "samples":{"0":{"a":[{"value":"SECRET-A","line_number":1,"source":"raw-log"}]},"1":{"a":[{"value":"SECRET-B","line_number":2,"source":"raw-log"}]}},
                "event_annotations":[],"warnings":[],"download_kind":"mapped_sub_rules","download_content":"ORIGINAL"}


def setup(tmp_path):
    settings = Settings(data_dir=tmp_path/"data")
    client = TestClient(create_app(settings))
    store = client.app.state.store
    conversation = client.post("/api/v2/conversations",json={}).json()["id"]
    business = Business()
    worker = Worker(store,"worker",business_application=business)
    file_id = client.post(f"/api/v2/conversations/{conversation}/files",files={"file":("logs.txt",b"type=x a=SECRET-A\n")}).json()["file"]["id"]
    assert worker.once()
    assert client.post(f"/api/v2/conversations/{conversation}/field-mapping",json={"file_id":file_id,"product":"private-product","log_vendor":"private-vendor"},headers={"Idempotency-Key":"mapping"}).status_code == 201
    assert worker.once()
    artifact = store.get_conversation("dev-user",conversation)["artifacts"][-1]
    draft = client.post(f"/api/v2/artifacts/{artifact['id']}/mapping-drafts").json()
    return client,store,conversation,worker,business,artifact,draft,file_id


def save(client,draft,source,target,rule="0",linked=None,revision=None):
    return client.patch(f"/api/v2/mapping-drafts/{draft['id']}/operations/{operation_key(rule,source)}",json={"sub_rule_id":rule,"source_path":source,"standard_field":target,"linked_sub_rule_ids":linked or []},headers={"If-Match":str(draft["revision"] if revision is None else revision)})


def view(client,artifact,draft=None,**query):
    return client.get(f"/api/v2/artifacts/{artifact['id']}/mapping-view",params={**query,**({"draft_id":draft["id"]} if draft else {})}).json()


def confirm(client,draft,response,accept=True,linked=None,key="confirm"):
    details = response.json()["error"]["details"]
    proposal = copy.deepcopy(details["proposal"])
    if linked is not None:
        proposal["linked_sub_rule_ids"] = linked
    return client.post(f"/api/v2/mapping-drafts/{draft['id']}/replacement-confirmations",json={"operation_key":details["operation_key"],"proposal":proposal,"confirm":accept},headers={"If-Match":str(draft["revision"]),"Idempotency-Key":key})


def apply(client,draft,key="apply"):
    return client.post(f"/api/v2/mapping-drafts/{draft['id']}/apply",headers={"If-Match":str(draft["revision"]),"Idempotency-Key":key})


def test_catalog_restore_stable_groups_privacy_and_message_guard(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    fields = client.get("/api/v2/standard-fields",params={"draft_id":draft["id"],"sub_rule":"0"}).json()["items"]
    assert len(fields)>500
    assert not {"事件名称","事件级别","日志类型","威胁类型"} & {item["name"] for item in fields}
    assert next(item for item in fields if item["name"]=="目的地址")["occupied_by"]=="b"
    original = view(client,artifact)
    draft = save(client,draft,"a","源端口").json()["draft"]
    edited = view(client,artifact,draft)
    assert [item["source_path"] for item in original["items"]] == [item["source_path"] for item in edited["items"]]
    row = next(item for item in edited["items"] if item["source_path"]=="a")
    assert row["standard_field"]=="源端口" and row["evidence"]=="用户选择" and row["draft_modified"]
    draft = save(client,draft,"c","目的端口").json()["draft"]
    row = next(item for item in view(client,artifact,draft)["items"] if item["source_path"]=="c")
    assert row["status"]=="matched" and row["group_status"]=="unmatched"
    assert view(client,artifact)["items"]==original["items"]
    restarted = TestClient(create_app(Settings(data_dir=store.root)))
    assert restarted.get(f"/api/v2/mapping-drafts/{draft['id']}").json()==draft
    assert restarted.post(f"/api/v2/artifacts/{artifact['id']}/mapping-drafts").json()==draft
    assert restarted.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"continue"}).json()["error"]["code"]=="draft_resolution_required"
    safe = restarted.get(f"/api/v2/conversations/{conversation}").json()
    assert "operations" not in safe["drafts"][0]
    assert all(secret not in json.dumps(safe,ensure_ascii=False) for secret in ("SECRET-A","SECRET-B","nested.a","private-product"))
    assert "SECRET-A" not in str(store.events("dev-user",conversation,0))


def test_replacement_cancel_scope_conflicts_and_repeated_edits(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    preview = save(client,draft,"a","目的地址")
    assert preview.status_code==409
    assert client.get(f"/api/v2/mapping-drafts/{draft['id']}").json()==draft
    choices = preview.json()["error"]["details"]["candidates"]["items"]
    assert choices[0]["sub_rule_id"]=="1" and not choices[0]["selectable"] and choices[0]["conflict_source_path"]=="b"
    assert choices[1]["selectable"]
    assert confirm(client,draft,preview,False).json()["draft"]==draft
    assert confirm(client,draft,preview,linked=["1"],key="invalid").json()["error"]["code"]=="mapping_link_conflict"
    response = confirm(client,draft,preview,linked=["2"],key="yes")
    assert response.status_code==200,response.text
    assert confirm(client,draft,preview,linked=["2"],key="yes").json()==response.json()
    draft = response.json()["draft"]
    rows = {row["source_path"]:row for row in view(client,artifact,draft)["items"]}
    assert rows["a"]["standard_field"]=="目的地址" and rows["b"]["standard_field"]==""
    assert next(row for row in view(client,artifact,draft,sub_rule="2")["items"] if row["source_path"]=="a")["standard_field"]=="目的地址"
    assert next(row for row in view(client,artifact,draft,sub_rule="1")["items"] if row["source_path"]=="a")["standard_field"]==""
    draft = save(client,draft,"b","源地址").json()["draft"]
    changed = save(client,draft,"a","源端口")
    assert changed.status_code==200,changed.text
    draft = changed.json()["draft"]
    rows = {row["source_path"]:row for row in view(client,artifact,draft)["items"]}
    assert rows["a"]["standard_field"]=="源端口" and rows["b"]["standard_field"]=="源地址"
    assert next(row for row in view(client,artifact,draft,sub_rule="2")["items"] if row["source_path"]=="a")["standard_field"]=="目的端口"


def test_revert_releases_old_occupant_and_noop_allows_message(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    draft = confirm(client,draft,save(client,draft,"a","目的地址")).json()["draft"]
    draft = save(client,draft,"a","源地址").json()["draft"]
    assert draft["changed_count"]==0 and draft["operations"]==[]
    assert client.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"allowed"}).status_code==201
    assert apply(client,draft).json()["error"]["code"]=="mapping_draft_empty"


@pytest.mark.parametrize("target",["src_ip","sourceIp","事件名称","事件级别","日志类型","威胁类型","invented"," 源地址 "])
def test_only_canonical_legal_targets(tmp_path,target):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    response = save(client,draft,"a",target)
    assert response.status_code==400,response.text
    assert response.json()["error"]["code"]=="mapping_target_invalid"
    assert client.get(f"/api/v2/mapping-drafts/{draft['id']}").json()["revision"]==1


def test_revision_and_operation_key_cannot_bypass_source_identity(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    changed = save(client,draft,"a","源端口").json()["draft"]
    assert save(client,draft,"a",None).json()["error"]["code"]=="draft_revision_conflict"
    assert save(client,changed,"a","源端口").json()["draft"]==changed
    malformed = client.patch(f"/api/v2/mapping-drafts/{draft['id']}/operations/fake",json={"sub_rule_id":"0","source_path":"a","standard_field":None},headers={"If-Match":"2"})
    assert malformed.json()["error"]["code"]=="mapping_operation_key_invalid"
    missing = client.patch(f"/api/v2/mapping-drafts/{draft['id']}/operations/{operation_key('0','a')}",json={"sub_rule_id":"0","source_path":"a","standard_field":None})
    assert missing.status_code==428
    assert save(client,changed,"original_log",None).json()["error"]["code"]=="mapping_source_not_editable"
    assert save(client,changed,"a",None,linked=["01"]).status_code==409
    choices = client.get(f"/api/v2/mapping-drafts/{draft['id']}/same-source-candidates/{operation_key('0','a')}").json()
    assert len(choices["items"])==2 and choices["items"][0]["conflict_source_path"]=="nested.a"


def test_apply_new_task_frozen_snapshot_lineage_and_old_result_immutable(tmp_path):
    import base64
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    with connect(store.path) as db:
        db.execute("UPDATE runs SET provider_config_revision=7,prompt_version='original-prompt',standard_field_version='original-fields' WHERE id=?", (artifact["run_id"],))
    original = client.get(f"/api/v2/artifacts/{artifact['id']}/download").content
    draft = save(client,draft,"a","源端口",linked=["2"]).json()["draft"]
    queued = apply(client,draft)
    assert queued.status_code==201,queued.text
    assert apply(client,draft).json()==queued.json()
    assert apply(client,draft,key="another").json()["error"]["code"]=="draft_apply_in_progress"
    restarted = TestClient(create_app(Settings(data_dir=store.root)))
    assert apply(restarted,draft).json()==queued.json()
    assert save(client,draft,"a",None).json()["error"]["code"]=="draft_apply_in_progress"
    run_id = queued.json()["run"]["id"]
    with connect(store.path) as db:
        run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        assert (run["provider_config_revision"],run["prompt_version"],run["standard_field_version"])==(7,"original-prompt","original-fields")
        frozen = json.loads(run["input_snapshot_json"])
        assert frozen["base_artifact_id"]==artifact["id"] and frozen["draft_revision"]==draft["revision"]
        assert frozen["draft_operations"]==draft["operations"]
    assert worker.once()
    current = [row for row in store.get_conversation("dev-user",conversation)["artifacts"] if row.get("current")][0]
    assert current["id"]!=artifact["id"] and current["run_id"]==run_id
    with connect(store.path) as db:
        new = db.execute("SELECT * FROM artifacts WHERE id=?",(current["id"],)).fetchone()
        assert new["version"]==2 and new["task_id"]!=db.execute("SELECT task_id FROM artifacts WHERE id=?",(artifact["id"],)).fetchone()[0]
        assert db.execute("SELECT relation FROM artifact_edges WHERE source_artifact_id=? AND derived_artifact_id=?",(artifact["id"],new["id"])).fetchone()[0]=="mapping_edit"
    assert client.get(f"/api/v2/artifacts/{artifact['id']}/download").content==original
    decoded = json.loads(base64.b64decode(client.get(f"/api/v2/artifacts/{current['id']}/download").content))
    assert decoded[0]["normalize"][0]["field"]=="源端口"
    assert "mappings" not in decoded[0]["normalize"][0] and "value" not in decoded[0]["normalize"][0]
    assert decoded[0]["normalize"][0]["result"]==["SECRET-A"]
    assert client.get(f"/api/v2/mapping-drafts/{draft['id']}").json()["status"]=="applied"
    assert client.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"continue"}).status_code==201
    row = next(row for row in view(client,current)["items"] if row["source_path"]=="a")
    assert row["user_modified"] and not row["draft_modified"] and row["evidence"]=="用户选择"


@pytest.mark.parametrize("failure",["exception","cancel","worker_loss","new_base","new_file","corrupt"])
def test_failed_or_late_apply_preserves_draft_and_formal_result(tmp_path,failure):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    draft = save(client,draft,"a","源端口").json()["draft"]
    queued = apply(client,draft).json()
    claim = store.claim("worker",lease_seconds=60)
    if failure=="exception":
        business.apply_mapping_draft = lambda *args: (_ for _ in ()).throw(RuntimeError("secret-stack"))
    elif failure=="cancel":
        token = store.issue_cancel_token("dev-user",claim["id"])["token"]
        store.cancel("dev-user",claim["id"],token)
    elif failure=="worker_loss":
        with connect(store.path) as db:
            db.execute("UPDATE runs SET lease_expires_at='2000' WHERE id=?",(claim["id"],))
            db.execute("UPDATE worker_leases SET lease_expires_at='2000'")
        store.claim("successor")
    elif failure=="new_base":
        with connect(store.path) as db:
            old = db.execute("SELECT * FROM artifacts WHERE id=?",(artifact["id"],)).fetchone()
            db.execute("INSERT INTO artifacts(id,conversation_id,task_id,run_id,kind,version,status,storage_key,sha256,metadata_json,created_at,size) VALUES('new-base',?,?,?,?,2,'published',?,?,?,?,?)",(conversation,old["task_id"],old["run_id"],old["kind"],old["storage_key"],old["sha256"],old["metadata_json"],"2999",old["size"]))
    elif failure=="new_file":
        client.post(f"/api/v2/conversations/{conversation}/files",files={"file":("new.txt",b"new=x")})
        with connect(store.path) as db:
            db.execute("UPDATE files SET parse_status='succeeded' WHERE id<>?",(file_id,))
    else:
        with connect(store.path) as db:
            key = db.execute("SELECT storage_key FROM artifacts WHERE id=?",(artifact["id"],)).fetchone()[0]
        (store.root/key).write_bytes(b"corrupt")
    worker._run_mapping_draft_apply(claim)
    restored = client.get(f"/api/v2/mapping-drafts/{draft['id']}").json()
    assert restored["status"]=="active" and restored["operations"]==draft["operations"] and restored["revision"]==draft["revision"]
    with connect(store.path) as db:
        assert not db.execute("SELECT 1 FROM artifacts WHERE run_id=?",(queued["run"]["id"],)).fetchone()
    assert store.get_run("dev-user",claim["id"])["status"] in ("failed","cancelled")
    assert "secret-stack" not in str(store.get_conversation("dev-user",conversation))
    if failure in ("new_base","new_file"):
        assert not restored["base_current"]
        assert client.delete(f"/api/v2/mapping-drafts/{draft['id']}",headers={"If-Match":str(draft["revision"])}).status_code==200


def test_old_failed_retry_cannot_overwrite_newer_edit_and_message_receipt_replays(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    message = client.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"original"},headers={"Idempotency-Key":"message"})
    # 消息如今创建真实业务 Run；本用例专测 Draft 重试，明确取消该排队任务。
    message_run = message.json()["run"]["id"]
    cancel = store.issue_cancel_token("dev-user",message_run)
    store.cancel("dev-user",message_run,cancel["token"])
    draft = save(client,draft,"a","源端口").json()["draft"]
    assert client.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"original"},headers={"Idempotency-Key":"message"}).json()==message.json()
    queued = apply(client,draft).json()
    business.apply_mapping_draft = lambda *args: (_ for _ in ()).throw(RuntimeError("fail"))
    assert worker.once()
    draft = save(client,draft,"a","目的端口").json()["draft"]
    assert client.post(f"/api/v2/runs/{queued['run']['id']}/retry").json()["error"]["code"]=="mapping_draft_apply_stale"


def test_old_automatic_mapping_cannot_publish_over_successful_apply(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    automatic = store.enqueue_field_mapping("dev-user",conversation,file_id=file_id,product="p",log_vendor="v")
    draft = save(client,draft,"a","源端口").json()["draft"]
    apply(client,draft)
    with connect(store.path) as db:
        db.execute("UPDATE runs SET queued_at='2999' WHERE id=?",(automatic["run"]["id"],))
    assert worker.once()
    applied = [row for row in store.get_conversation("dev-user",conversation)["artifacts"] if row.get("current")][0]
    assert worker.once()
    assert store.get_run("dev-user",automatic["run"]["id"])["error_code"]=="mapping_input_stale"
    assert [row for row in store.get_conversation("dev-user",conversation)["artifacts"] if row.get("current")][0]["id"]==applied["id"]


@pytest.mark.parametrize("identity",["dev-other","dev-admin","another-user"])
def test_owner_and_write_role_guards(tmp_path,identity):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    with connect(store.path) as db:
        db.execute("INSERT INTO users VALUES('another-user','other','user',1,'now')")
    client.post("/api/v2/dev/session",json={"user_id":identity})
    assert client.get(f"/api/v2/mapping-drafts/{draft['id']}").status_code==404
    assert client.get("/api/v2/standard-fields",params={"draft_id":draft["id"]}).status_code==404
    assert client.get(f"/api/v2/artifacts/{artifact['id']}/mapping-view",params={"draft_id":draft["id"]}).status_code==404
    expected = 404 if identity=="another-user" else 403
    assert save(client,draft,"a",None).status_code==expected
    assert apply(client,draft).status_code==expected
    assert client.delete(f"/api/v2/mapping-drafts/{draft['id']}",headers={"If-Match":"1"}).status_code==expected


def test_cors_allows_draft_headers_and_verbs(tmp_path):
    client = TestClient(create_app(Settings(data_dir=tmp_path/"data")))
    response = client.options("/api/v2/mapping-drafts/example",headers={"Origin":"http://localhost:5173","Access-Control-Request-Method":"PATCH","Access-Control-Request-Headers":"If-Match,Idempotency-Key"})
    assert response.status_code==200


def test_unmapping_retains_source_and_exact_dotted_path_is_not_linked(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    response = save(client,draft,"nested.a",None,rule="1")
    assert response.status_code==200,response.text
    assert response.json()["candidates"]["items"]==[]
    draft = response.json()["draft"]
    assert draft["changed_count"]==1
    assert next(row for row in view(client,artifact,draft,sub_rule="0")["items"] if row["source_path"]=="a")["standard_field"]=="源地址"
    assert apply(client,draft).status_code==201 and worker.once()
    current = [row for row in store.get_conversation("dev-user",conversation)["artifacts"] if row.get("current")][0]
    _row,payload = store._owned_mapping("dev-user",current["id"])
    assert any(entry["index"]=="nested.a" and entry["field"] is None for entry in payload["config"][1]["normalize"])


def test_draft_filtering_is_over_entire_subrule_before_50_row_paging(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    row,payload = store._owned_mapping("dev-user",artifact["id"])
    for number in range(60):
        payload["config"][0]["normalize"].append({"index":f"extra_{number}","field":None})
        payload["mapping_rows"].append({"原始字段名":f"extra_{number}","匹配状态":"未匹配"})
    content=json.dumps(payload,ensure_ascii=False).encode()
    path=store.root/row["storage_key"]
    path.write_bytes(content)
    import hashlib
    with connect(store.path) as db:
        db.execute("UPDATE artifacts SET sha256=? WHERE id=?",(hashlib.sha256(content).hexdigest(),artifact["id"]))
    draft=save(client,draft,"extra_59","源端口").json()["draft"]
    assert len(view(client,artifact,draft)["items"])==50
    assert view(client,artifact,draft,page=2)["items"][-1]["draft_modified"]
    found=view(client,artifact,draft,q="extra_59",status="matched")
    assert found["total"]==1 and found["items"][0]["source_path"]=="extra_59"
    assert view(client,artifact,draft,status="matched")["total"]==3


def test_successful_retry_reclaims_unchanged_draft_and_releases_guard(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    draft=save(client,draft,"a","源端口").json()["draft"]
    queued=apply(client,draft).json()
    original_method=business.apply_mapping_draft
    business.apply_mapping_draft=lambda *args: (_ for _ in ()).throw(RuntimeError("fail"))
    assert worker.once()
    business.apply_mapping_draft=original_method
    retry=client.post(f"/api/v2/runs/{queued['run']['id']}/retry",headers={"Idempotency-Key":"retry"})
    assert retry.status_code==201,retry.text
    restored=client.get(f"/api/v2/mapping-drafts/{draft['id']}").json()
    assert restored["status"]=="applying" and restored["apply_run_id"]==retry.json()["id"]
    assert worker.once()
    assert client.get(f"/api/v2/mapping-drafts/{draft['id']}").json()["status"]=="applied"


def test_catalog_revision_change_after_freeze_fails_without_artifact(tmp_path,monkeypatch):
    from toolwithagent_v2.runtime import mapping_drafts
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    draft=save(client,draft,"a","源端口").json()["draft"]
    queued=apply(client,draft).json()
    monkeypatch.setattr(mapping_drafts,"catalog_version",lambda:"changed-resource-version")
    assert worker.once()
    assert store.get_run("dev-user",queued["run"]["id"])["error_code"]=="mapping_draft_apply_stale"
    restored=client.get(f"/api/v2/mapping-drafts/{draft['id']}").json()
    assert restored["status"]=="active" and restored["changed_count"]==1
    assert [row["id"] for row in store.get_conversation("dev-user",conversation)["artifacts"] if row.get("current")]==[artifact["id"]]


def test_current_scope_no_implicit_link_and_automatic_mapping_queue_unchanged(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    draft=save(client,draft,"a","源端口").json()["draft"]
    assert next(row for row in view(client,artifact,draft,sub_rule="2")["items"] if row["source_path"]=="a")["standard_field"]=="目的端口"
    queued=[store.enqueue_field_mapping("dev-user",conversation,file_id=file_id,product="p",log_vendor="v") for _ in range(2)]
    assert worker.once() and worker.once()
    assert all(store.get_run("dev-user",item["run"]["id"])["status"]=="succeeded" for item in queued)
    stale=client.get(f"/api/v2/mapping-drafts/{draft['id']}").json()
    assert not stale["base_current"] and stale["operations"]==draft["operations"]
    assert save(client,draft,"a",None).json()["error"]["code"]=="mapping_base_stale"
    assert apply(client,draft).json()["error"]["code"]=="mapping_base_stale"
    assert client.delete(f"/api/v2/mapping-drafts/{draft['id']}",headers={"If-Match":str(draft["revision"])}).status_code==200


def test_multiple_live_drafts_are_individually_resolvable(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    old=save(client,draft,"a","源端口").json()["draft"]
    store.enqueue_field_mapping("dev-user",conversation,file_id=file_id,product="p",log_vendor="v")
    assert worker.once()
    current=[row for row in store.get_conversation("dev-user",conversation)["artifacts"] if row.get("current")][0]
    newer=client.post(f"/api/v2/artifacts/{current['id']}/mapping-drafts").json()
    newer=save(client,newer,"a","目的端口").json()["draft"]
    summaries=client.get(f"/api/v2/conversations/{conversation}").json()["drafts"]
    assert {item["id"] for item in summaries}=={old["id"],newer["id"]}
    assert client.delete(f"/api/v2/mapping-drafts/{old['id']}",headers={"If-Match":str(old["revision"])}).status_code==200
    assert client.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"continue"}).status_code==409
    assert client.delete(f"/api/v2/mapping-drafts/{newer['id']}",headers={"If-Match":str(newer["revision"])}).status_code==200
    assert client.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"continue"}).status_code==201


def test_apply_marks_existing_descendants_stale_and_copies_ancestors(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    with connect(store.path) as db:
        row=db.execute("SELECT * FROM artifacts WHERE id=?",(artifact["id"],)).fetchone()
        for identifier,kind in (("ancestor","log_classification"),("dependent","other")):
            db.execute("INSERT INTO artifacts(id,conversation_id,task_id,run_id,kind,version,status,storage_key,sha256,metadata_json,created_at,size) VALUES(?,?,?,?,?,1,'published',?,?,?,'2000',?)",(identifier,conversation,row["task_id"],row["run_id"],kind,row["storage_key"],row["sha256"],"{}",row["size"]))
        db.execute("INSERT INTO artifact_edges VALUES('ancestor',?,'upstream')",(artifact["id"],))
        db.execute("INSERT INTO artifact_edges VALUES(?,'dependent','derived')",(artifact["id"],))
        # Currency compares the classification anchor, as it would for a real parent.
        snapshot=json.loads(db.execute("SELECT input_snapshot_json FROM runs WHERE id=?",(artifact["run_id"],)).fetchone()[0])
        snapshot["classification_anchor"]="ancestor"
        db.execute("UPDATE runs SET input_snapshot_json=? WHERE id=?",(json.dumps(snapshot),artifact["run_id"]))
    draft=save(client,draft,"a","源端口").json()["draft"]
    assert apply(client,draft).status_code==201 and worker.once()
    with connect(store.path) as db:
        new=db.execute("SELECT id FROM artifacts WHERE kind='field_mapping' AND status='published'").fetchone()[0]
        assert db.execute("SELECT status FROM artifacts WHERE id='dependent'").fetchone()[0]=="stale"
        assert db.execute("SELECT 1 FROM artifact_edges WHERE source_artifact_id='ancestor' AND derived_artifact_id=?",(new,)).fetchone()


def test_confirmed_replacement_patch_replay_and_later_overwrite_follow_latest_choice(tmp_path):
    client,store,conversation,worker,business,artifact,draft,file_id = setup(tmp_path)
    draft=confirm(client,draft,save(client,draft,"a","目的地址"),key="first").json()["draft"]
    repeat=save(client,draft,"a","目的地址")
    assert repeat.status_code==200 and repeat.json()["draft"]==draft
    # A later replacement from another source owns the target now.
    preview=save(client,draft,"b","目的地址")
    assert preview.status_code==409
    draft=confirm(client,draft,preview,key="second").json()["draft"]
    assert next(row for row in view(client,artifact,draft)["items"] if row["source_path"]=="a")["standard_field"]==""
    preview=save(client,draft,"a","目的地址")
    assert preview.status_code==409
    draft=confirm(client,draft,preview,key="third").json()["draft"]
    rows={row["source_path"]:row for row in view(client,artifact,draft)["items"]}
    assert rows["a"]["standard_field"]=="目的地址" and rows["b"]["standard_field"]==""


def test_threat_target_is_readonly_but_source_relation_edits_preserve_chain():
    from toolwithagent_v2.runtime.mapping_drafts import project_payload,prepare_operation
    base={"config":[{"name":"threat","parser":{"filter":[{"fields":{"威胁类型":"%{desc}"}}]},"normalize":[{"index":"desc","field":"描述","result":["attack"]},{"index":"威胁类型","field":"威胁类型","mappings":[{"orgValue":"attack","mappingValue":"网络攻击"}]}]}],
          "mapping_rows":[{"原始字段名":"desc","匹配状态":"匹配成功"}],"event_annotations":[{"rule_name":"threat","threat_source_field":"desc","threat_types":["网络攻击"]}],"download_kind":"mapped_sub_rules"}
    proposal={"sub_rule_id":"0","source_path":"desc","standard_field":None,"linked_sub_rule_ids":[]}
    operation,choices,modified=prepare_operation(base,[],operation_key("0","desc"),proposal)
    assert modified
    edited=project_payload(base,[operation])
    assert edited["config"][0]["parser"]==base["config"][0]["parser"]
    assert edited["config"][0]["normalize"][1]==base["config"][0]["normalize"][1]
    assert edited["config"][0]["normalize"][0]["result"]==["attack"]
    assert edited["event_annotations"]==base["event_annotations"]
    protected=copy.deepcopy(base)
    protected["config"][0]["normalize"][0]["field"]="威胁类型"
    protected["config"][0]["normalize"].pop()
    from toolwithagent_v2.runtime.mapping_projection import mapping_view
    assert mapping_view(protected)["items"][0]["editable"] is False
    with pytest.raises(ValueError,match="mapping_source_not_editable"):
        prepare_operation(protected,[],operation_key("0","desc"),proposal)
