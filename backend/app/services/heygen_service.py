"""
HeyGen Interactive Avatar service.

Manages the lifecycle of a HeyGen Streaming session:
  1. create_session  → POST /v1/streaming.new   (get SDP offer + ICE servers)
  2. start_session   → POST /v1/streaming.start  (exchange SDP answer)
  3. speak           → POST /v1/streaming.task   (make avatar speak text)
  4. stop_session    → POST /v1/streaming.stop   (end stream)

The frontend handles all WebRTC peer connection logic.
The backend only proxies HeyGen API calls to protect the API key.

Docs: https://docs.heygen.com/docs/streaming-api
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.heygen.com"
_TIMEOUT = 20

# Public avatar IDs available on HeyGen free/trial plans
# Users can override with their own avatar IDs via the API
DEFAULT_AVATAR_ID = "default"  # HeyGen uses "default" or specific IDs
AVATAR_OPTIONS = [
    {"id": "default", "name": "Default HeyGen Avatar"},
    {"id": "josh_lite3_20230714", "name": "Josh"},
    {"id": "anna_public_3_20240108", "name": "Anna"},
    {"id": "eric_public_pro2_20230608", "name": "Eric"},
]


class HeyGenService:
    """
    Async client for HeyGen Interactive Avatar streaming API.

    All methods return consistent {success, ...fields, error} dicts.
    Gracefully degrades when key is absent.
    """

    def __init__(self) -> None:
        self._api_key: str = settings.heygen_api_key or os.getenv("HEYGEN_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
        }

    # ── Session lifecycle ────────────────────────────────────────────────────

    async def create_session(
        self,
        *,
        avatar_id: str = DEFAULT_AVATAR_ID,
        quality: str = "high",
        voice_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new streaming session.

        Returns:
            {
                "success": bool,
                "session_id": str,
                "sdp_offer": str,        # WebRTC SDP offer (set as remote description)
                "ice_servers": list,     # ICE servers for RTCPeerConnection
                "error": str | None,
            }
        """
        if not self.available:
            return {
                "success": False,
                "session_id": None,
                "sdp_offer": None,
                "ice_servers": [],
                "error": "HeyGen API key not configured. Add HEYGEN_API_KEY to settings.",
            }

        payload: Dict[str, Any] = {
            "quality": quality,
            "avatar_id": avatar_id,
            "version": "v2",
            "video_encoding": "H264",
        }
        if voice_id:
            payload["voice"] = {"voice_id": voice_id}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_BASE_URL}/v1/streaming.new",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()

            session_data = data.get("data", data)
            session_id = session_data.get("session_id") or session_data.get("sessionId")
            sdp = session_data.get("sdp", {})
            sdp_offer = sdp.get("sdp") if isinstance(sdp, dict) else sdp

            # ICE servers come back as list of {urls, username, credential}
            ice_servers: List[Dict[str, Any]] = session_data.get("ice_servers2", [])
            if not ice_servers:
                ice_servers = session_data.get("ice_servers", [])

            if not session_id:
                raise ValueError(f"No session_id in HeyGen response: {data}")

            logger.info("HeyGen session created: %s", session_id)
            return {
                "success": True,
                "session_id": session_id,
                "sdp_offer": sdp_offer,
                "ice_servers": ice_servers,
                "error": None,
            }

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = {}
            try:
                body = exc.response.json()
            except Exception:
                pass
            error = body.get("message") or body.get("error") or f"HeyGen HTTP {status}"
            if status == 401:
                error = "Invalid HeyGen API key"
            logger.error("HeyGen create_session failed: %s", error)
            return {"success": False, "session_id": None, "sdp_offer": None, "ice_servers": [], "error": error}

        except Exception as exc:
            logger.warning("HeyGen create_session error: %s", exc)
            return {"success": False, "session_id": None, "sdp_offer": None, "ice_servers": [], "error": str(exc)}

    async def start_session(
        self,
        session_id: str,
        answer_sdp: str,
    ) -> Dict[str, Any]:
        """
        Start the streaming session by providing the browser's SDP answer.

        Returns: {"success": bool, "error": str | None}
        """
        if not self.available:
            return {"success": False, "error": "HeyGen API key not configured"}

        payload = {
            "session_id": session_id,
            "sdp": {
                "type": "answer",
                "sdp": answer_sdp,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_BASE_URL}/v1/streaming.start",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
            logger.info("HeyGen session started: %s", session_id)
            return {"success": True, "error": None}
        except Exception as exc:
            logger.warning("HeyGen start_session failed (%s): %s", session_id, exc)
            return {"success": False, "error": str(exc)}

    async def speak(
        self,
        session_id: str,
        text: str,
        *,
        task_type: str = "repeat",
    ) -> Dict[str, Any]:
        """
        Make the avatar speak text.

        task_type:
          - "repeat": Avatar speaks verbatim (fastest)
          - "talk": Avatar adds natural pauses/emphasis (slightly slower)

        Returns: {"success": bool, "task_id": str | None, "error": str | None}
        """
        if not self.available:
            return {"success": False, "task_id": None, "error": "HeyGen API key not configured"}

        # Truncate to reasonable TTS length
        speak_text = text.strip()[:800]
        if not speak_text:
            return {"success": False, "task_id": None, "error": "Empty text"}

        payload = {
            "session_id": session_id,
            "text": speak_text,
            "task_type": task_type,
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_BASE_URL}/v1/streaming.task",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()

            task_id = (data.get("data") or {}).get("task_id") or data.get("task_id")
            return {"success": True, "task_id": task_id, "error": None}

        except Exception as exc:
            logger.warning("HeyGen speak failed (%s): %s", session_id, exc)
            return {"success": False, "task_id": None, "error": str(exc)}

    async def stop_session(self, session_id: str) -> Dict[str, Any]:
        """
        Stop and clean up a streaming session.

        Returns: {"success": bool, "error": str | None}
        """
        if not self.available:
            return {"success": False, "error": "HeyGen API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{_BASE_URL}/v1/streaming.stop",
                    json={"session_id": session_id},
                    headers=self._headers(),
                )
                resp.raise_for_status()
            logger.info("HeyGen session stopped: %s", session_id)
            return {"success": True, "error": None}
        except Exception as exc:
            logger.warning("HeyGen stop_session failed (%s): %s", session_id, exc)
            # Non-fatal — session will expire on HeyGen's side anyway
            return {"success": True, "error": None}

    def list_avatars(self) -> List[Dict[str, str]]:
        return list(AVATAR_OPTIONS)


heygen_service = HeyGenService()
