from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.openrouter import ModelQuality, openrouter_client

router = APIRouter(prefix="/chat", tags=["chat"])

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, knowledgeable AI assistant. "
    "Answer questions clearly and concisely. "
    "Use markdown formatting for code, lists, and structure when helpful."
)


class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = []
    system: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    model: str


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest) -> Dict[str, Any]:
    """Direct chat with the AI — no task orchestration."""
    system_prompt = body.system if body.system else DEFAULT_SYSTEM_PROMPT
    messages = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]
    # Add conversation history
    for msg in body.history[-10:]:  # last 10 turns
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    # Add current message
    messages.append({"role": "user", "content": body.message})

    text, model, _ = await openrouter_client.chat_completion(
        messages=messages,
        task_type="general",
        quality=ModelQuality.FREE,
        max_tokens=2048,
        temperature=0.7,
    )
    return {"response": text, "model": model}
