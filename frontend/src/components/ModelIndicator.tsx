'use client';

import React, { useMemo } from 'react';
import { Cpu, Zap, DollarSign } from 'lucide-react';
import { useStore } from '@/lib/store';
import { EventType } from '@/lib/types';
import { cn, formatCost } from '@/lib/utils';

interface ModelIndicatorProps {
  taskId?: string | null;
}

export function ModelIndicator({ taskId }: ModelIndicatorProps) {
  const events = useStore((s) => (taskId ? s.events[taskId] : undefined));

  const lastModelCall = useMemo(() => {
    if (!events) return null;
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].type === EventType.MODEL_CALL) return events[i];
    }
    return null;
  }, [events]);

  const payload = lastModelCall?.payload as {
    model?: string;
    costUsd?: number;
    isFree?: boolean;
    inputTokens?: number;
    outputTokens?: number;
  } | undefined;

  const model = payload?.model || lastModelCall?.model || null;
  const isFree = payload?.isFree ?? false;
  const cost = payload?.costUsd ?? lastModelCall?.costUsd ?? 0;

  if (!model) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface border border-border text-text-muted text-xs">
        <Cpu className="w-3.5 h-3.5" />
        <span>No model active</span>
      </div>
    );
  }

  const shortModel = model.split('/').pop() || model;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface border border-border text-xs">
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            'w-2 h-2 rounded-full flex-shrink-0',
            isFree
              ? 'bg-success animate-pulse'
              : 'bg-warning animate-pulse'
          )}
        />
        <Cpu className="w-3.5 h-3.5 text-text-muted" />
      </div>

      <span
        className="font-mono font-medium text-text max-w-[160px] truncate"
        title={model}
      >
        {shortModel}
      </span>

      {isFree ? (
        <span className="flex items-center gap-0.5 text-success font-medium">
          <Zap className="w-3 h-3" />
          FREE
        </span>
      ) : (
        <span className="flex items-center gap-0.5 text-warning font-medium">
          <DollarSign className="w-3 h-3" />
          {formatCost(cost)}
        </span>
      )}
    </div>
  );
}
