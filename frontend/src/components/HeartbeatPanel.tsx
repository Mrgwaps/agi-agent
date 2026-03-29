'use client';

import React from 'react';
import { BrainCircuit, RefreshCw, Clock, Loader2, TrendingUp } from 'lucide-react';
import { useHeartbeat } from '@/hooks/useHeartbeat';
import { cn } from '@/lib/utils';

export function HeartbeatPanel() {
  const { insight, isLoading, lastUpdated, refresh } = useHeartbeat();

  function formatTime(d: Date | null): string {
    if (!d) return 'Never';
    const diff = Math.floor((Date.now() - d.getTime()) / 1000);
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function formatNextRun(sec: number): string {
    if (sec <= 0) return 'Running…';
    const m = Math.floor(sec / 60);
    if (m < 1) return 'soon';
    return `${m}m`;
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 pt-3 pb-2 border-b border-border flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-3.5 h-3.5 text-primary" />
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wider">
              Revenue Intel
            </p>
          </div>
          <button
            type="button"
            onClick={refresh}
            disabled={isLoading}
            title="Refresh insights"
            className="p-1 rounded text-text-muted hover:text-text transition-colors disabled:opacity-40"
          >
            <RefreshCw className={cn('w-3 h-3', isLoading && 'animate-spin')} />
          </button>
        </div>

        {/* Last updated + next run */}
        <div className="flex items-center gap-2 mt-1.5">
          <Clock className="w-3 h-3 text-text-muted/60" />
          <span className="text-xs text-text-muted/70">
            {lastUpdated ? `Updated ${formatTime(lastUpdated)}` : 'Pending first run'}
          </span>
          {insight && (
            <span className="text-xs text-text-muted/50 ml-auto">
              Next: {formatNextRun(insight.next_run_in_seconds)}
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-3">
        {isLoading && !insight?.text ? (
          <div className="flex flex-col items-center gap-3 py-8">
            <Loader2 className="w-6 h-6 text-primary animate-spin" />
            <p className="text-xs text-text-muted text-center">
              Analyzing task history…
            </p>
          </div>
        ) : !insight?.text ? (
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <div className="w-10 h-10 rounded-xl bg-surface border border-border flex items-center justify-center">
              <BrainCircuit className="w-5 h-5 text-text-muted/40" />
            </div>
            <div>
              <p className="text-xs font-medium text-text-muted">No insights yet</p>
              <p className="text-xs text-text-muted/60 mt-1">
                The first brief will be ready in about 60 seconds after the server starts.
              </p>
            </div>
            <button
              type="button"
              onClick={refresh}
              className="px-3 py-1.5 rounded-lg bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 transition-colors"
            >
              Check now
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {/* Model badge */}
            {insight.model_used && (
              <div className="flex items-center gap-1.5">
                <span className="text-xs px-2 py-0.5 rounded bg-success/10 border border-success/20 text-success font-mono truncate max-w-full">
                  {insight.model_used.split('/').pop()}
                </span>
                {insight.tasks_analyzed > 0 && (
                  <span className="text-xs text-text-muted/60 flex-shrink-0">
                    {insight.tasks_analyzed} tasks
                  </span>
                )}
              </div>
            )}

            {/* Brief text */}
            <div className="text-xs text-text leading-relaxed whitespace-pre-wrap">
              {insight.text}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
