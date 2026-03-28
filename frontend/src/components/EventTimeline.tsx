'use client';

import React, { useState, useRef, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BrainCircuit,
  Wrench,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  MessageSquare,
  Sparkles,
  ShieldAlert,
  Download,
  Loader2,
  ChevronDown,
  ChevronRight,
  Filter,
} from 'lucide-react';
import { type AgentEvent, EventType } from '@/lib/types';
import { cn, formatTimestamp, formatCost, safeJsonStringify } from '@/lib/utils';

// ============================================================
// Event type config
// ============================================================

type FilterTab = 'all' | 'tools' | 'models' | 'errors' | 'approvals';

const EVENT_CONFIG: Record<string, {
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bg: string;
  label: string;
  filter: FilterTab;
}> = {
  [EventType.TASK_CREATED]: { icon: Sparkles, color: 'text-accent', bg: 'bg-accent/10', label: 'Task Created', filter: 'all' },
  [EventType.TASK_STARTED]: { icon: Sparkles, color: 'text-primary', bg: 'bg-primary/10', label: 'Task Started', filter: 'all' },
  [EventType.TASK_COMPLETED]: { icon: CheckCircle2, color: 'text-success', bg: 'bg-success/10', label: 'Completed', filter: 'all' },
  [EventType.TASK_FAILED]: { icon: XCircle, color: 'text-error', bg: 'bg-error/10', label: 'Failed', filter: 'errors' },
  [EventType.TASK_ABORTED]: { icon: XCircle, color: 'text-text-muted', bg: 'bg-surface', label: 'Aborted', filter: 'all' },
  [EventType.PLAN_CREATED]: { icon: BrainCircuit, color: 'text-accent', bg: 'bg-accent/10', label: 'Plan Created', filter: 'all' },
  [EventType.STEP_STARTED]: { icon: ChevronRight, color: 'text-primary', bg: 'bg-primary/10', label: 'Step Started', filter: 'all' },
  [EventType.STEP_COMPLETED]: { icon: CheckCircle2, color: 'text-success', bg: 'bg-success/10', label: 'Step Done', filter: 'all' },
  [EventType.STEP_FAILED]: { icon: XCircle, color: 'text-error', bg: 'bg-error/10', label: 'Step Failed', filter: 'errors' },
  [EventType.TOOL_CALL_STARTED]: { icon: Wrench, color: 'text-warning', bg: 'bg-warning/10', label: 'Tool Call', filter: 'tools' },
  [EventType.TOOL_CALL_COMPLETED]: { icon: Wrench, color: 'text-success', bg: 'bg-success/10', label: 'Tool Done', filter: 'tools' },
  [EventType.TOOL_CALL_FAILED]: { icon: Wrench, color: 'text-error', bg: 'bg-error/10', label: 'Tool Error', filter: 'errors' },
  [EventType.MODEL_CALL]: { icon: BrainCircuit, color: 'text-accent', bg: 'bg-accent/10', label: 'Model Call', filter: 'models' },
  [EventType.APPROVAL_REQUIRED]: { icon: ShieldAlert, color: 'text-warning', bg: 'bg-warning/10', label: 'Approval Needed', filter: 'approvals' },
  [EventType.APPROVAL_GRANTED]: { icon: CheckCircle2, color: 'text-success', bg: 'bg-success/10', label: 'Approved', filter: 'approvals' },
  [EventType.APPROVAL_DENIED]: { icon: XCircle, color: 'text-error', bg: 'bg-error/10', label: 'Denied', filter: 'approvals' },
  [EventType.ARTIFACT_CREATED]: { icon: Download, color: 'text-accent', bg: 'bg-accent/10', label: 'Artifact', filter: 'all' },
  [EventType.LOG]: { icon: MessageSquare, color: 'text-text-muted', bg: 'bg-surface', label: 'Log', filter: 'all' },
  [EventType.ERROR]: { icon: AlertTriangle, color: 'text-error', bg: 'bg-error/10', label: 'Error', filter: 'errors' },
  [EventType.COST_UPDATE]: { icon: Sparkles, color: 'text-text-muted', bg: 'bg-surface', label: 'Cost Update', filter: 'all' },
};

function getEventSummary(event: AgentEvent): string {
  const p = event.payload;
  switch (event.type) {
    case EventType.PLAN_CREATED:
      return `Created plan with ${(p.plan as unknown[])?.length ?? '?'} steps`;
    case EventType.STEP_STARTED:
      return `Step ${(p.stepIndex as number ?? 0) + 1}: ${p.title as string || ''}`;
    case EventType.STEP_COMPLETED:
      return `Step ${(p.stepIndex as number ?? 0) + 1} completed`;
    case EventType.STEP_FAILED:
      return `Step ${(p.stepIndex as number ?? 0) + 1} failed: ${p.error as string || ''}`;
    case EventType.TOOL_CALL_STARTED:
      return `${p.toolName as string || 'tool'} called`;
    case EventType.TOOL_CALL_COMPLETED:
      return `${p.toolName as string || 'tool'} completed`;
    case EventType.TOOL_CALL_FAILED:
      return `${p.toolName as string || 'tool'} error: ${p.error as string || ''}`;
    case EventType.MODEL_CALL:
      return `${(p.model as string || 'model').split('/').pop()} — ${p.inputTokens as number || 0}+${p.outputTokens as number || 0} tokens`;
    case EventType.APPROVAL_REQUIRED:
      return p.action as string || 'Action requires approval';
    case EventType.LOG:
      return p.message as string || '';
    case EventType.ERROR:
      return p.message as string || p.error as string || 'Error occurred';
    default:
      return '';
  }
}

// ============================================================
// Individual event card
// ============================================================

function EventCard({ event }: { event: AgentEvent }) {
  const [expanded, setExpanded] = useState(false);
  const cfg = EVENT_CONFIG[event.type] || {
    icon: MessageSquare,
    color: 'text-text-muted',
    bg: 'bg-surface',
    label: event.type,
    filter: 'all' as FilterTab,
  };
  const Icon = cfg.icon;
  const summary = getEventSummary(event);
  const payload = event.payload;
  const hasPayload = Object.keys(payload).length > 0;

  const modelPayload = event.type === EventType.MODEL_CALL
    ? payload as { model?: string; isFree?: boolean; costUsd?: number; inputTokens?: number; outputTokens?: number }
    : null;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      className="animate-slide-in"
    >
      <div
        className={cn(
          'group flex flex-col border border-border rounded-xl overflow-hidden',
          'transition-colors hover:border-border/80',
          event.type === EventType.ERROR || event.type === EventType.TASK_FAILED
            ? 'border-error/20'
            : event.type === EventType.APPROVAL_REQUIRED
            ? 'border-warning/30'
            : ''
        )}
      >
        {/* Main row */}
        <div
          className={cn(
            'flex items-start gap-3 p-3',
            hasPayload ? 'cursor-pointer' : ''
          )}
          onClick={() => hasPayload && setExpanded(!expanded)}
        >
          {/* Icon */}
          <div className={cn('w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5', cfg.bg)}>
            <Icon className={cn('w-3.5 h-3.5', cfg.color)} />
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={cn('text-xs font-semibold', cfg.color)}>{cfg.label}</span>

              {/* Model badge */}
              {modelPayload?.model && (
                <span className={cn(
                  'text-xs px-1.5 py-0.5 rounded font-mono',
                  modelPayload.isFree
                    ? 'bg-success/15 text-success'
                    : 'bg-warning/15 text-warning'
                )}>
                  {modelPayload.model.split('/').pop()}
                </span>
              )}

              {/* Cost badge */}
              {(event.costUsd !== undefined && event.costUsd > 0) || modelPayload?.costUsd ? (
                <span className="text-xs px-1.5 py-0.5 rounded bg-surface-overlay text-text-muted font-mono">
                  {formatCost(modelPayload?.costUsd ?? event.costUsd ?? 0)}
                </span>
              ) : null}
            </div>

            {summary && (
              <p className="text-xs text-text-muted mt-0.5 leading-relaxed truncate">
                {summary}
              </p>
            )}
          </div>

          {/* Timestamp + expand */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="text-xs text-text-muted/60 font-mono">
              {formatTimestamp(event.timestamp)}
            </span>
            {hasPayload && (
              <ChevronDown
                className={cn(
                  'w-3.5 h-3.5 text-text-muted transition-transform opacity-0 group-hover:opacity-100',
                  expanded && 'rotate-180 opacity-100'
                )}
              />
            )}
          </div>
        </div>

        {/* Expanded payload */}
        <AnimatePresence>
          {expanded && hasPayload && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden border-t border-border"
            >
              <pre className="text-xs p-3 text-text-muted font-mono leading-relaxed overflow-x-auto max-h-64 overflow-y-auto bg-black/20">
                {safeJsonStringify(payload)}
              </pre>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

// ============================================================
// Main component
// ============================================================

const FILTER_TABS: { id: FilterTab; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'tools', label: 'Tools' },
  { id: 'models', label: 'Models' },
  { id: 'errors', label: 'Errors' },
  { id: 'approvals', label: 'Approvals' },
];

interface EventTimelineProps {
  events: AgentEvent[];
  isConnected?: boolean;
}

export function EventTimeline({ events, isConnected }: EventTimelineProps) {
  const [filter, setFilter] = useState<FilterTab>('all');
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    if (filter === 'all') return events;
    return events.filter((e) => {
      const cfg = EVENT_CONFIG[e.type];
      return cfg?.filter === filter || cfg?.filter === 'all' ? false : cfg?.filter === filter;
    });
  }, [events, filter]);

  // Real filter
  const realFiltered = useMemo(() => {
    if (filter === 'all') return events;
    return events.filter((e) => {
      const cfg = EVENT_CONFIG[e.type];
      return cfg?.filter === filter;
    });
  }, [events, filter]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events.length, autoScroll]);

  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoScroll(isAtBottom);
  }

  const errorCount = events.filter((e) =>
    e.type === EventType.ERROR || e.type === EventType.TASK_FAILED || e.type === EventType.TOOL_CALL_FAILED
  ).length;

  return (
    <div className="flex flex-col h-full gap-3">
      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-text">Event Timeline</span>
          <span className="text-xs text-text-muted bg-surface-overlay px-2 py-0.5 rounded-full">
            {events.length}
          </span>
          {isConnected && (
            <span className="flex items-center gap-1 text-xs text-success">
              <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
              Live
            </span>
          )}
          {!isConnected && events.length > 0 && (
            <span className="flex items-center gap-1 text-xs text-text-muted">
              <span className="w-1.5 h-1.5 rounded-full bg-text-muted" />
              Disconnected
            </span>
          )}
        </div>
        {errorCount > 0 && (
          <span className="text-xs text-error bg-error/10 px-2 py-0.5 rounded-full">
            {errorCount} error{errorCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Filter tabs */}
      <div className="flex items-center gap-1 flex-shrink-0 overflow-x-auto">
        <Filter className="w-3.5 h-3.5 text-text-muted flex-shrink-0 mr-1" />
        {FILTER_TABS.map((tab) => {
          const count = tab.id === 'all' ? events.length
            : events.filter((e) => EVENT_CONFIG[e.type]?.filter === tab.id).length;
          return (
            <button
              key={tab.id}
              onClick={() => setFilter(tab.id)}
              className={cn(
                'px-3 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition-colors',
                filter === tab.id
                  ? 'bg-primary/20 text-accent border border-primary/30'
                  : 'text-text-muted hover:text-text hover:bg-surface-elevated'
              )}
            >
              {tab.label}
              {count > 0 && (
                <span className={cn('ml-1', filter === tab.id ? 'text-accent/70' : 'text-text-muted/50')}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Events list */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto flex flex-col gap-2 pr-1"
      >
        {realFiltered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 gap-3 text-text-muted">
            <Loader2 className="w-6 h-6 opacity-30 animate-spin" />
            <p className="text-xs">
              {isConnected ? 'Waiting for events…' : 'No events yet.'}
            </p>
          </div>
        ) : (
          <>
            {realFiltered.map((event) => (
              <EventCard key={event.id} event={event} />
            ))}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Auto-scroll indicator */}
      {!autoScroll && events.length > 0 && (
        <button
          onClick={() => {
            setAutoScroll(true);
            bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
          }}
          className="flex-shrink-0 text-xs text-primary hover:text-accent transition-colors text-center py-1"
        >
          Jump to latest ↓
        </button>
      )}
    </div>
  );
}
