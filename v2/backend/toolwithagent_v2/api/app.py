"""Independent FastAPI entry for the V2 workbench."""
import asyncio
import json
from uuid import uuid4
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field, ConfigDict
from typing import Annotated, Union
from contracts.planner_models import EnumExtractStep, ThreatMappingStep, FillStep, RemoveMappingStep, ExportStep

from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.settings import Settings


class ConversationInput(BaseModel):
    title: str | None = None


class ConversationRenameInput(BaseModel):
    title: str = Field(max_length=160)


class MessageInput(BaseModel):
    content: str


class OperationInput(BaseModel):
    """按钮复用现有严格 StepSpec，不允许前端构造步骤依赖。"""
    model_config = ConfigDict(extra="forbid")
    step: Annotated[Union[EnumExtractStep, ThreatMappingStep, FillStep, RemoveMappingStep, ExportStep], Field(discriminator="type")]
    source_artifact_id: str | None = None
    config_artifact_id: str | None = None


class FieldSelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_group_ids: list[str] = Field(max_length=1000)


class FieldApplyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str | None = None


class FakeRunInput(BaseModel):
    scenario: str = "success"
    session_facts: dict = Field(default_factory=dict)


class TokenInput(BaseModel):
    token: str


class ConfirmInput(BaseModel):
    token: str
    checkpoint_revision: int


class ForceStopInput(BaseModel):
    reason: str


class AdminCancelInput(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class KnowledgeReviewInput(BaseModel):
    reason: str = Field(default="", max_length=1000)


class ProviderSaveInput(BaseModel):
    model: str = Field(max_length=160)
    api_key: str = Field(max_length=4096)
    params: dict | None = None
    reason: str | None = Field(default=None, max_length=1000)


class ProviderTestInput(BaseModel):
    model: str | None = Field(default=None, max_length=160)
    api_key: str | None = Field(default=None, max_length=4096)
    params: dict | None = None


class UserRoleInput(BaseModel):
    role: str
    reason: str | None = Field(default=None, max_length=1000)


class UserActiveInput(BaseModel):
    active: bool
    reason: str | None = Field(default=None, max_length=1000)


class SessionInput(BaseModel):
    user_id: str


class LogParseInput(BaseModel):
    file_id: str
    feature_field: str | None = None


class FieldMappingInput(BaseModel):
    file_id: str | None = None
    classification_artifact_id: str | None = None
    product: str = Field(max_length=160)
    log_vendor: str = Field(max_length=160)
    data_source: str = Field(default="", max_length=160)


class MappingOperationInput(BaseModel):
    sub_rule_id: str = Field(max_length=20)
    source_path: str = Field(min_length=1,max_length=4096)
    standard_field: str | None = Field(default=None,max_length=160)
    linked_sub_rule_ids: list[str] = Field(default_factory=list,max_length=1000)


class MappingReplacementInput(BaseModel):
    operation_key: str = Field(min_length=1,max_length=80)
    proposal: MappingOperationInput
    confirm: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings)
    app = FastAPI(title="ToolWithAgent V2", version="0.1.0")
    app.state.store = store
    from agent.tools.log_pattern_store import LogKnowledgeError, LogKnowledgeRepository
    from toolwithagent_v2.infrastructure.providers import MasterKeyUnavailable

    knowledge_repository = LogKnowledgeRepository(store.path)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "Idempotency-Key", "If-Match"])

    def principal(request: Request):
        user_id = request.cookies.get("v2_dev_user") or ("dev-user" if settings.development else None)
        user = store.user(user_id) if user_id else None
        if user is None:
            raise HTTPException(401, "unauthenticated")
        return user

    def admin_writer(request: Request):
        user = principal(request)
        if user["role"] != "admin":
            raise HTTPException(403, "insufficient_capability")
        return user

    def developer_reader(request: Request):
        user = principal(request)
        if user["role"] not in ("developer", "admin"):
            raise HTTPException(403, "insufficient_capability")
        return user

    def translate_knowledge_error(exc: LogKnowledgeError):
        message = str(exc)
        if "not found" in message:
            raise LookupError("log_knowledge_not_found")
        if "replacement reason is required" in message:
            raise ValueError("log_knowledge_replacement_reason_required")
        if "only pending" in message:
            raise ValueError("log_knowledge_not_pending")
        if "only rejected" in message:
            raise ValueError("log_knowledge_not_rejected")
        raise ValueError("log_knowledge_review_failed")

    def user_writer(request: Request):
        user = principal(request)
        if user["role"] != "user":
            raise HTTPException(403, "insufficient_capability")
        return user

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: HTTPException):
        code = exc.detail if isinstance(exc.detail, str) else "request_failed"
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": code, "message": code, "details": {}, "request_id": request.state.request_id}})

    @app.exception_handler(LookupError)
    async def missing(request: Request, exc: LookupError):
        code = str(exc)
        return JSONResponse(status_code=404, content={"error": {"code": code, "message": code, "details": {}, "request_id": request.state.request_id}})

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        code = str(exc)
        status = 413 if code == "file_too_large" else (409 if code in {
            "field_revision_conflict", "field_preview_not_editable", "field_undo_stale", "field_preview_resolution_required",
            "idempotency_key_reused", "run_not_retryable", "task_has_active_run",
            "run_not_cancellable", "run_not_stoppable", "run_not_queued", "run_not_waiting",
            "log_knowledge_not_pending", "log_knowledge_not_rejected", "log_knowledge_review_failed",
            "log_knowledge_replacement_reason_required",
            "invalid_role", "role_unchanged", "cannot_change_own_role", "active_unchanged", "cannot_deactivate_self",
            "invalid_confirmation_token", "confirmation_expired", "continuation_stale",
            "confirmation_resolution_required", "artifact_source_stale", "config_source_stale", "business_input_stale",
            "mapping_base_stale", "mapping_catalog_changed", "draft_revision_conflict", "draft_apply_in_progress", "draft_not_editable",
            "draft_resolution_required", "mapping_target_conflict", "mapping_link_conflict", "mapping_draft_apply_stale",
        } else 400)
        if code == "draft_revision_required":
            status = 428
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": code, "details": getattr(exc,"details",{}), "request_id": request.state.request_id}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "invalid_request", "details": {}, "request_id": request.state.request_id}})

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/api/v2/me")
    def me(request: Request):
        return principal(request)

    if settings.development:
        @app.get("/api/v2/dev/identities")
        def identities():
            return {"items": store.users()}

        @app.post("/api/v2/dev/session")
        def session(payload: SessionInput, response: Response):
            user = store.user(payload.user_id)
            if user is None:
                raise HTTPException(404, "user_not_found")
            response.set_cookie("v2_dev_user", user["id"], httponly=True, samesite="lax")
            return user

    def field_revision(value):
        if value is None:
            raise HTTPException(428, "field_revision_required")
        try:
            revision = int(value)
        except (TypeError, ValueError):
            raise ValueError("invalid_field_revision") from None
        if revision < 1:
            raise ValueError("invalid_field_revision")
        return revision

    @app.get("/api/v2/runs/{run_id}/field-change-preview")
    def field_preview(request: Request, run_id: str):
        from toolwithagent_v2.infrastructure.field_changes import FieldChanges
        return FieldChanges(store).get(principal(request)["id"], run_id)

    @app.post("/api/v2/runs/{run_id}/field-change-selection")
    def field_selection(request: Request, run_id: str, payload: FieldSelectionInput, if_match: str | None = Header(default=None), idempotency_key: str | None = Header(default=None)):
        from toolwithagent_v2.infrastructure.field_changes import FieldChanges
        return FieldChanges(store).select(user_writer(request)["id"], run_id, field_revision(if_match), payload.selected_group_ids, idempotency_key)

    @app.post("/api/v2/runs/{run_id}/field-change-cancel")
    def field_cancel(request: Request, run_id: str, if_match: str | None = Header(default=None), idempotency_key: str | None = Header(default=None)):
        from toolwithagent_v2.infrastructure.field_changes import FieldChanges
        return FieldChanges(store).cancel(user_writer(request)["id"], run_id, field_revision(if_match), idempotency_key)

    @app.post("/api/v2/tasks/{task_id}/confirmations")
    def field_confirmation(request: Request, task_id: str, if_match: str | None = Header(default=None), idempotency_key: str | None = Header(default=None)):
        from toolwithagent_v2.infrastructure.field_changes import FieldChanges
        return FieldChanges(store).confirmation(user_writer(request)["id"], task_id, field_revision(if_match), idempotency_key)

    @app.post("/api/v2/runs/{run_id}/field-change-apply", status_code=201)
    def field_apply(request: Request, run_id: str, payload: FieldApplyInput, if_match: str | None = Header(default=None), idempotency_key: str | None = Header(default=None)):
        from toolwithagent_v2.infrastructure.field_changes import FieldChanges
        return FieldChanges(store).apply(user_writer(request)["id"], run_id, field_revision(if_match), idempotency_key, payload.token)

    @app.post("/api/v2/artifacts/{artifact_id}/undo", status_code=201)
    def field_undo(request: Request, artifact_id: str, idempotency_key: str | None = Header(default=None)):
        from toolwithagent_v2.infrastructure.field_changes import FieldChanges
        return FieldChanges(store).undo(user_writer(request)["id"], artifact_id, idempotency_key)

    @app.get("/api/v2/conversations")
    def list_conversations(request: Request):
        return {"items": store.list_conversations(principal(request)["id"])}

    @app.get("/api/v2/tasks")
    def user_tasks(request: Request, status: str | None = None, page: int = 1):
        if page < 1 or (status and status not in {"queued", "running", "waiting_confirmation", "succeeded", "failed", "cancelling", "cancelled"}):
            raise HTTPException(422, "invalid_history_filter")
        return store.user_tasks(principal(request)["id"], status=status, page=page)

    @app.get("/api/v2/runs")
    def user_runs(request: Request, status: str | None = None, page: int = 1):
        if page < 1 or (status and status not in {"queued", "running", "waiting_confirmation", "succeeded", "failed", "cancelling", "cancelled"}):
            raise HTTPException(422, "invalid_history_filter")
        return store.user_runs(principal(request)["id"], status=status, page=page)

    @app.post("/api/v2/conversations", status_code=201)
    def create_conversation(request: Request, payload: ConversationInput):
        return store.create_conversation(user_writer(request)["id"], payload.title)

    @app.get("/api/v2/conversations/{conversation_id}")
    def get_conversation(request: Request, conversation_id: str):
        return store.get_conversation(principal(request)["id"], conversation_id)

    @app.patch("/api/v2/conversations/{conversation_id}")
    def rename_conversation(request: Request, conversation_id: str, payload: ConversationRenameInput):
        return store.rename_conversation(principal(request)["id"], conversation_id, payload.title)

    @app.post("/api/v2/conversations/{conversation_id}/messages", status_code=201)
    def create_message(request: Request, conversation_id: str, payload: MessageInput, idempotency_key: str | None = Header(None)):
        store.get_conversation(principal(request)["id"], conversation_id)
        return store.create_message(user_writer(request)["id"], conversation_id, payload.content, idempotency_key)

    @app.post("/api/v2/conversations/{conversation_id}/files", status_code=201)
    def upload_file(request: Request, conversation_id: str, file: UploadFile = File(...), role: str = Form("primary"), idempotency_key: str | None = Header(None)):
        try:
            store.get_conversation(principal(request)["id"], conversation_id)
            return store.upload(user_writer(request)["id"], conversation_id, file, idempotency_key, role)
        finally:
            file.file.close()

    @app.post("/api/v2/conversations/{conversation_id}/log-parse", status_code=201)
    def enqueue_log_parse(request: Request, conversation_id: str, payload: LogParseInput):
        return store.enqueue_log_parse(user_writer(request)["id"], conversation_id, payload.file_id, payload.feature_field)

    @app.post("/api/v2/conversations/{conversation_id}/field-mapping", status_code=201)
    def enqueue_field_mapping(request: Request, conversation_id: str, payload: FieldMappingInput, idempotency_key: str | None = Header(None)):
        return store.enqueue_field_mapping(user_writer(request)["id"], conversation_id,
                                          **payload.model_dump(), idempotency_key=idempotency_key)

    @app.post("/api/v2/conversations/{conversation_id}/operations", status_code=201)
    def enqueue_operation(request: Request, conversation_id: str, payload: OperationInput, idempotency_key: str | None = Header(None)):
        return store.enqueue_operation(user_writer(request)["id"], conversation_id, payload.step,
            payload.source_artifact_id, payload.config_artifact_id, idempotency_key)

    @app.get("/api/v2/artifacts/{artifact_id}/content")
    def artifact_content(request: Request, artifact_id: str):
        return store.artifact_content(principal(request)["id"], artifact_id)

    @app.get("/api/v2/artifacts/{artifact_id}/mapping-view")
    def mapping_view(request: Request, artifact_id: str, sub_rule: str | None = None, page: int = 1, q: str = "", status: str | None = None, draft_id: str | None = None):
        return store.mapping_view(principal(request)["id"], artifact_id, sub_rule, page, q, status,draft_id)

    def draft_revision(value):
        if value is None:
            raise ValueError("draft_revision_required")
        value = value.strip('"')
        if not value.isdecimal() or int(value) < 1:
            raise ValueError("invalid_draft_revision")
        return int(value)

    @app.get("/api/v2/standard-fields")
    def standard_fields(request: Request, draft_id: str | None = None, sub_rule: str | None = None, q: str = ""):
        return store.standard_fields(principal(request)["id"],draft_id,sub_rule,q)

    @app.post("/api/v2/artifacts/{artifact_id}/mapping-drafts")
    def create_mapping_draft(request: Request, artifact_id: str):
        return store.create_mapping_draft(user_writer(request)["id"],artifact_id)

    @app.get("/api/v2/mapping-drafts/{draft_id}")
    def get_mapping_draft(request: Request, draft_id: str):
        return store.get_mapping_draft(principal(request)["id"],draft_id)

    @app.patch("/api/v2/mapping-drafts/{draft_id}/operations/{operation_key}")
    def save_mapping_operation(request: Request, draft_id: str, operation_key: str, payload: MappingOperationInput, if_match: str | None = Header(None)):
        return store.save_mapping_operation(user_writer(request)["id"],draft_id,operation_key,payload.model_dump(),draft_revision(if_match))

    @app.get("/api/v2/mapping-drafts/{draft_id}/same-source-candidates/{operation_key}")
    def mapping_candidates(request: Request, draft_id: str, operation_key: str):
        return store.mapping_candidates(principal(request)["id"],draft_id,operation_key)

    @app.post("/api/v2/mapping-drafts/{draft_id}/replacement-confirmations")
    def confirm_mapping_replacement(request: Request, draft_id: str, payload: MappingReplacementInput, if_match: str | None = Header(None), idempotency_key: str | None = Header(None)):
        return store.confirm_mapping_replacement(user_writer(request)["id"],draft_id,payload.operation_key,payload.proposal.model_dump(),payload.confirm,draft_revision(if_match),idempotency_key)

    @app.post("/api/v2/mapping-drafts/{draft_id}/apply",status_code=201)
    def apply_mapping_draft(request: Request, draft_id: str, if_match: str | None = Header(None), idempotency_key: str | None = Header(None)):
        return store.apply_mapping_draft(user_writer(request)["id"],draft_id,draft_revision(if_match),idempotency_key)

    @app.delete("/api/v2/mapping-drafts/{draft_id}")
    def discard_mapping_draft(request: Request, draft_id: str, if_match: str | None = Header(None)):
        return store.discard_mapping_draft(user_writer(request)["id"],draft_id,draft_revision(if_match))

    @app.get("/api/v2/artifacts/{artifact_id}/download")
    def mapping_download(request: Request, artifact_id: str):
        name, content, media = store.artifact_download(principal(request)["id"], artifact_id)
        return Response(content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/v2/artifacts/{artifact_id}/submit-log-knowledge", status_code=201)
    def submit_log_knowledge(request: Request, artifact_id: str):
        return store.enqueue_log_knowledge(user_writer(request)["id"], artifact_id)

    if settings.development:
        @app.post("/api/v2/dev/conversations/{conversation_id}/fake-runs", status_code=201)
        def enqueue_fake(request: Request, conversation_id: str, payload: FakeRunInput):
            return store.enqueue_fake(user_writer(request)["id"], conversation_id, payload.scenario, payload.session_facts)

    @app.post("/api/v2/runs/{run_id}/retry", status_code=201)
    def retry_run(request: Request, run_id: str, idempotency_key: str | None = Header(None)):
        return store.retry(user_writer(request)["id"], run_id, idempotency_key)

    @app.post("/api/v2/runs/{run_id}/cancel-token")
    def cancel_token(request: Request, run_id: str):
        return store.issue_cancel_token(user_writer(request)["id"], run_id)

    @app.post("/api/v2/runs/{run_id}/cancel")
    def cancel_run(request: Request, run_id: str, payload: TokenInput):
        return store.cancel(user_writer(request)["id"], run_id, payload.token)

    @app.post("/api/v2/runs/{run_id}/confirmation-token")
    def confirmation_token(request: Request, run_id: str):
        return store.issue_resume_token(user_writer(request)["id"], run_id)

    @app.post("/api/v2/runs/{run_id}/confirm")
    def confirm_run(request: Request, run_id: str, payload: ConfirmInput, idempotency_key: str | None = Header(None)):
        return store.confirm(user_writer(request)["id"], run_id, payload.token, payload.checkpoint_revision, idempotency_key)

    @app.post("/api/v2/admin/runs/{run_id}/force-stop")
    def force_stop(request: Request, run_id: str, payload: ForceStopInput):
        user = principal(request)
        if user["role"] != "admin":
            raise HTTPException(403, "insufficient_capability")
        return store.force_stop(user["id"], run_id, payload.reason)

    @app.get("/api/v2/admin/overview")
    def admin_overview(request: Request):
        user = principal(request)
        if user["role"] != "admin":
            raise HTTPException(403, "insufficient_capability")
        return store.admin_overview(user["id"])

    @app.get("/api/v2/admin/runs")
    def admin_runs(request: Request, status: str | None = None, page: int = 1):
        user = principal(request)
        if user["role"] != "admin":
            raise HTTPException(403, "insufficient_capability")
        return store.admin_runs(user["id"], status=status or None, page=page)

    @app.post("/api/v2/admin/runs/{run_id}/cancel")
    def admin_cancel_run(request: Request, run_id: str, payload: AdminCancelInput):
        user = principal(request)
        if user["role"] != "admin":
            raise HTTPException(403, "insufficient_capability")
        return store.admin_cancel_queued(user["id"], run_id, payload.reason)

    @app.get("/api/v2/admin/audit-events")
    def admin_audit_events(request: Request, page: int = 1):
        user = principal(request)
        if user["role"] != "admin":
            raise HTTPException(403, "insufficient_capability")
        return store.admin_audit_events(user["id"], page=page)

    @app.get("/api/v2/admin/log-knowledge")
    def admin_log_knowledge(request: Request, status: str | None = None, page: int = 1):
        admin_writer(request)
        try:
            return knowledge_repository.list_applications(status=status or None, page=page)
        except ValueError:
            raise HTTPException(422, "invalid_request")

    @app.get("/api/v2/admin/log-knowledge/{application_id}")
    def admin_log_knowledge_detail(request: Request, application_id: int):
        admin_writer(request)
        try:
            detail = knowledge_repository.get_review_detail(application_id)
        except LogKnowledgeError as exc:
            translate_knowledge_error(exc)
        samples = list(detail.samples)[:10]
        application = detail.application
        return {
            "application_id": detail.application_id, "status": detail.status,
            "recipe_version": application.recipe_version, "structure_hash": application.structure_hash,
            "structure_tokens": list(application.structure_tokens), "format_type": application.format_type,
            "selection_mode": application.selection_mode, "feature_field": application.feature_field,
            "extractor_type": application.extractor_type, "extractor_spec": application.extractor_spec,
            "submission_note": application.submission_note, "created_at": detail.created_at,
            "reviewed_at": detail.reviewed_at, "reviewer": detail.reviewer, "review_reason": detail.review_reason,
            "replaces_application_id": detail.replaces_application_id,
            "replaced_by_application_id": detail.replaced_by_application_id,
            "sample_count": len(detail.samples), "samples": samples,
        }

    @app.post("/api/v2/admin/log-knowledge/{application_id}/approve")
    def admin_log_knowledge_approve(request: Request, application_id: int, payload: KnowledgeReviewInput):
        user = admin_writer(request)
        try:
            knowledge_repository.approve(application_id, reviewer=user["id"], reason=payload.reason)
        except LogKnowledgeError as exc:
            translate_knowledge_error(exc)
        detail = knowledge_repository.get_review_detail(application_id)
        store.admin_audit(user["id"], "log_knowledge_approve", "log_knowledge", str(application_id),
                          payload.reason, before={"status": "pending"}, after={"status": "approved",
                          "replaces_application_id": detail.replaces_application_id})
        return {"application_id": application_id, "status": "approved", "replaces_application_id": detail.replaces_application_id}

    @app.post("/api/v2/admin/log-knowledge/{application_id}/reject")
    def admin_log_knowledge_reject(request: Request, application_id: int, payload: KnowledgeReviewInput):
        user = admin_writer(request)
        if not payload.reason.strip():
            raise ValueError("log_knowledge_reason_required")
        try:
            knowledge_repository.reject(application_id, reviewer=user["id"], reason=payload.reason.strip())
        except LogKnowledgeError as exc:
            translate_knowledge_error(exc)
        store.admin_audit(user["id"], "log_knowledge_reject", "log_knowledge", str(application_id),
                          payload.reason.strip(), before={"status": "pending"}, after={"status": "rejected"})
        return {"application_id": application_id, "status": "rejected"}

    @app.delete("/api/v2/admin/log-knowledge/{application_id}")
    def admin_log_knowledge_delete(request: Request, application_id: int):
        user = admin_writer(request)
        try:
            knowledge_repository.delete_rejected(application_id)
        except LogKnowledgeError as exc:
            translate_knowledge_error(exc)
        store.admin_audit(user["id"], "log_knowledge_delete", "log_knowledge", str(application_id),
                          before={"status": "rejected"}, after={"status": "deleted"})
        return {"application_id": application_id, "status": "deleted"}

    @app.exception_handler(MasterKeyUnavailable)
    async def master_key_error(request: Request, exc: MasterKeyUnavailable):
        return JSONResponse(status_code=503, content={"error": {"code": str(exc), "message": str(exc), "details": {}, "request_id": request.state.request_id}})

    @app.get("/api/v2/admin/providers")
    def admin_providers(request: Request):
        admin_writer(request)
        return store.admin_providers(principal(request)["id"])

    @app.get("/api/v2/admin/providers/{provider}/history")
    def admin_provider_history(request: Request, provider: str):
        admin_writer(request)
        try:
            return store.admin_provider_history(principal(request)["id"], provider)
        except LookupError:
            raise HTTPException(404, "provider_not_found")

    @app.put("/api/v2/admin/providers/{provider}")
    def admin_save_provider(request: Request, provider: str, payload: ProviderSaveInput):
        user = admin_writer(request)
        try:
            result = store.admin_save_provider(user["id"], provider, payload.model, payload.api_key, payload.params, payload.reason)
        except LookupError:
            raise HTTPException(404, "provider_not_found")
        except ValueError:
            raise HTTPException(400, "invalid_provider_input")
        return result

    @app.post("/api/v2/admin/providers/{provider}/test")
    def admin_test_provider(request: Request, provider: str, payload: ProviderTestInput):
        user = admin_writer(request)
        try:
            return store.admin_test_provider(user["id"], provider, payload.model, payload.api_key, payload.params)
        except LookupError:
            raise HTTPException(404, "provider_not_found")

    @app.get("/api/v2/admin/users")
    def admin_users(request: Request):
        user = admin_writer(request)
        return store.admin_users(user["id"])

    @app.post("/api/v2/admin/users/{user_id}/role")
    def admin_set_user_role(request: Request, user_id: str, payload: UserRoleInput):
        user = admin_writer(request)
        try:
            return store.admin_set_role(user["id"], user_id, payload.role, payload.reason)
        except LookupError:
            raise HTTPException(404, "user_not_found")

    @app.post("/api/v2/admin/users/{user_id}/active")
    def admin_set_user_active(request: Request, user_id: str, payload: UserActiveInput):
        user = admin_writer(request)
        try:
            return store.admin_set_active(user["id"], user_id, payload.active, payload.reason)
        except LookupError:
            raise HTTPException(404, "user_not_found")

    @app.get("/api/v2/runs/{run_id}")
    def get_run(request: Request, run_id: str):
        return store.get_run(principal(request)["id"], run_id)

    def own_run(request: Request, run_id: str):
        store.get_run(principal(request)["id"], run_id)

    @app.get("/api/v2/runs/{run_id}/diagnostics")
    def user_run_diagnostics(request: Request, run_id: str):
        own_run(request, run_id)
        return store.diagnostic_run(run_id)

    @app.get("/api/v2/runs/{run_id}/logs")
    def user_run_logs(request: Request, run_id: str, after: int = 0):
        own_run(request, run_id)
        return store.diagnostic_logs(run_id, after)

    @app.get("/api/v2/runs/{run_id}/calls/{call_id}")
    def user_run_call(request: Request, run_id: str, call_id: str):
        own_run(request, run_id)
        return store.diagnostic_call(run_id, call_id)

    @app.get("/api/v2/runs/{run_id}/bundle")
    def user_run_bundle(request: Request, run_id: str):
        own_run(request, run_id)
        detail = store.diagnostic_run(run_id, include_content=True, include_all_logs=True)
        return Response(content=json.dumps(detail, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="run-{run_id}.json"',
                                 "Cache-Control": "no-store"})

    @app.get("/api/v2/developer/runs")
    def developer_runs(request: Request, status: str | None = None, page: int = 1):
        developer_reader(request)
        return store.admin_runs("", status=status or None, page=page)

    @app.get("/api/v2/developer/runs/{run_id}/bundle")
    def developer_run_bundle(request: Request, run_id: str):
        developer_reader(request)
        detail = store.diagnostic_run(run_id, include_content=True, include_all_logs=True)
        return Response(content=json.dumps(detail, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="run-{detail["run"]["id"]}.json"',
                                 "Cache-Control": "no-store"})

    @app.get("/api/v2/developer/runs/{run_id}")
    def developer_run(request: Request, run_id: str):
        developer_reader(request)
        return store.diagnostic_run(run_id)

    @app.get("/api/v2/developer/runs/{run_id}/calls/{call_id}")
    def developer_run_call(request: Request, run_id: str, call_id: str):
        developer_reader(request)
        return store.diagnostic_call(run_id, call_id)

    @app.get("/api/v2/developer/runs/{run_id}/logs")
    def developer_run_logs(request: Request, run_id: str, after: int = 0):
        developer_reader(request)
        return store.diagnostic_logs(run_id, after)

    @app.get("/api/v2/conversations/{conversation_id}/events")
    async def conversation_events(request: Request, conversation_id: str, after: int = 0):
        user_id = principal(request)["id"]
        if after < 0:
            raise HTTPException(400, "invalid_cursor")
        store.events(user_id, conversation_id, after)

        async def stream():
            cursor = after
            while not await request.is_disconnected():
                batch = store.events(user_id, conversation_id, cursor)
                for event in batch:
                    cursor = event["sequence"]
                    data = {k: v for k, v in event.items() if k != "payload_json"}
                    yield f"id: {cursor}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.3)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app
