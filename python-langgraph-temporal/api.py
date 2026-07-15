"""HTTP gateway for the Temporal + LangGraph support agent.

Each endpoint is one Temporal client call. The workflow ID is the conversation
ID, so the gateway can stay stateless.

    uv run python -m uvicorn api:app --port 8002
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from temporalio.client import Client, WorkflowUpdateFailedError
from temporalio.service import RPCError, RPCStatusCode

import config
from support_agent_common.conversations import new_conversation_id
from support_agent_common.demo_controls import (
    DemoControlState,
    get_demo_controls,
    update_demo_controls,
)
from activities.tools import execute_tool_local
from models.types import ApprovalDecision, ToolRequest
from workflows.agent import SupportAgentWorkflow


BACKEND_ID = "temporal-langgraph"
ENABLED_RANDOM_FAILURE_RATE = 0.5


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.temporal = await config.temporal_client()
    yield


app = FastAPI(title="support-agent Temporal LangGraph gateway", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
api = APIRouter()


@app.exception_handler(HTTPException)
async def error_shape(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


class CreateConversation(BaseModel):
    customerEmail: str


class SendMessage(BaseModel):
    text: str


class Approve(BaseModel):
    approvalId: str
    approved: bool
    reason: str | None = None


class DemoControlUpdate(BaseModel):
    randomOpenAIFailures: bool | None = None
    openAIResponsesOutage: bool | None = None
    workerEnabled: bool | None = None


def _client() -> Client:
    return app.state.temporal


def _handle(conversation_id: str):
    return _client().get_workflow_handle_for(SupportAgentWorkflow.run, conversation_id)


def _not_found(e: RPCError):
    if e.status == RPCStatusCode.NOT_FOUND:
        raise HTTPException(status_code=404, detail="unknown conversation") from e
    raise e


def _authorized(request: Request) -> bool:
    if config.DEMO_AUTH_DISABLED or not config.DEMO_ACCESS_TOKEN:
        return True
    token = request.headers.get("x-demo-token")
    if token == config.DEMO_ACCESS_TOKEN:
        return True
    authorization = request.headers.get("authorization", "")
    return authorization == f"Bearer {config.DEMO_ACCESS_TOKEN}"


def require_demo_access(request: Request) -> None:
    if not _authorized(request):
        raise HTTPException(status_code=401, detail="demo access token required")


def _load_controls() -> DemoControlState:
    return get_demo_controls(
        config.DB_URL,
        BACKEND_ID,
        initial_failure_rate=config.OPENAI_FAILURE_RATE,
    )


def _control_payload(controls: DemoControlState) -> dict:
    return {
        "backend": BACKEND_ID,
        "randomOpenAIFailures": controls.random_openai_failure_rate > 0,
        "randomOpenAIFailureRate": controls.random_openai_failure_rate,
        "openAIResponsesOutage": controls.openai_responses_outage,
        "langGraphAppEnabled": None,
        "workerEnabled": controls.worker_enabled,
        "capabilities": {"langGraphApp": False, "worker": True},
    }


@app.get("/")
async def root():
    return {
        "service": "support-agent gateway (python-temporal-langgraph)",
        "hint": "This is the API. Open the chat UI: cd web && python3 -m http.server 5173",
        "taskQueue": config.TASK_QUEUE,
        "endpoints": [
            "POST /conversations",
            "POST /conversations/{id}/messages",
            "GET  /conversations/{id}/transcript",
            "GET  /conversations/{id}/pending-approval",
            "POST /conversations/{id}/approve",
        ],
    }


@api.get("/health")
@api.get("/healthz")
async def healthz():
    return {"ok": True}


@api.get("/demo/controls")
async def demo_controls(_access: None = Depends(require_demo_access)):
    return _control_payload(await asyncio.to_thread(_load_controls))


@api.put("/demo/controls")
async def set_demo_controls(
    body: DemoControlUpdate,
    _access: None = Depends(require_demo_access),
):
    failure_rate = (
        None
        if body.randomOpenAIFailures is None
        else ENABLED_RANDOM_FAILURE_RATE
        if body.randomOpenAIFailures
        else 0
    )
    controls = await asyncio.to_thread(
        update_demo_controls,
        config.DB_URL,
        BACKEND_ID,
        random_openai_failure_rate=failure_rate,
        openai_responses_outage=body.openAIResponsesOutage,
        worker_enabled=body.workerEnabled,
        initial_failure_rate=config.OPENAI_FAILURE_RATE,
    )
    return _control_payload(controls)


@app.post("/internal/tools/execute", include_in_schema=False)
def internal_execute_tool(body: ToolRequest):
    """Private worker-to-backend tool execution endpoint.

    Kubernetes and Compose expose this only through the backend's internal
    service; the public ingress routes only the /api prefix.
    """
    return {"result": execute_tool_local(body)}


@api.post("/conversations", status_code=201)
async def create_conversation(
    body: CreateConversation, _access: None = Depends(require_demo_access)
):
    conversation_id = new_conversation_id(body.customerEmail)
    await _client().start_workflow(
        SupportAgentWorkflow.run,
        body.customerEmail,
        id=conversation_id,
        task_queue=config.TASK_QUEUE,
    )
    return {"conversationId": conversation_id}


@api.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: SendMessage,
    _access: None = Depends(require_demo_access),
):
    try:
        result = await _handle(conversation_id).execute_update(
            SupportAgentWorkflow.send_message, body.text
        )
    except WorkflowUpdateFailedError as e:
        detail = getattr(e.cause, "message", None) or str(e.cause)
        raise HTTPException(status_code=409, detail=detail) from e
    except RPCError as e:
        _not_found(e)
    return {"status": result.status, "reply": result.reply}


@api.get("/conversations/{conversation_id}/transcript")
async def transcript(
    conversation_id: str, _access: None = Depends(require_demo_access)
):
    try:
        messages = await _handle(conversation_id).query(SupportAgentWorkflow.transcript)
    except RPCError as e:
        _not_found(e)
    return {"messages": [{"role": m.role, "content": m.content} for m in messages]}


@api.get("/conversations/{conversation_id}/pending-approval")
async def pending_approval(
    conversation_id: str, _access: None = Depends(require_demo_access)
):
    try:
        pending = await _handle(conversation_id).query(
            SupportAgentWorkflow.pending_approval
        )
    except RPCError as e:
        _not_found(e)
    if pending is None:
        return {"pending": None}
    return {
        "pending": {
            "approvalId": pending.approval_id,
            "trackIds": pending.track_ids,
            "description": pending.description,
        }
    }


@api.post("/conversations/{conversation_id}/approve", status_code=202)
async def approve(
    conversation_id: str,
    body: Approve,
    _access: None = Depends(require_demo_access),
):
    handle = _handle(conversation_id)
    try:
        await handle.execute_update(
            SupportAgentWorkflow.approve_purchase,
            args=[
                body.approvalId,
                ApprovalDecision(approved=body.approved, reason=body.reason),
            ],
        )
    except WorkflowUpdateFailedError as e:
        detail = getattr(e.cause, "message", None) or str(e.cause)
        raise HTTPException(status_code=409, detail=detail) from e
    except RPCError as e:
        _not_found(e)
    return {}


# Keep the original endpoint surface for source-only local development while
# exposing the same API under /api for Compose and Kubernetes.
app.include_router(api)
app.include_router(api, prefix="/api")
