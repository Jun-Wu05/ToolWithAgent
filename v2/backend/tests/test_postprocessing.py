"""#276 通过真实 Application 组合验证跨轮产物、附件、确认和导出。"""
import base64
from io import BytesIO
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from application.adapters.composition import create_default_adapters
from application.adapters.enum_extract import EnumExtractAdapter
from contracts.planner_models import PlanDecision
from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.infrastructure.db import connect
from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.runtime.business_application import BusinessApplication
from toolwithagent_v2.runtime.worker import Worker
from toolwithagent_v2.settings import Settings

ROOT={"meta":"中文根结构", "rules":[{"name":"rule", "normalize":[
    {"index":"alarm","field":"威胁类型","result":["SQL注入"]},
    {"index":"status","field":"事件结果","result":["allow"]},
    {"index":"src","field":"源地址","result":["SENSITIVE-SAMPLE"]}]}]}


class Planner:
    def __init__(self,decision="execute"):
        self.calls=0; self.decision=decision
    async def plan(self,**kwargs):
        self.calls+=1
        return PlanDecision.model_validate({"decision":self.decision,"plan_id":"user-plan","question":"确认导出？" if self.decision=="proposal" else None,
            "reason_code":"confirm_export" if self.decision=="proposal" else None,"choices":["确认","取消"] if self.decision=="proposal" else [],
            "steps":[{"step_id":"export","type":"export","source_ref":"session.decoded_config"}]})


class ThreatMember:
    name="ThreatAgent"
    async def arun(self,prompt,**kwargs):
        values=json.loads(prompt)["values"]
        yield SimpleNamespace(event="RunCompleted",content=[{"mappingType":"EQUAL","orgValue":value,"mappingValue":"SQL注入"} for value in values])


def setup(tmp_path,planner=None):
    client=TestClient(create_app(Settings(data_dir=tmp_path/"data"))); store=client.app.state.store
    conversation=client.post("/api/v2/conversations",json={}).json()["id"]
    def adapters(team):
        result=create_default_adapters(team)
        result["enum_extract"]=EnumExtractAdapter(llm_caller=lambda *args,**kwargs: json.dumps({"field":"alarm","regex":r"alarm=([^\s]+)"}),prompt_loader=lambda:"TEST")
        return result
    business=BusinessApplication(store.path,team_factory=lambda:SimpleNamespace(members=(ThreatMember(),)),adapters_factory=adapters,planner=planner or Planner())
    worker=Worker(store,"worker",business_application=business)
    return client,store,conversation,worker


def upload(client,conversation,name,content,role="primary"):
    response=client.post(f"/api/v2/conversations/{conversation}/files",files={"file":(name,content)},data={"role":role})
    assert response.status_code==201,response.text
    return response.json()


def rules(client,conversation,worker):
    upload(client,conversation,"rules.b64",base64.b64encode(json.dumps(ROOT,ensure_ascii=False).encode()))
    assert worker.once()


def excel(value="允许"):
    workbook=Workbook(); sheet=workbook.active; sheet.title="事件结果"
    sheet.append(["mappingType","orgValue","mappingValue"]); sheet.append(["EQUAL","allow",value])
    out=BytesIO(); workbook.save(out); workbook.close(); return out.getvalue()


def operation(client,conversation,type,**params):
    response=client.post(f"/api/v2/conversations/{conversation}/operations",json={"step":{"step_id":"operation","type":type,**params}})
    assert response.status_code==201,response.text
    return response.json()["run"]["id"]


def current(store,conversation,kind):
    return next(item for item in reversed(store.get_conversation("dev-user",conversation)["artifacts"]) if item["kind"]==kind and item.get("current",True))


def test_rules_attachment_fill_restart_export_root_and_latest_draft(tmp_path):
    client,store,conversation,worker=setup(tmp_path); rules(client,conversation,worker)
    primary=store.get_conversation("dev-user",conversation)["files"][0]["id"]
    attachment=upload(client,conversation,"enum.xlsx",excel(),"enum_mapping"); assert worker.once()
    assert attachment["file"]["role"]=="enum_mapping"
    run=operation(client,conversation,"fill",fill_kind="enum",target_fields=["事件结果"],source_ref="session.enum_mapping_table",config_ref="session.decoded_config")
    assert worker.once(); assert store.get_run("dev-user",run)["status"]=="succeeded"
    mapped=current(store,conversation,"field_mapping")
    data=client.get(f"/api/v2/artifacts/{mapped['id']}/download")
    exported=json.loads(base64.b64decode(data.content))
    assert exported["meta"]==ROOT["meta"] and isinstance(exported,dict)
    assert exported["rules"][0]["normalize"][1]["mappings"][0]["mappingValue"]=="允许"
    draft=client.post(f"/api/v2/artifacts/{mapped['id']}/mapping-drafts").json()
    view=client.get(f"/api/v2/artifacts/{mapped['id']}/mapping-view").json()
    row=next(item for item in view["items"] if item["source_path"]=="src")
    changed=client.patch(f"/api/v2/mapping-drafts/{draft['id']}/operations/{row['operation_key']}",json={"sub_rule_id":"0","source_path":"src","standard_field":"目的地址","linked_sub_rule_ids":[]},headers={"If-Match":str(draft["revision"])})
    assert changed.status_code==200,changed.text
    draft=changed.json()["draft"]
    assert client.post(f"/api/v2/mapping-drafts/{draft['id']}/apply",headers={"If-Match":str(draft["revision"]),"Idempotency-Key":"apply"}).status_code==201
    assert worker.once()
    edited=current(store,conversation,"field_mapping")
    editedroot=json.loads(base64.b64decode(client.get(f"/api/v2/artifacts/{edited['id']}/download").content))
    assert editedroot["rules"][0]["normalize"][1]["mappings"][0]["mappingValue"]=="允许"
    assert editedroot["rules"][0]["normalize"][2]["field"]=="目的地址"
    restarted=Store(Settings(data_dir=store.root)); worker=Worker(restarted,"worker",business_application=worker.business_application)
    run=operation(client,conversation,"export",source_ref="session.decoded_config")
    assert worker.once(); assert restarted.get_run("dev-user",run)["status"]=="succeeded"
    export=current(restarted,conversation,"config_export")
    assert json.loads(base64.b64decode(client.get(f"/api/v2/artifacts/{export['id']}/download").content))==editedroot
    assert next(item for item in restarted.get_conversation("dev-user",conversation)["files"] if item["id"]==primary)["mapping_eligible"]


def test_same_sheet_replacement_requires_refill_and_failed_export_keeps_old(tmp_path):
    client,store,conversation,worker=setup(tmp_path); rules(client,conversation,worker)
    upload(client,conversation,"enum.xlsx",excel(),"enum_mapping"); assert worker.once()
    operation(client,conversation,"fill",fill_kind="enum",target_fields=["事件结果"],source_ref="session.enum_mapping_table",config_ref="session.decoded_config"); assert worker.once()
    old=current(store,conversation,"field_mapping")
    upload(client,conversation,"enum.xlsx",excel("新允许"),"enum_mapping"); assert worker.once()
    run=operation(client,conversation,"export",source_ref="session.decoded_config"); assert worker.once()
    assert store.get_run("dev-user",run)["error_code"]=="enum_refill_required"
    assert current(store,conversation,"field_mapping")["id"]==old["id"]
    operation(client,conversation,"fill",fill_kind="enum",target_fields=["事件结果"],source_ref="session.enum_mapping_table",config_ref="session.decoded_config"); assert worker.once()
    updated=current(store,conversation,"field_mapping")
    root=json.loads(base64.b64decode(client.get(f"/api/v2/artifacts/{updated['id']}/download").content))
    assert root["rules"][0]["normalize"][1]["mappings"]==[{"mappingType":"EQUAL","orgValue":"allow","mappingValue":"新允许"}]


def test_enum_threat_cross_round_restart_and_owner_download_privacy(tmp_path):
    client,store,conversation,worker=setup(tmp_path)
    upload(client,conversation,"logs.txt","alarm=SQL注入 status=allow\nalarm=恶意访问 status=deny\n".encode()); assert worker.once()
    run=operation(client,conversation,"enum_extract",target_field="alarm"); assert worker.once()
    assert store.get_run("dev-user",run)["status"]=="succeeded"
    enum=current(store,conversation,"enum_values")
    assert "SQL注入" not in json.dumps(store.get_conversation("dev-user",conversation),ensure_ascii=False)
    assert client.get(f"/api/v2/artifacts/{enum['id']}/content").json()["values"]==["SQL注入","恶意访问"]
    enum_download=client.get(f"/api/v2/artifacts/{enum['id']}/download")
    assert enum_download.headers["content-type"].startswith("application/json")
    assert set(enum_download.json()) == {"field", "regex", "original_log", "value"}
    assert enum_download.json()["value"] == ["SQL注入", "恶意访问"]
    restarted=Store(Settings(data_dir=store.root)); worker=Worker(restarted,"worker",business_application=worker.business_application)
    response=client.post(f"/api/v2/conversations/{conversation}/operations",json={"step":{"step_id":"operation","type":"threat_mapping","source_ref":"session.artifacts.enum_values"},"source_artifact_id":enum["id"]})
    assert response.status_code==201,response.text; assert worker.once()
    assert restarted.get_run("dev-user",response.json()["run"]["id"])["status"]=="succeeded"
    threat=current(restarted,conversation,"threat_mapping")
    download=client.get(f"/api/v2/artifacts/{threat['id']}/download")
    assert download.headers["content-type"].startswith("application/vnd.openxmlformats")
    workbook=load_workbook(BytesIO(download.content)); assert workbook.active.max_row==3
    assert workbook.sheetnames == ["threat_mapping"]
    assert list(next(workbook.active.iter_rows(values_only=True))) == ["mappingType", "orgValue", "mappingValue"]
    workbook.close()
    client.post("/api/v2/dev/session",json={"user_id":"dev-other"})
    assert client.get(f"/api/v2/artifacts/{threat['id']}/content").status_code==404
    assert client.get(f"/api/v2/artifacts/{threat['id']}/download").status_code==404
    assert "SQL注入" not in json.dumps(store.events("dev-user",conversation,0),ensure_ascii=False)


def test_real_proposal_checkpoint_confirm_once_no_replanning(tmp_path):
    planner=Planner("proposal"); client,store,conversation,worker=setup(tmp_path,planner); rules(client,conversation,worker)
    response=client.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"导出规则"},headers={"Idempotency-Key":"message"})
    assert response.status_code==201,response.text
    run=response.json()["run"]["id"]; assert response.json()["content"]=="导出规则"; assert worker.once()
    assert store.get_run("dev-user",run)["status"]=="waiting_confirmation" and planner.calls==1
    assert client.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"其他操作"}).json()["error"]["code"]=="confirmation_resolution_required"
    token=client.post(f"/api/v2/runs/{run}/confirmation-token").json()
    assert token["kind"]=="business_plan" and token["payload"]["operations"]==["export"]
    body={"token":token["token"],"checkpoint_revision":token["checkpoint_revision"]}; headers={"Idempotency-Key":"confirm"}
    first=client.post(f"/api/v2/runs/{run}/confirm",json=body,headers=headers)
    assert first.status_code==200,first.text
    assert client.post(f"/api/v2/runs/{run}/confirm",json=body,headers=headers).json()==first.json()
    worker=Worker(Store(Settings(data_dir=store.root)),"worker",business_application=worker.business_application)
    assert worker.once(); assert store.get_run("dev-user",run)["status"]=="succeeded" and planner.calls==1
    assert current(store,conversation,"config_export")


@pytest.mark.parametrize("change",["primary","attachment","cancel","fence","hash"])
def test_late_operation_cannot_publish_after_frozen_inputs_change(tmp_path,change):
    client,store,conversation,worker=setup(tmp_path); rules(client,conversation,worker)
    run=operation(client,conversation,"export",source_ref="session.decoded_config")
    claim=store.claim("worker")
    if change=="primary":
        upload(client,conversation,"new.txt",b"new=other")
        with connect(store.path) as db: db.execute("UPDATE files SET parse_status='succeeded' WHERE original_name='new.txt'")
    elif change=="attachment":
        upload(client,conversation,"enum.xlsx",excel(),"enum_mapping")
        with connect(store.path) as db: db.execute("UPDATE files SET parse_status='succeeded' WHERE role='enum_mapping'")
    elif change=="cancel":
        token=store.issue_cancel_token("dev-user",run)["token"]; store.cancel("dev-user",run,token)
    elif change=="fence":
        with connect(store.path) as db: db.execute("UPDATE runs SET fence_token='new' WHERE id=?",(run,))
    else:
        (store.root/claim["input"]["storage_key"]).write_bytes(b"changed")
    worker._run_business(claim)
    assert not any(item["run_id"]==run for item in store.get_conversation("dev-user",conversation)["artifacts"])


def test_old_card_id_and_untyped_button_sources_are_rejected(tmp_path):
    client,store,conversation,worker=setup(tmp_path)
    upload(client,conversation,"logs.txt","alarm=SQL注入\n".encode()); assert worker.once()
    operation(client,conversation,"enum_extract",target_field="alarm"); assert worker.once(); old=current(store,conversation,"enum_values")
    operation(client,conversation,"enum_extract",target_field="alarm"); assert worker.once()
    response=client.post(f"/api/v2/conversations/{conversation}/operations",json={"step":{"step_id":"op","type":"threat_mapping","source_ref":"session.artifacts.enum_values"},"source_artifact_id":old["id"]})
    assert response.status_code==409
    assert client.post(f"/api/v2/conversations/{conversation}/operations",json={"step":{"step_id":"op","type":"threat_mapping","source_ref":"session.last_threat_data"}}).status_code==422
    assert client.post(f"/api/v2/conversations/{conversation}/operations",json={"step":{"step_id":"op","type":"enum_extract"}}).status_code==422


def test_confirmation_rejects_same_count_changed_content(tmp_path):
    planner=Planner("proposal"); client,store,conversation,worker=setup(tmp_path,planner); rules(client,conversation,worker)
    run=client.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"导出"}).json()["run"]["id"]
    assert worker.once(); token=store.issue_resume_token("dev-user",run)
    with connect(store.path) as db: key=db.execute("SELECT storage_key FROM files WHERE role='primary'").fetchone()[0]
    (store.root/key).write_bytes(b"tampered")
    # 内容校验在确认/执行两个边界均失败关闭。
    response=client.post(f"/api/v2/runs/{run}/confirm",json={"token":token["token"],"checkpoint_revision":token["checkpoint_revision"]})
    assert response.status_code==409 and response.json()["error"]["code"]=="continuation_stale"
    assert not any(item["run_id"]==run for item in store.get_conversation("dev-user",conversation)["artifacts"])



def test_logs_mapping_automatic_threat_chain_persists_and_reuses_after_restart(tmp_path, monkeypatch):
    from application.adapters.field_mapping import FieldMappingAdapter
    from application.adapters.log_parse import LogParseAdapter
    import application.threat_chain as chain
    client,store,conversation,_worker=setup(tmp_path)
    class FieldMember:
        name="FieldMappingAgent"
        async def arun(self,prompt,**kwargs):
            yield SimpleNamespace(event="RunCompleted",content=[
                {"原始字段名":"src","系统属性名称":"源地址","匹配状态":"匹配成功"},
                {"原始字段名":"kind","系统属性名称":"未匹配","匹配状态":"未匹配"},
                {"原始字段名":"alarm","系统属性名称":"未匹配","匹配状态":"未匹配"}])
    classification={"status":"SUCCESS","log_format":"KV","feature_field":"kind",
        "analysis":{"has_key_value_pairs":True,"delimit":" ","tab":"="},
        "classification_details":[{"logtype":"a","count":3,"real_samples":"kind=a src=1 alarm=SQL注入"}]}
    async def events(prompt):
        rows=json.loads(prompt.split("## 待判定子规则\n```json\n")[1].split("\n```")[0])
        return json.dumps({"results":[{"rule_name":row["rule_name"],"event_name":"网络攻击","group":"threat"} for row in rows]},ensure_ascii=False)
    def adapters(team):
        result=create_default_adapters(team)
        result["field_mapping"]=FieldMappingAdapter(team,candidate_retriever=lambda _: {},event_classifier=events)
        result["enum_extract"]=EnumExtractAdapter(llm_caller=lambda *args,**kwargs: json.dumps({"field":"alarm","regex":r"alarm=([^\s]+)"}),prompt_loader=lambda:"TEST")
        result["log_parse"]=LogParseAdapter(format_identifier=lambda _: json.dumps({"format":"KV","feature_field":"kind"}),classifier=lambda *args,**kwargs: json.dumps(classification),sample_filler=lambda data,_:data)
        return result
    # 只替换公开候选检索依赖；自动链构造/执行/原子提交全部走生产代码。
    monkeypatch.setattr(chain,"batch_retrieve_candidates_table",lambda fields,**kwargs:{field:[("威胁类型",0.95,"威胁","")] if field=="alarm" else [] for field in fields})
    business=BusinessApplication(store.path,team_factory=lambda:SimpleNamespace(members=(FieldMember(),ThreatMember())),adapters_factory=adapters)
    worker=Worker(store,"worker",business_application=business)
    uploaded=upload(client,conversation,"logs.txt","kind=a src=1 alarm=SQL注入\nkind=a src=2 alarm=恶意访问\nkind=a src=3 alarm=SQL注入\n".encode()); assert worker.once()
    assert client.post(f"/api/v2/conversations/{conversation}/log-parse",json={"file_id":uploaded["file"]["id"]}).status_code==201
    assert worker.once()
    parsed=next(item for item in store.get_conversation("dev-user",conversation)["artifacts"] if item["kind"]=="log_classification")
    response=client.post(f"/api/v2/conversations/{conversation}/field-mapping",json={"classification_artifact_id":parsed["id"],"product":"p","log_vendor":"v"})
    assert response.status_code==201,response.text; assert worker.once()
    assert store.get_run("dev-user",response.json()["run"]["id"])["status"]=="succeeded"
    enum=current(store,conversation,"enum_values"); threat=current(store,conversation,"threat_mapping"); mapped=current(store,conversation,"field_mapping")
    assert enum["summary"]["item_count"]==2 and threat["summary"]["item_count"]==2
    from toolwithagent_v2.infrastructure.db import connect
    with connect(store.path) as db:
        for source, derived in ((enum, threat), (threat, mapped)):
            assert db.execute("SELECT 1 FROM artifact_edges WHERE source_artifact_id=? AND derived_artifact_id=?", (source["id"], derived["id"])).fetchone()
    root=json.loads(base64.b64decode(client.get(f"/api/v2/artifacts/{mapped['id']}/download").content))
    assert any(entry.get("index")=="威胁类型" and entry.get("mappings") for entry in root[0]["normalize"])
    worker=Worker(Store(Settings(data_dir=store.root)),"worker",business_application=business)
    operation(client,conversation,"threat_mapping",source_ref="user.values",values=["新的攻击"]); assert worker.once()
    run=operation(client,conversation,"fill",fill_kind="threat",target_fields=["威胁类型"],source_ref="session.artifacts.threat_mapping",config_ref="session.mapped_sub_rules")
    assert worker.once(); assert store.get_run("dev-user",run)["status"]=="succeeded"
    operation(client,conversation,"export",source_ref="session.mapped_sub_rules"); assert worker.once()
    final=current(store,conversation,"config_export")
    data=client.get(f"/api/v2/artifacts/{final['id']}/download")
    assert data.headers["content-type"].startswith("text/plain") and "mappedconfig_subrules_" in data.headers["content-disposition"]
    assert any(row["orgValue"]=="新的攻击" for entry in json.loads(base64.b64decode(data.content))[0]["normalize"] for row in entry.get("mappings",[]))
    old_enum, old_threat = current(store,conversation,"enum_values"), current(store,conversation,"threat_mapping")
    async def failing_threat(self,*args,**kwargs):
        raise RuntimeError("SENSITIVE-FAILED-CHAIN")
        yield
    with monkeypatch.context() as failed:
        failed.setattr(ThreatMember,"arun",failing_threat)
        response=client.post(f"/api/v2/conversations/{conversation}/field-mapping",json={"classification_artifact_id":parsed["id"],"product":"p","log_vendor":"v"})
        assert response.status_code==201,response.text; assert worker.once()
        assert store.get_run("dev-user",response.json()["run"]["id"])["status"]=="succeeded"
    assert current(store,conversation,"enum_values")["id"]==old_enum["id"]
    assert current(store,conversation,"threat_mapping")["id"]==old_threat["id"]



def test_remove_mapping_latest_configuration_and_primary_replacement(tmp_path):
    client,store,conversation,worker=setup(tmp_path); rules(client,conversation,worker)
    upload(client,conversation,"enum.xlsx",excel(),"enum_mapping"); assert worker.once()
    operation(client,conversation,"fill",fill_kind="enum",target_fields=["事件结果"],source_ref="session.enum_mapping_table",config_ref="session.decoded_config"); assert worker.once()
    old=current(store,conversation,"field_mapping")
    operation(client,conversation,"remove_mapping",target_fields=["status"],config_ref="session.decoded_config"); assert worker.once()
    latest=current(store,conversation,"field_mapping")
    assert latest["id"] != old["id"] and latest["config_ref"]=="session.decoded_config"
    exported=json.loads(base64.b64decode(client.get(f"/api/v2/artifacts/{latest['id']}/download").content))
    assert not exported["rules"][0]["normalize"][1].get("mappings")
    upload(client,conversation,"replacement.txt",b"new=value"); assert worker.once()
    detail=store.get_conversation("dev-user",conversation)
    assert not next(item for item in detail["artifacts"] if item["id"]==latest["id"])["current"]
    assert detail["session_facts"]["available_config_refs"]==[] and detail["session_facts"]["enum_mapping_target_fields"]==[]
    assert client.get(f"/api/v2/artifacts/{latest['id']}/download").status_code==200


def test_safe_facts_content_failure_does_not_hide_history(tmp_path):
    client,store,conversation,worker=setup(tmp_path); rules(client,conversation,worker)
    upload(client,conversation,"enum.xlsx",excel("SENSITIVE-MAPPING"),"enum_mapping"); assert worker.once()
    operation(client,conversation,"fill",fill_kind="enum",target_fields=["事件结果"],source_ref="session.enum_mapping_table",config_ref="session.decoded_config"); assert worker.once()
    detail=store.get_conversation("dev-user",conversation)
    assert detail["session_facts"]["available_config_refs"]==["session.decoded_config"]
    assert "SENSITIVE-MAPPING" not in json.dumps(detail["session_facts"],ensure_ascii=False)
    assert detail["session_facts_error"] is None
    assert all(key not in detail["session_facts"] for key in ("available_fields", "mappable_fields", "mapped_sub_rule_names", "decoded_config_rule_names"))
    artifact=current(store,conversation,"field_mapping")
    assert artifact["result_message_id"] in {message["id"] for message in detail["messages"]}
    with connect(store.path) as db: key=db.execute("SELECT storage_key FROM files WHERE role='primary'").fetchone()[0]
    (store.root/key).write_bytes(b"tampered")
    detail=client.get(f"/api/v2/conversations/{conversation}").json()
    assert detail["session_facts"] is None and detail["session_facts_error"]=="business_input_unavailable"
    assert detail["artifacts"] and client.get(f"/api/v2/artifacts/{artifact['id']}/download").status_code==200


def test_natural_log_parse_persists_classification_and_safe_facts(tmp_path):
    from application.adapters.log_parse import LogParseAdapter
    class LogPlanner:
        async def plan(self,**kwargs):
            return PlanDecision.model_validate({"decision":"execute","plan_id":"parse", "steps":[{"step_id":"parse","type":"log_parse"}]})
    client,store,conversation,_=setup(tmp_path)
    classification={"status":"SUCCESS","log_format":"KV","feature_field":"kind","analysis":{"has_key_value_pairs":True,"delimit":" ","tab":"="},
        "classification_details":[{"logtype":"a","count":3,"real_samples":"kind=a value=secret"}]}
    def adapters(team):
        result=create_default_adapters(team)
        result["log_parse"]=LogParseAdapter(format_identifier=lambda _:json.dumps({"format":"KV","feature_field":"kind"}),classifier=lambda *args,**kwargs:json.dumps(classification),sample_filler=lambda value,_:value)
        return result
    business=BusinessApplication(store.path,team_factory=lambda:SimpleNamespace(members=()),adapters_factory=adapters,planner=LogPlanner())
    worker=Worker(store,"worker",business_application=business)
    upload(client,conversation,"logs.txt",b"kind=a value=secret\nkind=a value=secret\nkind=a value=secret\n"); assert worker.once()
    message=client.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"解析日志"}).json()
    assert worker.once(); assert store.get_run("dev-user",message["run"]["id"])["status"]=="succeeded"
    detail=store.get_conversation("dev-user",conversation)
    artifact=next(item for item in detail["artifacts"] if item["kind"]=="log_classification")
    assert artifact["mapping_eligible"]
    assert client.get(f"/api/v2/artifacts/{artifact['id']}/download").json()==classification
    assert detail["session_facts"]["has_log_classification"]
    assert "secret" not in json.dumps(detail["session_facts"],ensure_ascii=False)



def test_real_multi_step_progress_survives_restart_and_hides_values_and_identifiers(tmp_path):
    class MultiPlanner:
        async def plan(self,**kwargs):
            return PlanDecision.model_validate({"decision":"execute","plan_id":"SENSITIVE-PLAN","steps":[
                {"step_id":"SENSITIVE-ENUM","type":"enum_extract","target_field":"alarm"},
                {"step_id":"SENSITIVE-THREAT","type":"threat_mapping","source_ref":"step:SENSITIVE-ENUM","depends_on":["SENSITIVE-ENUM"]}]})
    client,store,conversation,worker=setup(tmp_path,MultiPlanner())
    upload(client,conversation,"logs.txt",b"alarm=SENSITIVE-VALUE\n"); assert worker.once()
    message=client.post(f"/api/v2/conversations/{conversation}/messages",json={"content":"提取并映射"}).json()
    assert worker.once()
    run=store.get_run("dev-user",message["run"]["id"])
    assert run["status"]=="succeeded"
    progress=[event for event in run["events"] if event["event_type"]=="run_progress"]
    enum=next(event for event in progress if event["summary"]["operation"]=="enum_extract")
    threat=next(event for event in progress if event["summary"]["operation"]=="threat_mapping")
    assert threat["summary"]["dependency_scope_ids"]==[enum["scope_id"]]
    assert "SENSITIVE" not in json.dumps(run["events"])
    assert "SENSITIVE" not in json.dumps(store.events("dev-user",conversation,0))
    restarted=Store(Settings(data_dir=store.root))
    assert restarted.get_run("dev-user",run["id"])["events"]==run["events"]


def test_late_progress_is_rejected_after_cancel_or_worker_fence(tmp_path):
    from toolwithagent_v2.runtime.progress import RunProgressSink
    from contracts.progress import ProgressEvent, ProgressPhase, ProgressStatus
    import asyncio
    client,store,conversation,worker=setup(tmp_path); rules(client,conversation,worker)
    run=operation(client,conversation,"export",source_ref="session.decoded_config")
    claim=store.claim("worker")
    token=store.issue_cancel_token("dev-user",run)["token"]; store.cancel("dev-user",run,token)
    before=store.get_run("dev-user",run)["events"]
    asyncio.run(RunProgressSink(store,"worker",claim).publish(ProgressEvent(plan_id="SENSITIVE",step_id="SENSITIVE",phase=ProgressPhase.EXECUTION,status=ProgressStatus.RUNNING,message_code="export_SENSITIVE")))
    assert store.get_run("dev-user",run)["events"]==before


def test_proposal_execution_failure_creates_one_bounded_real_resume(tmp_path):
    """执行前确认之后的首次失败仍暂停，人工恢复再次失败必须结束。"""
    class ProposalPlanner:
        calls = 0
        async def plan(self, **kwargs):
            self.calls += 1
            return PlanDecision.model_validate({"decision": "proposal", "plan_id": "bounded", "reason_code": "approval", "question": "执行？", "choices": ["确认", "取消"], "steps": [
                {"step_id": "prefix", "type": "enum_extract", "target_field": "alarm"},
                {"step_id": "pending", "type": "enum_extract", "target_field": "alarm"}]})
    planner = ProposalPlanner()
    client, store, conversation, worker = setup(tmp_path, planner)
    upload(client, conversation, "logs.txt", b"alarm=attack\n")
    assert worker.once()
    calls = []
    original_factory = worker.business_application.adapters_factory
    def adapters(team):
        result = original_factory(team)
        original = result["enum_extract"]
        class Interrupted:
            async def execute(self, step, context, dependencies):
                calls.append(step.step_id)
                if step.step_id == "pending":
                    raise TimeoutError("PRIVATE-TRANSIENT")
                return await original.execute(step, context, dependencies)
        result["enum_extract"] = Interrupted()
        return result
    worker.business_application.adapters_factory = adapters
    run = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "提取"}).json()["run"]["id"]
    assert worker.once()
    for expected in ("waiting_confirmation", "failed"):
        token = store.issue_resume_token("dev-user", run)
        assert client.post(f"/api/v2/runs/{run}/confirm", json={"token": token["token"], "checkpoint_revision": token["checkpoint_revision"]}).status_code == 200
        assert worker.once()
        assert store.get_run("dev-user", run)["status"] == expected
    assert planner.calls == 1 and calls == ["prefix", "pending", "pending", "pending"]
    continuation = store.continuation(run)
    assert continuation.next_action == "resume_after_failure"
    assert continuation.completed_step_refs == ("prefix",) and continuation.recovery_count == 1
    assert continuation.step_recovery_counts == {"pending": 1}
    assert not store.get_conversation("dev-user", conversation)["artifacts"]
    assert "PRIVATE-TRANSIENT" not in json.dumps(store.events("dev-user", conversation, 0))


def test_clear_preserves_classification_history_and_rejects_inactive_file(tmp_path):
    """清空后历史分类仍可查看，历史文件不能再次作为生产输入。"""
    from contracts.planner_models import LogClassificationArtifact, StepResult, StepStatus
    class ParsePlanner:
        async def plan(self, **kwargs):
            return PlanDecision.model_validate({"decision": "execute", "plan_id": "parse-history", "steps": [{"step_id": "parse", "type": "log_parse"}]})
    client, store, conversation, worker = setup(tmp_path, ParsePlanner())
    file = upload(client, conversation, "logs.txt", b"alarm=attack\n")["file"]
    assert worker.once()
    original_factory = worker.business_application.adapters_factory
    def adapters(team):
        result = original_factory(team)
        class Parse:
            async def execute(self, step, context, dependencies):
                context.session["log_classification"] = {"type": "history"}
                return StepResult(step_id=step.step_id, operation_type=step.type, status=StepStatus.SUCCESS,
                    artifact=LogClassificationArtifact(item_count=1, classification={"type": "history"}, submission_eligible=False))
        result["log_parse"] = Parse()
        return result
    worker.business_application.adapters_factory = adapters
    assert client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "分类"}).status_code == 201
    assert worker.once()
    classification = current(store, conversation, "log_classification")
    clear = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "清空数据"})
    assert clear.status_code == 201 and clear.json()["run"]["status"] == "queued"
    assert worker.once()
    reopened = Store(Settings(data_dir=store.root))
    detail = reopened.get_conversation("dev-user", conversation)
    assert all(not item["active"] for item in detail["files"])
    old = next(item for item in detail["artifacts"] if item["id"] == classification["id"])
    assert old["status"] == "stale" and not old["current"] and not old["mapping_eligible"]
    assert client.get(f"/api/v2/artifacts/{old['id']}/content").status_code == 200
    assert client.get(f"/api/v2/artifacts/{old['id']}/download").status_code == 200
    with pytest.raises(LookupError):
        reopened.enqueue_log_parse("dev-user", conversation, file["id"])


def test_clear_frozen_boundary_preserves_later_upload_and_corrupt_history(tmp_path):
    """清空只处理请求时的输入，损坏的旧内容不能挡住后续上传。"""
    from toolwithagent_v2.infrastructure.db import connect
    client, store, conversation, worker = setup(tmp_path, Planner())
    rules(client, conversation, worker)
    old = store.get_conversation("dev-user", conversation)["files"][0]
    with connect(store.path) as db:
        key = db.execute("SELECT storage_key FROM files WHERE id=?", (old["id"],)).fetchone()[0]
    (store.root / key).write_bytes(b"CORRUPT")
    clear = client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "清空数据"})
    assert clear.status_code == 201
    later = upload(client, conversation, "later.txt", b"alarm=new\n")["file"]
    assert worker.once()
    assert store.get_run("dev-user", clear.json()["run"]["id"])["status"] == "succeeded"
    assert worker.once()
    reopened = Store(Settings(data_dir=store.root))
    detail = reopened.get_conversation("dev-user", conversation)
    old_file = next(item for item in detail["files"] if item["id"] == old["id"])
    new_file = next(item for item in detail["files"] if item["id"] == later["id"])
    assert not old_file["active"] and new_file["active"] and new_file["mapping_eligible"]
    assert new_file["parse_status"] == "succeeded" and detail["session_facts"]["has_logs"]


def test_clear_rolls_back_if_final_worker_fence_is_lost(tmp_path, monkeypatch):
    """租约最终失效时不能提交清空的任何业务状态。"""
    client, store, conversation, worker = setup(tmp_path, Planner())
    rules(client, conversation, worker)
    assert client.post(f"/api/v2/conversations/{conversation}/messages", json={"content": "清空数据"}).status_code == 201
    claim = store.claim("worker")
    original = store._valid_claim
    calls = []
    def expires(db, worker_id, current_claim):
        calls.append(1)
        return original(db, worker_id, current_claim) if len(calls) == 1 else None
    monkeypatch.setattr(store, "_valid_claim", expires)
    assert not store.clear_business("worker", claim)
    assert len(calls) == 2
    detail = store.get_conversation("dev-user", conversation)
    assert detail["session_facts"]["has_decoded_config"] and all(item["active"] for item in detail["files"])
    assert not any(message["content"].startswith("业务数据已清空") for message in detail["messages"])
