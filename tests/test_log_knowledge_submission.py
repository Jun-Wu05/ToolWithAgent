"""日志知识显式提交的资格、生命周期与执行接缝测试。"""

import asyncio

from application.log_knowledge_submission import build_submission_snapshot

from factories import make_session_state


def _classification(**overrides):
    value = {
        "status": "SUCCESS",
        "log_format": "kv",
        "log_format_detail": "KV",
        "feature_field": " Event.Type ",
        "feature_identifier": "",
        "analysis": {"delimit": " ", "tab": "="},
        "coverage": {"total_lines": 3, "matched_lines": 3},
        "classification_details": [{"logtype": "attack", "count": 3}],
    }
    value.update(overrides)
    return value


def test完整成功且三条可回放真实日志才生成eligible快照():
    lines = [
        "Event.Type=attack src=1",
        "Event.Type=scan src=2",
        "Event.Type=audit src=3",
    ]

    snapshot = build_submission_snapshot(
        _classification(),
        lines,
        selection_mode="explicit",
        feature_field=" Event.Type ",
    )

    assert snapshot.eligible is True
    assert snapshot.ineligible_reason is None
    assert snapshot.feature_field == "event.type"
    assert snapshot.selection_mode == "explicit"
    assert snapshot.extractor_type == "field_path"
    assert len(snapshot.samples) == 3
    assert snapshot.dataset_digest
    assert snapshot.classification_digest


def test资格门槛拒绝不完整低覆盖少样例与不可执行配方():
    lines = ["kind=a", "kind=b", "kind=c"]

    assert build_submission_snapshot(
        _classification(status="PARTIAL"), lines, selection_mode="automatic"
    ).ineligible_reason == "classification_incomplete"
    assert build_submission_snapshot(
        _classification(coverage={"total_lines": 10, "matched_lines": 7}),
        lines,
        selection_mode="automatic",
    ).ineligible_reason == "coverage_insufficient"
    assert build_submission_snapshot(
        _classification(feature_field="kind"),
        lines[:2],
        selection_mode="automatic",
    ).ineligible_reason == "samples_insufficient"
    assert build_submission_snapshot(
        _classification(feature_field=""), lines, selection_mode="automatic"
    ).ineligible_reason == "recipe_unavailable"


def test覆盖率按配方在真实主数据上的回放结果计算而非信任分类自报():
    lines = ["kind=a", "kind=b", "kind=c"] + [f"other={index}" for index in range(7)]
    snapshot = build_submission_snapshot(
        _classification(
            feature_field="kind",
            coverage={"total_lines": 10, "matched_lines": 10},
        ),
        lines,
        selection_mode="automatic",
    )
    assert snapshot.coverage == 0.3
    assert snapshot.ineligible_reason == "coverage_insufficient"


def test覆盖率扫描全量日志且审核样例上限不降低覆盖率():
    lines = [f"kind={index % 4}" for index in range(20)]

    snapshot = build_submission_snapshot(
        _classification(feature_field="kind"),
        lines,
        selection_mode="automatic",
    )

    assert snapshot.coverage == 1.0
    assert snapshot.eligible is True
    assert len(snapshot.samples) == 4


def test自动与显式身份隔离且显式字段规范化():
    lines = ["Type=a", "Type=b", "Type=c"]
    classification = _classification(feature_field="Type")

    automatic = build_submission_snapshot(
        classification, lines, selection_mode="automatic"
    )
    explicit = build_submission_snapshot(
        classification,
        lines,
        selection_mode="explicit",
        feature_field="Ｔｙｐｅ ",
    )

    assert automatic.selection_mode == "automatic"
    assert automatic.feature_field == ""
    assert explicit.selection_mode == "explicit"
    assert explicit.feature_field == "type"
    assert automatic.identity_digest != explicit.identity_digest


class _Repository:
    def __init__(self, status="created", error=None):
        self.status = status
        self.error = error
        self.calls = []

    def submit_application(self, application, samples):
        self.calls.append((application, samples))
        if self.error is not None:
            raise self.error
        from agent.tools.log_pattern_store import LogKnowledgeSubmissionResult

        return LogKnowledgeSubmissionResult(self.status, 7)


def _eligible_session():
    lines = ["kind=a", "kind=b", "kind=c"]
    classification = _classification(feature_field="kind")
    classification["coverage"] = {"total_lines": 3, "matched_lines": 3}
    return make_session_state(
        raw_log_lines=lines,
        log_classification=classification,
        log_knowledge_submission=build_submission_snapshot(
            classification, lines, selection_mode="automatic"
        ),
    )


def _execute_submit(session, repository):
    from application.adapters.log_knowledge_submit import LogKnowledgeSubmitAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import LogKnowledgeSubmitStep

    step = LogKnowledgeSubmitStep(
        step_id="submit",
        type="log_knowledge_submit",
        submission_token=session.log_knowledge_submission.submission_token,
    )
    return asyncio.run(
        LogKnowledgeSubmitAdapter(repository=repository).execute(
            step,
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )


def test_submit_adapter重验新鲜度后原子提交且保留分类结果():
    session = _eligible_session()
    classification = session.log_classification
    repository = _Repository("created")

    result = _execute_submit(session, repository)

    assert result.artifact.submission_status == "created"
    assert result.artifact.application_id == 7
    assert result.status.value == "success"
    assert "7" in (result.message or "")
    assert len(repository.calls) == 1
    assert session.log_classification is classification


def test_submit_adapter过期与仓储错误都不改变分类结果():
    session = _eligible_session()
    classification = session.log_classification
    session.raw_log_lines.append("kind=changed")
    repository = _Repository()

    stale = _execute_submit(session, repository)

    assert stale.artifact.submission_status == "stale"
    assert stale.status.value == "failed"
    assert stale.error_code == "log_knowledge_submission_stale"
    assert repository.calls == []
    assert session.log_classification is classification

    session = _eligible_session()
    classification = session.log_classification
    failed = _execute_submit(session, _Repository(error=RuntimeError("raw-secret")))
    assert failed.artifact.submission_status == "error"
    assert failed.status.value == "failed"
    assert failed.error_code == "log_knowledge_submission_error"
    assert "raw-secret" not in (failed.message or "")
    assert session.log_classification is classification


def test_submit_adapter映射pending重复与已批准状态():
    for repository_status, expected in (
        ("pending_duplicate", "pending_duplicate"),
        ("already_approved", "already_approved"),
    ):
        result = _execute_submit(_eligible_session(), _Repository(repository_status))
        assert result.artifact.submission_status == expected
        assert result.status.value == "success"
        assert "7" in (result.message or "")


def test新主数据原子替换时旧提交快照失效():
    from application.file_input import commit_primary_dataset
    from application.session_state import PrimaryDatasetSnapshot

    session = _eligible_session()
    commit_primary_dataset(
        session,
        PrimaryDatasetSnapshot(
            decoded_data={"raw_text": "kind=new"},
            decoded_fields=[],
            original_log=["kind=new"],
            simplified_data={"fields": [], "original_log_sample": "kind=new"},
            decoded_text="kind=new",
            uploaded_file_name="new.txt",
            uploaded_file_time="10:00:00",
            raw_log_lines=["kind=new"],
        ),
    )

    assert session.log_knowledge_submission is None
    assert session.log_classification is None


def test旧结果按钮在重解析产生新快照后必须stale且零写入():
    from application.adapters.log_knowledge_submit import LogKnowledgeSubmitAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import LogKnowledgeSubmitStep

    session = _eligible_session()
    old_token = session.log_knowledge_submission.submission_token
    new_lines = ["kind=x", "kind=y", "kind=z"]
    new_classification = _classification(feature_field="kind")
    session.raw_log_lines = new_lines
    session.log_classification = new_classification
    session.log_knowledge_submission = build_submission_snapshot(
        new_classification, new_lines, selection_mode="automatic"
    )
    repository = _Repository()
    result = asyncio.run(
        LogKnowledgeSubmitAdapter(repository=repository).execute(
            LogKnowledgeSubmitStep(
                step_id="submit",
                type="log_knowledge_submit",
                submission_token=old_token,
            ),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )
    assert result.artifact.submission_status == "stale"
    assert repository.calls == []
