"""
AgentMail API endpoints — gives agents dedicated email inboxes.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.agentmail_service import agentmail_service

router = APIRouter(prefix="/email", tags=["email"])


# ── Request / Response models ─────────────────────────────────────────────────

class CreateInboxRequest(BaseModel):
    username: Optional[str] = None
    display_name: Optional[str] = None


class SendMessageRequest(BaseModel):
    inbox_id: str
    to: List[str]
    subject: str
    body: str
    html: Optional[str] = None
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    reply_to_id: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def email_status():
    return {
        "available": agentmail_service.available,
        "service": "AgentMail",
        "base_url": "https://api.agentmail.to/v0",
    }


@router.get("/inboxes")
async def list_inboxes():
    result = await agentmail_service.list_inboxes()
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "AgentMail error"))
    return result


@router.post("/inboxes")
async def create_inbox(req: CreateInboxRequest):
    result = await agentmail_service.create_inbox(
        username=req.username,
        display_name=req.display_name,
    )
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "AgentMail error"))
    return result


@router.get("/inboxes/{inbox_id}")
async def get_inbox(inbox_id: str):
    result = await agentmail_service.get_inbox(inbox_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Inbox not found"))
    return result


@router.delete("/inboxes/{inbox_id}")
async def delete_inbox(inbox_id: str):
    result = await agentmail_service.delete_inbox(inbox_id)
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "AgentMail error"))
    return result


@router.get("/inboxes/{inbox_id}/messages")
async def list_messages(inbox_id: str, limit: int = 20, page: int = 1):
    result = await agentmail_service.list_messages(inbox_id, limit=limit, page=page)
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "AgentMail error"))
    return result


@router.get("/inboxes/{inbox_id}/messages/{message_id}")
async def get_message(inbox_id: str, message_id: str):
    result = await agentmail_service.get_message(inbox_id, message_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Message not found"))
    return result


@router.post("/send")
async def send_message(req: SendMessageRequest):
    result = await agentmail_service.send_message(
        req.inbox_id,
        req.to,
        req.subject,
        req.body,
        html=req.html,
        cc=req.cc,
        bcc=req.bcc,
        reply_to_id=req.reply_to_id,
    )
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "Send failed"))
    return result


@router.delete("/inboxes/{inbox_id}/messages/{message_id}")
async def delete_message(inbox_id: str, message_id: str):
    result = await agentmail_service.delete_message(inbox_id, message_id)
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "AgentMail error"))
    return result
