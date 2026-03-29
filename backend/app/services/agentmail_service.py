"""
AgentMail service — gives agents dedicated email inboxes for signing up to
platforms and communicating with other agents / users.

API: https://api.agentmail.to/v0   Bearer auth
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.agentmail.to/v0"


class AgentMailService:
    def __init__(self) -> None:
        self._key = getattr(settings, "agentmail_api_key", "")

    @property
    def available(self) -> bool:
        return bool(self._key)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    # ── Inboxes ────────────────────────────────────────────────────────────────

    async def list_inboxes(self) -> Dict[str, Any]:
        """Return all inboxes for this account."""
        if not self.available:
            return {"success": False, "error": "AgentMail key not configured", "inboxes": []}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{_BASE_URL}/inboxes", headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        return {"success": True, "inboxes": data.get("inboxes", data)}

    async def create_inbox(self, username: Optional[str] = None, display_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new inbox.  If *username* is omitted AgentMail auto-assigns one.
        Returns { success, inbox_id, address, username, … }
        """
        if not self.available:
            return {"success": False, "error": "AgentMail key not configured"}
        body: Dict[str, Any] = {}
        if username:
            body["username"] = username
        if display_name:
            body["display_name"] = display_name
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(f"{_BASE_URL}/inboxes", headers=self._headers(), json=body)
            resp.raise_for_status()
            data = resp.json()
        inbox = data.get("inbox", data)
        return {
            "success": True,
            "inbox_id": inbox.get("id") or inbox.get("inbox_id"),
            "address": inbox.get("address") or inbox.get("email"),
            "username": inbox.get("username"),
            "raw": inbox,
        }

    async def get_inbox(self, inbox_id: str) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "AgentMail key not configured"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{_BASE_URL}/inboxes/{inbox_id}", headers=self._headers())
            resp.raise_for_status()
        return {"success": True, **resp.json()}

    async def delete_inbox(self, inbox_id: str) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "AgentMail key not configured"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.delete(f"{_BASE_URL}/inboxes/{inbox_id}", headers=self._headers())
            resp.raise_for_status()
        return {"success": True}

    # ── Messages ───────────────────────────────────────────────────────────────

    async def list_messages(self, inbox_id: str, limit: int = 20, page: int = 1) -> Dict[str, Any]:
        """List messages in an inbox (most-recent first)."""
        if not self.available:
            return {"success": False, "error": "AgentMail key not configured", "messages": []}
        params = {"limit": limit, "page": page}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{_BASE_URL}/inboxes/{inbox_id}/messages",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        return {"success": True, "messages": data.get("messages", data)}

    async def get_message(self, inbox_id: str, message_id: str) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "AgentMail key not configured"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{_BASE_URL}/inboxes/{inbox_id}/messages/{message_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
        return {"success": True, **resp.json()}

    async def send_message(
        self,
        inbox_id: str,
        to: List[str],
        subject: str,
        body: str,
        *,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        reply_to_id: Optional[str] = None,
        html: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an email from the given inbox.

        Args:
            inbox_id:    Source inbox.
            to:          List of recipient addresses.
            subject:     Email subject line.
            body:        Plain-text body.
            html:        Optional HTML body.
            reply_to_id: Message ID to thread as a reply.
        """
        if not self.available:
            return {"success": False, "error": "AgentMail key not configured"}
        payload: Dict[str, Any] = {
            "to": to,
            "subject": subject,
            "text": body,
        }
        if html:
            payload["html"] = html
        if cc:
            payload["cc"] = cc
        if bcc:
            payload["bcc"] = bcc
        if reply_to_id:
            payload["reply_to_id"] = reply_to_id
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_BASE_URL}/inboxes/{inbox_id}/messages",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return {"success": True, "message_id": data.get("id") or data.get("message_id"), "raw": data}

    async def delete_message(self, inbox_id: str, message_id: str) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "AgentMail key not configured"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.delete(
                f"{_BASE_URL}/inboxes/{inbox_id}/messages/{message_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
        return {"success": True}


# Singleton
agentmail_service = AgentMailService()
