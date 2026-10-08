"""Independent FastAPI entry for the V2 workbench."""
import asyncio
import json
from uuid import uuid4
from fastapi import FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.settings import Settings


class ConversationInput(BaseModel):
    title: str | None = None


class MessageInput(BaseModel):
    content: str


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


class SessionInput(BaseModel):
    user_id: str


class LogParseInput(BaseModel):
    file_id: str
    feature_field: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings)
    app = FastAPI(title="ToolWithAgent V2", version="0.1.0")
    app.state.store = store
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Idempotency-Key"])

    def principal(request: Request):
        user_id = request.cookies.get("v2_dev_user") or ("dev-user" if settings.development else None)
        user = store.user(user_id) if user_id else None
        if user is None:
            raise HTTPException(401, "unauthenticated")
        return user

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
            "idempotency_key_reused", "run_not_retryable", "task_has_active_run",
            "run_not_cancellable", "run_not_stoppable", "run_not_waiting",
            "invalid_confirmation_token", "confirmation_expired",
        } else 400)
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": code, "details": {}, "request_id": request.state.request_id}})

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

    @app.get("/api/v2/conversations")
    def list_conversations(request: Request):
        return {"items": store.list_conversations(principal(request)["id"])}

    @app.post("/api/v2/conversations", status_code=201)
    def create_conversation(request: Request, payload: ConversationInput):
        return store.create_conversation(user_writer(request)["id"], payload.title)

    @app.get("/api/v2/conversations/{conversation_id}")
    def get_conversation(request: Request, conversation_id: str):
        return store.get_conversation(principal(request)["id"], conversation_id)

    @app.post("/api/v2/conversations/{conversation_id}/messages", status_code=201)
    def create_message(request: Request, conversation_id: str, payload: MessageInput, idempotency_key: str | None = Header(None)):
        store.get_conversation(principal(request)["id"], conversation_id)
        return store.create_message(user_writer(request)["id"], conversation_id, payload.content, idempotency_key)

    @app.post("/api/v2/conversations/{conversation_id}/files", status_code=201)
    def upload_file(request: Request, conversation_id: str, file: UploadFile = File(...), idempotency_key: str | None = Header(None)):
        try:
            store.get_conversation(principal(request)["id"], conversation_id)
            return store.upload(user_writer(request)["id"], conversation_id, file, idempotency_key)
        finally:
            file.file.close()

    @app.post("/api/v2/conversations/{conversation_id}/log-parse", status_code=201)
    def enqueue_log_parse(request: Request, conversation_id: str, payload: LogParseInput):
        return store.enqueue_log_parse(user_writer(request)["id"], conversation_id, payload.file_id, payload.feature_field)

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
    def confirm_run(request: Request, run_id: str, payload: ConfirmInput):
        return store.confirm(user_writer(request)["id"], run_id, payload.token, payload.checkpoint_revision)

    @app.post("/api/v2/admin/runs/{run_id}/force-stop")
    def force_stop(request: Request, run_id: str, payload: ForceStopInput):
        user = principal(request)
        if user["role"] != "admin":
            raise HTTPException(403, "insufficient_capability")
        return store.force_stop(user["id"], run_id, payload.reason)

    @app.get("/api/v2/runs/{run_id}")
    def get_run(request: Request, run_id: str):
        return store.get_run(principal(request)["id"], run_id)

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
