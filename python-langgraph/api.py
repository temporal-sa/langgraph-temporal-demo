"""HTTP gateway for the standalone LangGraph support agent.

Conversations are held in this process. Run one API process for the demo, or
replace ConversationStore with durable storage before scaling horizontally.

    uv run uvicorn api:app --port 8001
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import config
from graph.agent import (
    ConversationStore,
    NoPendingApprovalError,
    PendingApprovalError,
    StaleApprovalError,
)
from models.types import ApprovalDecision
from support_agent_common.conversations import new_conversation_id
from support_agent_common.demo_controls import (
    DemoControlState,
    DemoOpenAIError,
    get_demo_controls,
    update_demo_controls,
)


BACKEND_ID = "langgraph"
ENABLED_RANDOM_FAILURE_RATE = 0.5


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.conversations = ConversationStore()
    yield


app = FastAPI(title="support-agent LangGraph gateway", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


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
    langGraphAppEnabled: bool | None = None


def _store() -> ConversationStore:
    return app.state.conversations


def _session(conversation_id: str):
    try:
        return _store().get(conversation_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="unknown conversation") from e


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
        "langGraphAppEnabled": controls.langgraph_app_enabled,
        "workerEnabled": None,
        "capabilities": {
            "langGraphApp": True,
            "worker": False,
            "endWorkflow": False,
        },
    }


async def _require_app_enabled() -> None:
    controls = await asyncio.to_thread(_load_controls)
    if not controls.langgraph_app_enabled:
        raise HTTPException(
            status_code=503,
            detail="LangGraph app is disabled in Demo controls",
        )


@app.get("/")
async def root():
    return {
        "service": "support-agent gateway (python-langgraph)",
        "hint": "This is the API. Open the chat UI: cd web && python3 -m http.server 5173",
        "endpoints": [
            "POST /conversations",
            "POST /conversations/{id}/messages",
            "GET  /conversations/{id}/transcript",
            "GET  /conversations/{id}/pending-approval",
            "POST /conversations/{id}/approve",
        ],
    }


@app.get("/demo/controls")
async def demo_controls():
    return _control_payload(await asyncio.to_thread(_load_controls))


@app.put("/demo/controls")
async def set_demo_controls(body: DemoControlUpdate):
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
        langgraph_app_enabled=body.langGraphAppEnabled,
        initial_failure_rate=config.OPENAI_FAILURE_RATE,
    )
    if body.langGraphAppEnabled is False and hasattr(app.state, "conversations"):
        app.state.conversations = ConversationStore()
    return _control_payload(controls)


@app.post("/conversations", status_code=201)
async def create_conversation(body: CreateConversation):
    await _require_app_enabled()
    conversation_id = new_conversation_id(body.customerEmail)
    _store().create(conversation_id, body.customerEmail)
    return {"conversationId": conversation_id}


@app.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, body: SendMessage):
    await _require_app_enabled()
    try:
        result = await _session(conversation_id).send_message(body.text)
    except PendingApprovalError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except DemoOpenAIError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"status": result.status, "reply": result.reply}


@app.get("/conversations/{conversation_id}/transcript")
async def transcript(conversation_id: str):
    await _require_app_enabled()
    messages = _session(conversation_id).transcript()
    return {"messages": [{"role": m.role, "content": m.content} for m in messages]}


@app.get("/conversations/{conversation_id}/pending-approval")
async def pending_approval(conversation_id: str):
    await _require_app_enabled()
    pending = _session(conversation_id).pending_approval()
    if pending is None:
        return {"pending": None}
    return {
        "pending": {
            "approvalId": pending.approval_id,
            "trackIds": pending.track_ids,
            "description": pending.description,
        }
    }


@app.post("/conversations/{conversation_id}/approve", status_code=202)
async def approve(conversation_id: str, body: Approve):
    await _require_app_enabled()
    try:
        result = await _session(conversation_id).approve_purchase(
            body.approvalId,
            ApprovalDecision(approved=body.approved, reason=body.reason),
        )
    except (NoPendingApprovalError, StaleApprovalError) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except DemoOpenAIError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"status": result.status, "reply": result.reply}
