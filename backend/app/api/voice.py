"""
Voice API — TTS, avatar session management.

Endpoints:
  GET  /voice/status                  Check which voice services are configured
  POST /voice/tts                     Kokoro TTS via fal.ai
  POST /voice/avatar/session          Create HeyGen streaming session
  POST /voice/avatar/start            Exchange SDP answer (start WebRTC)
  POST /voice/avatar/speak            Make avatar speak text
  DELETE /voice/avatar/session/{id}   Stop session
  GET  /voice/voices                  List available TTS voices
  GET  /voice/avatars                 List available avatar presets
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.fal_service import fal_service
from app.services.heygen_service import heygen_service

router = APIRouter(prefix="/voice", tags=["voice"])


# ── Request models ────────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1500)
    voice: str = Field(default="af_sky")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class AvatarSessionRequest(BaseModel):
    avatar_id: str = Field(default="default")
    quality: str = Field(default="high")
    voice_id: str | None = Field(default=None)


class AvatarStartRequest(BaseModel):
    session_id: str
    answer_sdp: str


class AvatarSpeakRequest(BaseModel):
    session_id: str
    text: str = Field(..., min_length=1, max_length=800)
    task_type: str = Field(default="repeat")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def voice_status():
    """Check which voice services are available."""
    return {
        "tts_available": fal_service.available,
        "avatar_available": heygen_service.available,
        "tts_default_voice": "af_sky",
        "services": {
            "fal_ai": "configured" if fal_service.available else "missing FAL_API_KEY",
            "heygen": "configured" if heygen_service.available else "missing HEYGEN_API_KEY",
        },
    }


@router.get("/voices")
async def list_voices():
    """List all available Kokoro TTS voice IDs."""
    return {"voices": fal_service.list_voices()}


@router.get("/avatars")
async def list_avatars():
    """List available HeyGen avatar presets."""
    return {"avatars": heygen_service.list_avatars()}


@router.post("/tts")
async def text_to_speech(body: TTSRequest):
    """
    Convert text to speech using Kokoro TTS via fal.ai.

    Returns audio_url that can be played directly in the browser.
    """
    result = await fal_service.kokoro_tts(
        body.text,
        voice=body.voice,
        speed=body.speed,
    )
    return result


@router.post("/avatar/session")
async def create_avatar_session(body: AvatarSessionRequest):
    """
    Create a HeyGen interactive avatar streaming session.

    Returns session_id, sdp_offer (WebRTC offer from HeyGen), and ice_servers.
    The browser should:
      1. Create RTCPeerConnection with the returned ice_servers
      2. Set the sdp_offer as the remote description
      3. Create an answer and call POST /voice/avatar/start
    """
    result = await heygen_service.create_session(
        avatar_id=body.avatar_id,
        quality=body.quality,
        voice_id=body.voice_id,
    )
    return result


@router.post("/avatar/start")
async def start_avatar_session(body: AvatarStartRequest):
    """
    Start the WebRTC session by providing the browser's SDP answer.

    Call this after creating the RTCPeerConnection answer in the browser.
    After this succeeds, the video stream will begin flowing.
    """
    result = await heygen_service.start_session(
        session_id=body.session_id,
        answer_sdp=body.answer_sdp,
    )
    return result


@router.post("/avatar/speak")
async def avatar_speak(body: AvatarSpeakRequest):
    """
    Send text for the avatar to speak.

    The avatar will lip-sync and speak the text through the active WebRTC stream.
    task_type="repeat" is fastest. task_type="talk" adds natural pacing.
    """
    result = await heygen_service.speak(
        session_id=body.session_id,
        text=body.text,
        task_type=body.task_type,
    )
    return result


@router.delete("/avatar/session/{session_id}")
async def stop_avatar_session(session_id: str):
    """
    Stop and clean up a HeyGen streaming session.

    Always call this when the user dismisses the avatar or navigates away.
    """
    result = await heygen_service.stop_session(session_id)
    return result
