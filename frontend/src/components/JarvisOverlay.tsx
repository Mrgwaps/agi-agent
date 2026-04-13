'use client';

import React, {
  useEffect,
  useRef,
  useCallback,
  useState,
} from 'react';
import { useStore } from '@/lib/store';
import { TaskStatus } from '@/lib/types';

// ─── Types ────────────────────────────────────────────────────────────────────

type JarvisState =
  | 'off'
  | 'waking'
  | 'briefing'
  | 'listening'
  | 'responding'
  | 'sleeping';

interface Particle {
  angle: number;
  radius: number;
  baseRadius: number;
  speed: number;
  baseSize: number;
  baseOpacity: number;
  z: number; // pseudo-depth 0.3–1.0
}

// ─── Constants ────────────────────────────────────────────────────────────────

const PARTICLE_COUNT = 1800;
const CYAN = '0, 212, 255';
const JARVIS_SYSTEM =
  'You are JARVIS, the AI assistant from Iron Man. You are witty, precise, ' +
  'and speak with a calm British confidence. Keep responses concise and intelligent — ' +
  'this is a voice interface, so avoid markdown, bullet points, or any formatting. ' +
  'Speak naturally, as if through a speaker.';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

function createParticles(): Particle[] {
  const particles: Particle[] = [];
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const baseRadius = Math.random() * 260 + 20;
    particles.push({
      angle: Math.random() * Math.PI * 2,
      radius: 0, // start collapsed for boot animation
      baseRadius,
      speed: (Math.random() * 0.004 + 0.001) * (Math.random() < 0.5 ? 1 : -1),
      baseSize: Math.random() * 1.8 + 0.4,
      baseOpacity: Math.random() * 0.5 + 0.25,
      z: Math.random() * 0.7 + 0.3,
    });
  }
  return particles;
}

function getTimeGreeting(): string {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 12) return 'Good morning, Sir.';
  if (hour >= 12 && hour < 17) return 'Good afternoon, Sir.';
  if (hour >= 17 && hour < 21) return 'Good evening, Sir.';
  return 'Working late, I see.';
}

async function fetchWeather(): Promise<string> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);
    const res = await fetch('https://wttr.in/?format=j1', {
      signal: controller.signal,
    });
    clearTimeout(timeout);
    if (!res.ok) return '';
    const data = await res.json();
    const area =
      data?.nearest_area?.[0]?.areaName?.[0]?.value ?? 'your location';
    const tempC = data?.current_condition?.[0]?.temp_C ?? '?';
    const desc =
      data?.current_condition?.[0]?.weatherDesc?.[0]?.value ?? 'unknown';
    const tempNum = parseInt(tempC, 10);

    let commentary = '';
    const descLower = desc.toLowerCase();
    if (descLower.includes('rain') || descLower.includes('drizzle')) {
      commentary = ' I recommend an umbrella.';
    } else if (tempNum >= 30) {
      commentary = " It's quite hot out there.";
    } else if (tempNum <= 5) {
      commentary = ' Bundle up — it is rather cold.';
    } else if (
      descLower.includes('clear') ||
      descLower.includes('sunny')
    ) {
      commentary = ' Clear skies ahead.';
    }

    return `Currently in ${area}: ${tempC}°C, ${desc}.${commentary}`;
  } catch {
    return '';
  }
}

// ─── Component ────────────────────────────────────────────────────────────────

export function JarvisOverlay({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const settings = useStore((s) => s.settings);
  const tasks = useStore((s) => s.tasks);

  // ── Refs that survive renders without causing them ──────────────────────────
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>([]);
  const stateRef = useRef<JarvisState>('off');
  const rafRef = useRef<number>(0);
  const bootProgressRef = useRef(0);
  const shutProgressRef = useRef(1);
  const breathPhaseRef = useRef(0);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);
  const recognitionRef = useRef<any>(null);
  const handleCommandRef = useRef<(text: string) => void>(() => {});

  // ── React state only for the small UI label ─────────────────────────────────
  const [displayState, setDisplayState] = useState<JarvisState>('off');

  function setJarvisState(s: JarvisState) {
    stateRef.current = s;
    setDisplayState(s);
  }

  // ── Audio helpers ────────────────────────────────────────────────────────────

  function ensureAudioContext() {
    if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
      audioCtxRef.current = new AudioContext();
    }
    if (audioCtxRef.current.state === 'suspended') {
      audioCtxRef.current.resume();
    }
    return audioCtxRef.current;
  }

  async function speak(text: string): Promise<void> {
    const apiKey = settings.elevenLabsApiKey || '37b2d7684ea1b8f85b21cf63b5895567';
    const voiceId = settings.jarvisVoiceId || 'onwK4e9ZLuTAKqWW03F9';

    try {
      const res = await fetch(
        `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`,
        {
          method: 'POST',
          headers: {
            'xi-api-key': apiKey,
            'Content-Type': 'application/json',
            Accept: 'audio/mpeg',
          },
          body: JSON.stringify({
            text,
            model_id: 'eleven_turbo_v2_5',
            voice_settings: {
              stability: 0.75,
              similarity_boost: 0.8,
              style: 0.0,
              use_speaker_boost: true,
            },
          }),
        }
      );
      if (!res.ok) {
        console.warn('[JARVIS] ElevenLabs error', res.status);
        return;
      }
      const arrayBuffer = await res.arrayBuffer();
      const ctx = ensureAudioContext();
      const audioBuffer = await ctx.decodeAudioData(arrayBuffer);

      // Set up analyser
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.75;
      analyserRef.current = analyser;

      // Stop any previous source
      if (sourceRef.current) {
        try { sourceRef.current.stop(); } catch {}
        sourceRef.current = null;
      }

      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(analyser);
      analyser.connect(ctx.destination);
      sourceRef.current = source;

      await new Promise<void>((resolve) => {
        source.onended = () => {
          analyserRef.current = null;
          sourceRef.current = null;
          resolve();
        };
        source.start();
      });
    } catch (err) {
      console.warn('[JARVIS] speak error', err);
    }
  }

  // ── Briefing ─────────────────────────────────────────────────────────────────

  async function runBriefing() {
    setJarvisState('briefing');

    const greeting = getTimeGreeting();
    const weatherPromise = fetchWeather();

    // Task summary
    const taskList = Object.values(tasks);
    const completed = taskList.filter(
      (t) => t.status === TaskStatus.COMPLETED
    ).length;
    const running = taskList.filter(
      (t) =>
        t.status === TaskStatus.RUNNING ||
        t.status === TaskStatus.PLANNING
    ).length;

    let taskSummary = '';
    if (taskList.length === 0) {
      taskSummary = 'No tasks are currently queued.';
    } else {
      const parts: string[] = [];
      if (running > 0) parts.push(`${running} task${running > 1 ? 's' : ''} in progress`);
      if (completed > 0) parts.push(`${completed} completed`);
      taskSummary = parts.length > 0 ? `You have ${parts.join(' and ')}.` : '';
    }

    const weather = await weatherPromise;

    const briefingParts = [greeting];
    if (weather) briefingParts.push(weather);
    if (taskSummary) briefingParts.push(taskSummary);
    briefingParts.push('All systems are operational.');

    const briefingText = briefingParts.join(' ');
    await speak(briefingText);

    if (stateRef.current === 'briefing') {
      startListening();
    }
  }

  // ── Voice recognition ────────────────────────────────────────────────────────

  const startListening = useCallback(() => {
    if (typeof window === 'undefined') return;
    const SpeechRecognition =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn('[JARVIS] SpeechRecognition not supported');
      return;
    }

    setJarvisState('listening');

    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch {}
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';
    recognitionRef.current = recognition;

    recognition.onresult = (event: any) => {
      const transcript: string =
        event.results[event.results.length - 1]?.[0]?.transcript?.trim() ?? '';
      if (transcript) {
        handleCommandRef.current(transcript);
      }
    };

    recognition.onerror = (e: any) => {
      if (e.error === 'no-speech' || e.error === 'aborted') return;
      console.warn('[JARVIS] recognition error', e.error);
    };

    recognition.onend = () => {
      const s = stateRef.current;
      if (s === 'listening' || s === 'responding') {
        // Auto-restart
        try { recognition.start(); } catch {}
      }
    };

    try { recognition.start(); } catch {}
  }, []);

  const stopRecognition = useCallback(() => {
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch {}
      recognitionRef.current = null;
    }
  }, []);

  // ── Command handler ────────────────────────────────────────────────────────

  const handleCommand = useCallback(
    async (text: string) => {
      const lower = text.toLowerCase();
      console.log('[JARVIS] heard:', text);

      // Shutdown commands
      if (
        lower.includes('goodnight jarvis') ||
        lower.includes('go to sleep') ||
        lower.includes('shut down') ||
        lower.includes('goodbye')
      ) {
        shutdown();
        return;
      }

      // Rebrief commands
      if (
        lower.includes('briefing') ||
        lower.includes('status report') ||
        lower.includes("what's the status") ||
        lower.includes('whats the status')
      ) {
        stopRecognition();
        await runBriefing();
        return;
      }

      // General command → LLM response
      setJarvisState('responding');
      stopRecognition();

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: text,
            history: [],
            system: JARVIS_SYSTEM,
          }),
        });
        if (!res.ok) throw new Error(`chat API ${res.status}`);
        const data = await res.json();
        const reply: string = data.response || "I'm afraid I didn't catch that, Sir.";
        await speak(reply);
      } catch (err) {
        console.warn('[JARVIS] chat error', err);
        await speak("I encountered an error processing that request, Sir.");
      }

      if (stateRef.current === 'responding') {
        startListening();
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [startListening, stopRecognition, tasks]
  );

  // Keep ref fresh so recognition onresult (closure) always calls the latest version
  useEffect(() => {
    handleCommandRef.current = handleCommand;
  }, [handleCommand]);

  // ── Shutdown ─────────────────────────────────────────────────────────────────

  const shutdown = useCallback(() => {
    setJarvisState('sleeping');
    shutProgressRef.current = 1;
    stopRecognition();
    if (sourceRef.current) {
      try { sourceRef.current.stop(); } catch {}
      sourceRef.current = null;
    }
    analyserRef.current = null;
  }, [stopRecognition]);

  // ── Canvas animation loop ─────────────────────────────────────────────────

  const animate = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    const cx = W / 2;
    const cy = H / 2;
    const state = stateRef.current;

    // ─ Audio data ───────────────────────────────────────────────────────────
    let bass = 0, mid = 0, high = 0;
    const analyser = analyserRef.current;
    if (analyser) {
      const data = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteFrequencyData(data);
      // bass: bins 0-2, mid: 3-18, high: 19-55
      const avgBins = (start: number, end: number) => {
        let sum = 0;
        for (let i = start; i <= end && i < data.length; i++) sum += data[i];
        return sum / ((end - start + 1) * 255);
      };
      bass = avgBins(0, 2);
      mid = avgBins(3, 18);
      high = avgBins(19, 55);
    }

    // ─ Clear ────────────────────────────────────────────────────────────────
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, W, H);

    // ─ Boot / shutdown progress ─────────────────────────────────────────────
    if (state === 'waking') {
      bootProgressRef.current = Math.min(1, bootProgressRef.current + 0.006);
      if (bootProgressRef.current >= 1) {
        // boot done → run briefing (call async outside animation)
        stateRef.current = 'briefing'; // prevents re-triggering
        setDisplayState('briefing');
        runBriefing();
      }
    }

    if (state === 'sleeping') {
      shutProgressRef.current = Math.max(0, shutProgressRef.current - 0.015);
      if (shutProgressRef.current <= 0) {
        cancelAnimationFrame(rafRef.current);
        onClose();
        return;
      }
    }

    // ─ Breath ───────────────────────────────────────────────────────────────
    breathPhaseRef.current += 0.012;

    // ─ Central glow ─────────────────────────────────────────────────────────
    const glowSize = 80 + bass * 120;
    const centralGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowSize);
    centralGrad.addColorStop(0, `rgba(${CYAN}, ${0.35 + bass * 0.4})`);
    centralGrad.addColorStop(0.5, `rgba(${CYAN}, ${0.08 + bass * 0.1})`);
    centralGrad.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = centralGrad;
    ctx.beginPath();
    ctx.ellipse(cx, cy, glowSize, glowSize * 0.52, 0, 0, Math.PI * 2);
    ctx.fill();

    // ─ Update & draw particles ───────────────────────────────────────────────
    const particles = particlesRef.current;

    // Collect inner particles for connection lines
    const innerParticles: { x: number; y: number }[] = [];

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];

      // ── Radius target based on state ──────────────────────────────────────
      let targetRadius = p.baseRadius;
      let speedMult = 1;
      let opacityMult = 1;
      let sizeMult = 1;

      if (state === 'waking') {
        const progress = easeOutCubic(bootProgressRef.current);
        targetRadius = p.baseRadius * progress;
        p.radius = targetRadius;
      } else if (state === 'sleeping') {
        targetRadius = p.baseRadius * shutProgressRef.current;
        p.radius = targetRadius;
      } else if (state === 'briefing' || state === 'responding') {
        sizeMult = 1 + bass * 1.9;
        targetRadius = p.baseRadius * (1 + mid * 0.65);
        speedMult = 1 + mid * 2.8;
        opacityMult = 0.6 + high * 0.8;
        p.radius += (targetRadius - p.radius) * 0.08;
      } else if (state === 'listening') {
        targetRadius = p.baseRadius * 0.68;
        speedMult = 0.55;
        opacityMult = 0.7;
        p.radius += (targetRadius - p.radius) * 0.05;
      } else {
        // idle breathing
        const breathAmp = 0.18;
        const breathed = p.baseRadius * (1 + Math.sin(breathPhaseRef.current + p.angle) * breathAmp);
        p.radius += (breathed - p.radius) * 0.04;
        opacityMult = 0.7 + Math.sin(breathPhaseRef.current * 0.5 + p.angle) * 0.3;
      }

      // ── Orbit ──────────────────────────────────────────────────────────────
      p.angle += p.speed * speedMult;

      // ── Position (elliptical — 52% y-axis tilt) ───────────────────────────
      const depth = p.z;
      const r = state === 'waking' || state === 'sleeping' ? targetRadius : p.radius;
      const px = cx + Math.cos(p.angle) * r * depth;
      const py = cy + Math.sin(p.angle) * r * 0.52 * depth;

      // ── Size & opacity ─────────────────────────────────────────────────────
      const size = p.baseSize * sizeMult * depth;
      const opacity = Math.min(1, p.baseOpacity * opacityMult * depth);

      // ── Collect inner particles for connection lines ───────────────────────
      if (p.baseRadius < 100) {
        innerParticles.push({ x: px, y: py });
      }

      // ── Draw outer glow halo (radial gradient, 3.5x size) ─────────────────
      const haloR = size * 3.5;
      const haloGrad = ctx.createRadialGradient(px, py, 0, px, py, haloR);
      haloGrad.addColorStop(0, `rgba(${CYAN}, ${opacity * 0.45})`);
      haloGrad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = haloGrad;
      ctx.beginPath();
      ctx.arc(px, py, haloR, 0, Math.PI * 2);
      ctx.fill();

      // ── Draw solid core ────────────────────────────────────────────────────
      ctx.fillStyle = `rgba(${CYAN}, ${opacity})`;
      ctx.beginPath();
      ctx.arc(px, py, size, 0, Math.PI * 2);
      ctx.fill();
    }

    // ─ Connection lines between close inner particles ────────────────────────
    ctx.strokeStyle = `rgba(${CYAN}, 0.07)`;
    ctx.lineWidth = 0.6;
    for (let i = 0; i < innerParticles.length; i++) {
      for (let j = i + 1; j < innerParticles.length; j++) {
        const dx = innerParticles[i].x - innerParticles[j].x;
        const dy = innerParticles[i].y - innerParticles[j].y;
        if (dx * dx + dy * dy < 50 * 50) {
          ctx.beginPath();
          ctx.moveTo(innerParticles[i].x, innerParticles[i].y);
          ctx.lineTo(innerParticles[j].x, innerParticles[j].y);
          ctx.stroke();
        }
      }
    }

    // ─ Vignette overlay ──────────────────────────────────────────────────────
    const vigGrad = ctx.createRadialGradient(cx, cy, W * 0.3, cx, cy, W * 0.8);
    vigGrad.addColorStop(0, 'rgba(0,0,0,0)');
    vigGrad.addColorStop(1, 'rgba(0,0,0,0.72)');
    ctx.fillStyle = vigGrad;
    ctx.fillRect(0, 0, W, H);

    rafRef.current = requestAnimationFrame(animate);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onClose]);

  // ── Resize handler ───────────────────────────────────────────────────────────

  function resizeCanvas() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }

  // ── Keyboard handler ──────────────────────────────────────────────────────────

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') shutdown();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, shutdown]);

  // ── Main lifecycle effect ─────────────────────────────────────────────────────

  useEffect(() => {
    if (!open) return;

    // Init particles & canvas
    particlesRef.current = createParticles();
    bootProgressRef.current = 0;
    shutProgressRef.current = 1;
    setJarvisState('waking');

    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    // Start animation loop
    rafRef.current = requestAnimationFrame(animate);

    return () => {
      // Cleanup
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener('resize', resizeCanvas);
      stopRecognition();
      if (sourceRef.current) {
        try { sourceRef.current.stop(); } catch {}
        sourceRef.current = null;
      }
      analyserRef.current = null;
      if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
        audioCtxRef.current.close();
        audioCtxRef.current = null;
      }
      stateRef.current = 'off';
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  const stateLabels: Record<JarvisState, string> = {
    off: '',
    waking: 'initializing',
    briefing: 'briefing',
    listening: 'listening',
    responding: 'processing',
    sleeping: 'shutting down',
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        background: '#000000',
        cursor: 'none',
      }}
    >
      <canvas
        ref={canvasRef}
        style={{ display: 'block', width: '100%', height: '100%' }}
      />

      {/* ESC button — faint top-right */}
      <button
        onClick={shutdown}
        style={{
          position: 'absolute',
          top: 16,
          right: 20,
          background: 'none',
          border: `1px solid rgba(${CYAN}, 0.18)`,
          borderRadius: 6,
          color: `rgba(${CYAN}, 0.28)`,
          fontSize: 10,
          padding: '3px 7px',
          cursor: 'pointer',
          letterSpacing: '0.08em',
          fontFamily: 'monospace',
          transition: 'opacity 0.2s',
        }}
        onMouseEnter={(e) =>
          ((e.currentTarget as HTMLElement).style.opacity = '1')
        }
        onMouseLeave={(e) =>
          ((e.currentTarget as HTMLElement).style.opacity = '0.5')
        }
      >
        ESC
      </button>

      {/* State label — subtle bottom center */}
      {displayState !== 'off' && (
        <div
          style={{
            position: 'absolute',
            bottom: 28,
            left: 0,
            right: 0,
            textAlign: 'center',
            fontSize: 10,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: `rgba(${CYAN}, 0.18)`,
            fontFamily: 'monospace',
            pointerEvents: 'none',
            userSelect: 'none',
          }}
        >
          {stateLabels[displayState]}
        </div>
      )}
    </div>
  );
}
