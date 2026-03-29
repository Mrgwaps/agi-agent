'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from '@/lib/store';

const BASE_URL =
  typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000')
    : 'http://localhost:8000';

const POLL_INTERVAL = 30 * 60 * 1000; // 30 minutes

interface HeartbeatInsight {
  text: string | null;
  timestamp: string | null;
  tasks_analyzed: number;
  model_used: string | null;
  next_run_in_seconds: number;
  available: boolean;
}

interface UseHeartbeatReturn {
  insight: HeartbeatInsight | null;
  isLoading: boolean;
  lastUpdated: Date | null;
  refresh: () => void;
}

export function useHeartbeat(): UseHeartbeatReturn {
  const addToast = useStore((s) => s.addToast);
  const [insight, setInsight] = useState<HeartbeatInsight | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const lastTimestampRef = useRef<string | null>(null);

  const fetchInsights = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${BASE_URL}/heartbeat/insights`);
      if (!res.ok) return;
      const data: HeartbeatInsight = await res.json();
      setInsight(data);

      // Show toast when new insight arrives
      if (
        data.available &&
        data.timestamp &&
        data.timestamp !== lastTimestampRef.current
      ) {
        lastTimestampRef.current = data.timestamp;
        setLastUpdated(new Date(data.timestamp));

        addToast({
          type: 'info',
          title: 'Revenue Intelligence Ready',
          message: 'New AI-generated revenue opportunities available.',
          duration: 8000,
        });
      }
    } catch {
      // Silently fail — heartbeat is supplementary
    } finally {
      setIsLoading(false);
    }
  }, [addToast]);

  const refresh = useCallback(() => {
    fetchInsights();
  }, [fetchInsights]);

  useEffect(() => {
    // Initial fetch (slight delay so app settles first)
    const initialTimer = setTimeout(fetchInsights, 5000);

    // Poll every 30 minutes
    const interval = setInterval(fetchInsights, POLL_INTERVAL);

    return () => {
      clearTimeout(initialTimer);
      clearInterval(interval);
    };
  }, [fetchInsights]);

  return { insight, isLoading, lastUpdated, refresh };
}
