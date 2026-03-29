'use client';

import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Video, VideoOff, X, Loader2, WifiOff, Maximize2, Minimize2 } from 'lucide-react';
import { cn } from '@/lib/utils';

const BASE_URL =
  typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000')
    : 'http://localhost:8000';

interface VoiceAvatarProps {
  enabled: boolean;
}

type AvatarState = 'idle' | 'connecting' | 'connected' | 'speaking' | 'error';

export function VoiceAvatar({ enabled }: VoiceAvatarProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [state, setState] = useState<AvatarState>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);

  // Checks if browser supports WebRTC
  const isWebRTCSupported =
    typeof window !== 'undefined' && !!window.RTCPeerConnection;

  const connect = useCallback(async () => {
    if (!isWebRTCSupported) {
      setErrorMsg('WebRTC is not supported in this browser.');
      setState('error');
      return;
    }

    setState('connecting');
    setErrorMsg(null);

    try {
      // 1. Create HeyGen session via backend
      const sessionRes = await fetch(`${BASE_URL}/voice/avatar/session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ avatar_id: 'default', quality: 'high' }),
      });
      const sessionData = await sessionRes.json();

      if (!sessionData.success) {
        throw new Error(sessionData.error || 'Failed to create avatar session');
      }

      const { session_id, sdp_offer, ice_servers } = sessionData;
      setSessionId(session_id);

      // 2. Create RTCPeerConnection
      const pc = new RTCPeerConnection({
        iceServers: ice_servers?.length
          ? ice_servers
          : [{ urls: 'stun:stun.l.google.com:19302' }],
      });
      pcRef.current = pc;

      // 3. Set up track handler — attach stream to video element
      pc.ontrack = (event) => {
        if (videoRef.current && event.streams[0]) {
          videoRef.current.srcObject = event.streams[0];
        }
      };

      // 4. Set remote description (HeyGen's offer)
      await pc.setRemoteDescription({
        type: 'offer',
        sdp: sdp_offer,
      } as RTCSessionDescriptionInit);

      // 5. Create browser answer
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);

      // 6. Send answer back to HeyGen via backend
      const startRes = await fetch(`${BASE_URL}/voice/avatar/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id,
          answer_sdp: answer.sdp,
        }),
      });
      const startData = await startRes.json();

      if (!startData.success) {
        throw new Error(startData.error || 'Failed to start avatar stream');
      }

      // 7. Handle connection state changes
      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'connected') {
          setState('connected');
        } else if (
          pc.connectionState === 'disconnected' ||
          pc.connectionState === 'failed'
        ) {
          setState('error');
          setErrorMsg('Avatar connection lost. Click to reconnect.');
        }
      };

      // Some connections resolve quickly
      if (pc.connectionState === 'connected') {
        setState('connected');
      } else {
        // Wait for connected state (or timeout)
        setTimeout(() => {
          if (pcRef.current?.connectionState !== 'connected') {
            setState('connected'); // Optimistically assume connected
          }
        }, 3000);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Avatar connection failed';
      setErrorMsg(msg);
      setState('error');
    }
  }, [isWebRTCSupported]);

  const disconnect = useCallback(async () => {
    if (sessionId) {
      fetch(`${BASE_URL}/voice/avatar/session/${sessionId}`, {
        method: 'DELETE',
      }).catch(() => {}); // Fire and forget
    }

    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    setSessionId(null);
    setState('idle');
    setErrorMsg(null);
  }, [sessionId]);

  // Public: speak text through avatar
  const speakText = useCallback(
    async (text: string) => {
      if (!sessionId || state !== 'connected') return;
      setState('speaking');
      try {
        await fetch(`${BASE_URL}/voice/avatar/speak`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, text }),
        });
      } catch {
        // Non-fatal
      }
      setTimeout(() => setState('connected'), 5000); // Reset after ~5s
    },
    [sessionId, state]
  );

  // Expose speakText on window for cross-component use (simple pattern)
  useEffect(() => {
    if (typeof window !== 'undefined') {
      (window as Window & { __avatarSpeak?: (t: string) => void }).__avatarSpeak = speakText;
    }
    return () => {
      if (typeof window !== 'undefined') {
        delete (window as Window & { __avatarSpeak?: (t: string) => void }).__avatarSpeak;
      }
    };
  }, [speakText]);

  const handleToggle = useCallback(() => {
    if (isOpen) {
      disconnect();
      setIsOpen(false);
    } else {
      setIsOpen(true);
      connect();
    }
  }, [isOpen, connect, disconnect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!enabled) return null;

  const avatarSize = expanded ? { width: 480, height: 360 } : { width: 320, height: 240 };

  return (
    <>
      {/* Toggle button in header */}
      <button
        type="button"
        onClick={handleToggle}
        disabled={!isWebRTCSupported}
        title={
          !isWebRTCSupported
            ? 'WebRTC not supported in this browser'
            : isOpen
            ? 'Close avatar'
            : 'Open AI avatar'
        }
        className={cn(
          'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors',
          isOpen && state === 'connected'
            ? 'text-accent bg-primary/15 border border-primary/30'
            : isOpen && state === 'connecting'
            ? 'text-warning bg-warning/10 border border-warning/30'
            : state === 'error'
            ? 'text-error bg-error/10 border border-error/30'
            : 'text-text-muted hover:text-text hover:bg-surface-elevated',
          !isWebRTCSupported && 'opacity-50 cursor-not-allowed'
        )}
      >
        {state === 'connecting' ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : !isWebRTCSupported || state === 'error' ? (
          <WifiOff className="w-3.5 h-3.5" />
        ) : isOpen ? (
          <Video className="w-3.5 h-3.5" />
        ) : (
          <VideoOff className="w-3.5 h-3.5" />
        )}
        <span className="hidden sm:block">
          {state === 'connecting'
            ? 'Connecting…'
            : state === 'speaking'
            ? 'Speaking…'
            : isOpen && state === 'connected'
            ? 'Avatar'
            : 'Avatar'}
        </span>
      </button>

      {/* Floating avatar panel */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
            style={{ width: avatarSize.width }}
            className="fixed bottom-4 right-4 z-50 bg-card border border-border rounded-2xl shadow-2xl overflow-hidden"
          >
            {/* Avatar header */}
            <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-surface">
              <div className="flex items-center gap-2">
                <div
                  className={cn(
                    'w-2 h-2 rounded-full',
                    state === 'connected' ? 'bg-success animate-pulse' :
                    state === 'speaking' ? 'bg-primary animate-pulse' :
                    state === 'connecting' ? 'bg-warning animate-pulse' :
                    state === 'error' ? 'bg-error' :
                    'bg-border'
                  )}
                />
                <span className="text-xs font-medium text-text">
                  {state === 'connected' ? 'Avatar Ready' :
                   state === 'speaking' ? 'Speaking…' :
                   state === 'connecting' ? 'Connecting…' :
                   state === 'error' ? 'Connection Error' :
                   'Avatar'}
                </span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setExpanded(!expanded)}
                  className="p-1 rounded text-text-muted hover:text-text transition-colors"
                >
                  {expanded ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
                </button>
                <button
                  type="button"
                  onClick={handleToggle}
                  className="p-1 rounded text-text-muted hover:text-error transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Video area */}
            <div
              className="relative bg-black flex items-center justify-center"
              style={{ height: avatarSize.height }}
            >
              <video
                ref={videoRef}
                autoPlay
                playsInline
                className="w-full h-full object-cover"
              />

              {/* Overlay states */}
              {state === 'connecting' && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/70">
                  <Loader2 className="w-8 h-8 text-primary animate-spin mb-3" />
                  <p className="text-sm text-white">Connecting to avatar…</p>
                  <p className="text-xs text-white/60 mt-1">Establishing WebRTC stream</p>
                </div>
              )}

              {state === 'error' && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/70 p-4">
                  <WifiOff className="w-8 h-8 text-error mb-3" />
                  <p className="text-sm text-white text-center">{errorMsg}</p>
                  <button
                    type="button"
                    onClick={() => { disconnect(); connect(); }}
                    className="mt-3 px-4 py-1.5 rounded-lg bg-primary text-white text-xs font-medium hover:bg-primary/90 transition-colors"
                  >
                    Reconnect
                  </button>
                </div>
              )}

              {/* Speaking indicator overlay */}
              {state === 'speaking' && (
                <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex gap-1 items-end h-4">
                  {[0, 1, 2, 3].map((i) => (
                    <div
                      key={i}
                      className="w-1 bg-primary rounded-full animate-bounce"
                      style={{
                        height: `${8 + i * 4}px`,
                        animationDelay: `${i * 0.1}s`,
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
