'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Volume2, VolumeX, Loader2 } from 'lucide-react';
import { useStore } from '@/lib/store';
import { EventType } from '@/lib/types';
import { cn } from '@/lib/utils';

const BASE_URL =
  typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000')
    : 'http://localhost:8000';

interface VoicePlayerProps {
  taskId: string | null;
  enabled: boolean;
  voice?: string;
  muted?: boolean;
  onMuteChange?: (muted: boolean) => void;
}

export function VoicePlayer({
  taskId,
  enabled,
  voice = 'af_sky',
  muted: externalMuted,
  onMuteChange,
}: VoicePlayerProps) {
  const events = useStore((s) => (taskId ? s.events[taskId] ?? [] : []));
  const [isPlaying, setIsPlaying] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [internalMuted, setInternalMuted] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastPlayedEventRef = useRef<string | null>(null);

  const muted = externalMuted ?? internalMuted;

  const toggleMute = useCallback(() => {
    const next = !muted;
    setInternalMuted(next);
    onMuteChange?.(next);
    if (audioRef.current) {
      audioRef.current.muted = next;
    }
  }, [muted, onMuteChange]);

  const playText = useCallback(
    async (text: string, eventId: string) => {
      if (!enabled || muted || !text.trim()) return;
      if (lastPlayedEventRef.current === eventId) return; // Deduplicate
      lastPlayedEventRef.current = eventId;

      // Stop any current playback
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = '';
      }

      setIsLoading(true);
      try {
        const res = await fetch(`${BASE_URL}/voice/tts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: text.slice(0, 800), voice }),
        });

        if (!res.ok) return;
        const data = await res.json();
        if (!data.success || !data.audio_url) return;

        const audio = new Audio(data.audio_url);
        audio.muted = muted;
        audioRef.current = audio;

        audio.onplay = () => setIsPlaying(true);
        audio.onended = () => setIsPlaying(false);
        audio.onerror = () => setIsPlaying(false);

        setIsLoading(false);
        await audio.play();
      } catch {
        setIsLoading(false);
        setIsPlaying(false);
      }
    },
    [enabled, muted, voice]
  );

  // Watch for task_completed events
  useEffect(() => {
    if (!taskId || !enabled) return;

    const completedEvent = events
      .filter((e) => e.type === EventType.TASK_COMPLETED)
      .at(-1);

    if (!completedEvent) return;

    const text =
      (completedEvent.payload.result_preview as string) ||
      (completedEvent.payload.summary as string) ||
      'Task completed successfully.';

    playText(text, completedEvent.id);
  }, [events, taskId, enabled, playText]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = '';
      }
    };
  }, []);

  if (!enabled) return null;

  return (
    <button
      type="button"
      onClick={toggleMute}
      title={muted ? 'Unmute voice' : 'Mute voice'}
      className={cn(
        'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors',
        isPlaying && !muted
          ? 'text-accent bg-primary/15 border border-primary/30'
          : 'text-text-muted hover:text-text hover:bg-surface-elevated'
      )}
    >
      {isLoading ? (
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
      ) : isPlaying && !muted ? (
        <Volume2 className="w-3.5 h-3.5 animate-pulse" />
      ) : muted ? (
        <VolumeX className="w-3.5 h-3.5" />
      ) : (
        <Volume2 className="w-3.5 h-3.5" />
      )}
      <span className="hidden sm:block">{muted ? 'Muted' : isPlaying ? 'Speaking…' : 'Voice'}</span>
    </button>
  );
}
