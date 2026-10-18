"""日志知识显式提交适配器：重验快照后调用 SQLite 仓储。"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from application.adapters.shared import _success
from application.execution import ExecutionContext
from application.log_knowledge_submission import (
    LogKnowledgeSubmissionSnapshot,
    build_submission_snapshot,
)
from contracts.planner_models import (
    LogKnowledgeSubmissionArtifact,
    LogKnowledgeSubmitStep,
    StepResult,
    StepSpec,
    StepStatus,
)


logger = logging.getLogger("log_knowledge_submission")

_MESSAGES = {
    "created": "日志知识申请已提交，等待管理员审核",
    "pending_duplicate": "相同日志知识申请已在审核中，已补充去重样例",
    "already_approved": "相同日志知识已批准，无需重复申请",
    "stale": "当前主数据或分类结果已变化，请重新执行日志类型提取后再申请",
    "error": "日志知识申请暂时无法提交；现有分类结果不受影响",
}


class LogKnowledgeSubmitAdapter:
    """执行按钮专用提交步骤，不读取用户原文。"""

    def __init__(self, repository: Any | None = None) -> None:
        self._repository = repository

    def _repository_instance(self) -> Any:
        if self._repository is not None:
            return self._repository
        from agent.tools.log_pattern_store import LogKnowledgeRepository

        return LogKnowledgeRepository()

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """重验主数据、分类、样例血缘和配方后，在单事务中提交。"""
        del dependencies
        if not isinstance(step, LogKnowledgeSubmitStep):
            raise TypeError("LogKnowledgeSubmitAdapter 只接受 LogKnowledgeSubmitStep")

        snapshot = context.session.log_knowledge_submission
        classification = context.session.log_classification
        raw_lines = context.session.raw_log_lines or context.session.original_log
        if not isinstance(snapshot, LogKnowledgeSubmissionSnapshot) or not isinstance(
            classification, dict
        ):
            return self._result(step, "stale")
        if snapshot.submission_token != step.submission_token:
            return self._result(step, "stale")
        refreshed = build_submission_snapshot(
            classification,
            raw_lines,
            selection_mode=snapshot.selection_mode,
            feature_field=(
                snapshot.feature_field
                if snapshot.selection_mode == "explicit"
                else None
            ),
        )
        if not (
            snapshot.eligible
            and refreshed.eligible
            and refreshed.dataset_digest == snapshot.dataset_digest
            and refreshed.classification_digest == snapshot.classification_digest
            and refreshed.identity_digest == snapshot.identity_digest
            and refreshed.sample_hashes == snapshot.sample_hashes
        ):
            logger.info(
                "[LOG_KNOWLEDGE_SUBMIT] stale identity=%s dataset=%s classification=%s",
                snapshot.identity_digest[:12],
                snapshot.dataset_digest[:12],
                snapshot.classification_digest[:12],
            )
            return self._result(step, "stale")

        from agent.tools.log_pattern_store import LogKnowledgeApplicationInput

        application = LogKnowledgeApplicationInput(
            recipe_version=snapshot.recipe_version,
            structure_hash=snapshot.structure_hash,
            structure_tokens=snapshot.structure_tokens,
            format_type=snapshot.format_type,
            format_spec=snapshot.format_spec,
            selection_mode=snapshot.selection_mode,
            feature_field=snapshot.feature_field,
            extractor_type=snapshot.extractor_type,
            extractor_spec=snapshot.extractor_spec,
            submitter="session-user",
        )
        try:
            stored = self._repository_instance().submit_application(
                application, snapshot.samples
            )
        except Exception as error:
            logger.error(
                "[LOG_KNOWLEDGE_SUBMIT] repository failure type=%s identity=%s sample_count=%s",
                type(error).__name__,
                snapshot.identity_digest[:12],
                len(snapshot.samples),
            )
            return self._result(step, "error")
        logger.info(
            "[LOG_KNOWLEDGE_SUBMIT] status=%s application_id=%s sample_count=%s identity=%s",
            stored.status,
            stored.application_id,
            len(snapshot.samples),
            snapshot.identity_digest[:12],
        )
        return self._result(step, stored.status, stored.application_id)

    @staticmethod
    def _result(
        step: LogKnowledgeSubmitStep,
        status: str,
        application_id: int | None = None,
    ) -> StepResult:
        artifact = LogKnowledgeSubmissionArtifact(
            submission_status=status,
            application_id=application_id,
            item_count=1 if application_id is not None else 0,
        )
        message = _MESSAGES[status]
        if application_id is not None:
            message = f"{message}（申请编号 {application_id}）"
        if status in {"stale", "error"}:
            return StepResult(
                step_id=step.step_id,
                operation_type=step.type,
                status=StepStatus.FAILED,
                artifact=artifact,
                error_code=f"log_knowledge_submission_{status}",
                message=message,
            )
        return _success(step, artifact, message=message)
