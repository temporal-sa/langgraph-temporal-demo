"""HTTP gateway for the standalone LangGraph support agent.

Conversations are held in this process. Run one API process for the demo, or
replace ConversationStore with durable storage before scaling horizontally.

    uv run uvicorn api:app --port 8001
"""

import re
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from activities.llm import SimulatedOpenAIFailure
from graph.agent import ConversationStore, NoPendingApprovalError, PendingApprovalError
from models.types import ApprovalDecision


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
    approved: bool
    reason: str | None = None


def _store() -> ConversationStore:
    return app.state.conversations


def _session(conversation_id: str):
    try:
        return _store().get(conversation_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="unknown conversation") from e


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


@app.post("/conversations", status_code=201)
async def create_conversation(body: CreateConversation):
    slug = re.sub(r"[^a-z0-9]+", "-", body.customerEmail.lower()).strip("-")
    conversation_id = f"support-{slug}-{secrets.token_hex(2)}"
    _store().create(conversation_id, body.customerEmail)
    return {"conversationId": conversation_id}


@app.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, body: SendMessage):
    try:
        result = await _session(conversation_id).send_message(body.text)
    except PendingApprovalError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except SimulatedOpenAIFailure as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"status": result.status, "reply": result.reply}


@app.get("/conversations/{conversation_id}/transcript")
async def transcript(conversation_id: str):
    messages = _session(conversation_id).transcript()
    return {"messages": [{"role": m.role, "content": m.content} for m in messages]}


@app.get("/conversations/{conversation_id}/pending-approval")
async def pending_approval(conversation_id: str):
    pending = _session(conversation_id).pending_approval()
    if pending is None:
        return {"pending": None}
    return {"pending": {"trackIds": pending.track_ids, "description": pending.description}}


@app.post("/conversations/{conversation_id}/approve", status_code=202)
async def approve(conversation_id: str, body: Approve):
    try:
        result = await _session(conversation_id).approve_purchase(
            ApprovalDecision(approved=body.approved, reason=body.reason)
        )
    except NoPendingApprovalError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except SimulatedOpenAIFailure as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"status": result.status, "reply": result.reply}
