"""HTTP gateway for the Temporal + LangGraph support agent.

Each endpoint is one Temporal client call. The workflow ID is the conversation
ID, so the gateway can stay stateless.

    uv run uvicorn api:app --port 8002
"""

import re
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from temporalio.client import Client, WorkflowUpdateFailedError
from temporalio.service import RPCError, RPCStatusCode

import config
from models.types import ApprovalDecision
from workflows.agent import SupportAgentWorkflow


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.temporal = await config.temporal_client()
    yield


app = FastAPI(title="support-agent Temporal LangGraph gateway", lifespan=lifespan)
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
    approved: bool
    reason: str | None = None


def _client() -> Client:
    return app.state.temporal


def _handle(conversation_id: str):
    return _client().get_workflow_handle_for(SupportAgentWorkflow.run, conversation_id)


def _not_found(e: RPCError):
    if e.status == RPCStatusCode.NOT_FOUND:
        raise HTTPException(status_code=404, detail="unknown conversation") from e
    raise e


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


@app.post("/conversations", status_code=201)
async def create_conversation(body: CreateConversation):
    slug = re.sub(r"[^a-z0-9]+", "-", body.customerEmail.lower()).strip("-")
    conversation_id = f"support-{slug}-{secrets.token_hex(2)}"
    await _client().start_workflow(
        SupportAgentWorkflow.run,
        body.customerEmail,
        id=conversation_id,
        task_queue=config.TASK_QUEUE,
    )
    return {"conversationId": conversation_id}


@app.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, body: SendMessage):
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


@app.get("/conversations/{conversation_id}/transcript")
async def transcript(conversation_id: str):
    try:
        messages = await _handle(conversation_id).query(SupportAgentWorkflow.transcript)
    except RPCError as e:
        _not_found(e)
    return {"messages": [{"role": m.role, "content": m.content} for m in messages]}


@app.get("/conversations/{conversation_id}/pending-approval")
async def pending_approval(conversation_id: str):
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
            "trackIds": pending.track_ids,
            "description": pending.description,
        }
    }


@app.post("/conversations/{conversation_id}/approve", status_code=202)
async def approve(conversation_id: str, body: Approve):
    handle = _handle(conversation_id)
    try:
        pending = await handle.query(SupportAgentWorkflow.pending_approval)
        if pending is None:
            raise HTTPException(status_code=409, detail="nothing pending")
        await handle.signal(
            SupportAgentWorkflow.approve_purchase,
            ApprovalDecision(approved=body.approved, reason=body.reason),
        )
    except RPCError as e:
        _not_found(e)
    return {}
