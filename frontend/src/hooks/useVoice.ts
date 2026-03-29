'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

interface UseVoiceOptions {
  onTranscriptChange?: (text: string) => void;
  onAutoSubmit?: () => void;
  autoSubmitOnSilence?: boolean;
  silenceTimeoutMs?: number;
  lang?: string;
}

interface UseVoiceReturn {
  isSupported: boolean;
  isListening: boolean;
  interimTranscript: string;
  error: string | null;
  startListening: () => void;
  stopListening: () => void;
}

// Augment window type for cross-browser Speech API
declare global {
  interface Window {
    SpeechRecognition?: typeof SpeechRecognition;
    webkitSpeechRecognition?: typeof SpeechRecognition;
  }
}

export function useVoice({
  onTranscriptChange,
  onAutoSubmit,
  autoSubmitOnSilence = false,
  silenceTimeoutMs = 2000,
  lang = 'en-US',
}: UseVoiceOptions = {}): UseVoiceReturn {
  const [isListening, setIsListening] = useState(false);
  const [interimTranscript, setInterimTranscript] = useState('');
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const finalTranscriptRef = useRef('');

  const isSupported =
    typeof window !== 'undefined' &&
    !!(window.SpeechRecognition || window.webkitSpeechRecognition);

  // Create recognition instance once
  const getRecognition = useCallback((): SpeechRecognition | null => {
    if (typeof window === 'undefined') return null;
    const SpeechAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechAPI) return null;

    if (!recognitionRef.current) {
      const recognition = new SpeechAPI();
      recognition.lang = lang;
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      recognitionRef.current = recognition;
    }
    return recognitionRef.current;
  }, [lang]);

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const startSilenceTimer = useCallback(() => {
    clearSilenceTimer();
    if (!autoSubmitOnSilence) return;
    silenceTimerRef.current = setTimeout(() => {
      // Stop listening; auto-submit will fire in onend handler
      recognitionRef.current?.stop();
    }, silenceTimeoutMs);
  }, [autoSubmitOnSilence, silenceTimeoutMs, clearSilenceTimer]);

  const startListening = useCallback(() => {
    if (!isSupported) {
      setError('Speech recognition is not supported in this browser. Use Chrome or Edge.');
      return;
    }

    const recognition = getRecognition();
    if (!recognition) return;

    setError(null);
    finalTranscriptRef.current = '';
    setInterimTranscript('');

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = '';
      let finalText = finalTranscriptRef.current;

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const transcript = result[0].transcript;
        if (result.isFinal) {
          finalText += transcript + ' ';
        } else {
          interim = transcript;
        }
      }

      finalTranscriptRef.current = finalText;
      setInterimTranscript(interim);

      // Update parent with the combined text
      const combined = (finalText + interim).trim();
      if (combined) {
        onTranscriptChange?.(combined);
      }

      // Reset silence timer on each new speech result
      if (autoSubmitOnSilence) {
        startSilenceTimer();
      }
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      const errorMessages: Record<string, string> = {
        'not-allowed': 'Microphone permission denied. Please allow microphone access.',
        'no-speech': 'No speech detected. Try speaking closer to the microphone.',
        'network': 'Network error during speech recognition.',
        'aborted': '', // User stopped — not an error
        'audio-capture': 'No microphone found. Please connect a microphone.',
      };
      const msg = errorMessages[event.error] ?? `Speech error: ${event.error}`;
      if (msg) setError(msg);
      setIsListening(false);
      setInterimTranscript('');
      clearSilenceTimer();
    };

    recognition.onend = () => {
      setIsListening(false);
      setInterimTranscript('');
      clearSilenceTimer();

      // Auto-submit if enabled and we have transcript
      if (autoSubmitOnSilence && finalTranscriptRef.current.trim()) {
        onAutoSubmit?.();
      }
    };

    recognition.onstart = () => {
      setIsListening(true);
      if (autoSubmitOnSilence) startSilenceTimer();
    };

    try {
      recognition.start();
    } catch (err) {
      // Already started — stop and restart
      recognition.stop();
      setTimeout(() => recognition.start(), 200);
    }
  }, [isSupported, getRecognition, onTranscriptChange, onAutoSubmit, autoSubmitOnSilence, startSilenceTimer, clearSilenceTimer]);

  const stopListening = useCallback(() => {
    clearSilenceTimer();
    recognitionRef.current?.stop();
    setIsListening(false);
    setInterimTranscript('');
  }, [clearSilenceTimer]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      clearSilenceTimer();
      if (recognitionRef.current) {
        recognitionRef.current.onresult = null;
        recognitionRef.current.onerror = null;
        recognitionRef.current.onend = null;
        recognitionRef.current.onstart = null;
        try {
          recognitionRef.current.stop();
        } catch {
          // ignore
        }
        recognitionRef.current = null;
      }
    };
  }, [clearSilenceTimer]);

  return {
    isSupported,
    isListening,
    interimTranscript,
    error,
    startListening,
    stopListening,
  };
}
