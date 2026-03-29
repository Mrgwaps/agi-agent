'use client';

import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Wrench,
  ChevronDown,
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  Globe,
  Code2,
  FolderOpen,
  Terminal,
  Search,
  Database,
} from 'lucide-react';
import { type AgentEvent, EventType } from '@/lib/types';
import { cn, formatTimestamp, formatDuration, safeJsonStringify } from '@/lib/utils';

// ============================================================
// Tool icon mapping
// ============================================================

const TOOL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  web_search: Search,
  browse_url: Globe,
  run_code: Code2,
  execute_python: Code2,
  execute_shell: Terminal,
  read_file: FolderOpen,
  write_file: FolderOpen,
  list_files: FolderOpen,
  query_db: Database,
  default: Wrench,
};

function getToolIcon(toolName: string): React.ComponentType<{ className?: string }> {
  const lower = toolName.toLowerCase();
  for (const [key, Icon] of Object.entries(TOOL_ICONS)) {
    if (lower.includes(key)) return Icon;
  }
  return TOOL_ICONS.default;
}

// ============================================================
// Tool call extracted from events
// ============================================================

interface ToolCall {
  id: string;
  toolName: string;
  input: Record<string, unknown>;
  output?: unknown;
  error?: string;
  status: 'running' | 'completed' | 'failed';
  startedAt: string;
  completedAt?: string;
  latencyMs?: number;
}

function extractToolCalls(events: AgentEvent[]): ToolCall[] {
  const calls: Map<string, ToolCall> = new Map();

  for (const event of events) {
    const p = event.payload as {
      callId?: string;
      toolName?: string;
      input?: Record<string, unknown>;
      output?: unknown;
      error?: string;
      latencyMs?: number;
    };

    // Backend uses step_id to correlate tool_called / tool_result events
    const callId = (p as Record<string, unknown>).callId as string
      || (p as Record<string, unknown>).step_id as string
      || event.id;
    const toolName = p.toolName || (p as Record<string, unknown>).tool as string || 'unknown';

    if (event.type === EventType.TOOL_CALL_STARTED) {
      calls.set(callId, {
        id: callId,
        toolName,
        input: (p.input as Record<string, unknown>) || {},
        status: 'running',
        startedAt: event.timestamp,
      });
    } else if (event.type === EventType.TOOL_CALL_COMPLETED) {
      const existing = calls.get(callId);
      // Backend sends result_preview instead of output
      const output = p.output ?? (p as Record<string, unknown>).result_preview;
      if (existing) {
        calls.set(callId, {
          ...existing,
          output,
          status: 'completed',
          completedAt: event.timestamp,
          latencyMs: p.latencyMs,
        });
      } else {
        calls.set(callId, {
          id: callId,
          toolName,
          input: {},
          output,
          status: 'completed',
          startedAt: event.timestamp,
          completedAt: event.timestamp,
          latencyMs: p.latencyMs,
        });
      }
    } else if (event.type === EventType.TOOL_CALL_FAILED) {
      const existing = calls.get(callId);
      if (existing) {
        calls.set(callId, {
          ...existing,
          error: p.error || 'Unknown error',
          status: 'failed',
          completedAt: event.timestamp,
          latencyMs: p.latencyMs,
        });
      }
    }
  }

  return Array.from(calls.values()).sort(
    (a, b) => new Date(a.startedAt).getTime() - new Date(b.startedAt).getTime()
  );
}

// ============================================================
// Tool row
// ============================================================

function ToolRow({ call }: { call: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const Icon = getToolIcon(call.toolName);
  const latency = call.latencyMs ?? (
    call.completedAt
      ? new Date(call.completedAt).getTime() - new Date(call.startedAt).getTime()
      : null
  );

  const statusColor = {
    running: 'text-warning bg-warning/10',
    completed: 'text-success bg-success/10',
    failed: 'text-error bg-error/10',
  }[call.status];

  const StatusIcon = call.status === 'running' ? Loader2
    : call.status === 'completed' ? CheckCircle2
    : XCircle;

  return (
    <div className={cn(
      'border rounded-xl overflow-hidden transition-colors',
      call.status === 'failed' ? 'border-error/20' : 'border-border hover:border-border/80'
    )}>
      {/* Header row */}
      <div
        className="flex items-center gap-3 p-3 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        {/* Tool icon */}
        <div className="w-7 h-7 rounded-lg bg-surface-elevated flex items-center justify-center flex-shrink-0">
          <Icon className="w-3.5 h-3.5 text-accent" />
        </div>

        {/* Tool name */}
        <code className="text-sm font-mono text-text flex-1 min-w-0 truncate">
          {call.toolName}
        </code>

        {/* Metadata */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {latency !== null && (
            <span className="flex items-center gap-1 text-xs text-text-muted font-mono">
              <Clock className="w-3 h-3" />
              {formatDuration(latency)}
            </span>
          )}
          <span className={cn('flex items-center gap-1 text-xs px-2 py-0.5 rounded font-medium', statusColor)}>
            <StatusIcon className={cn('w-3 h-3', call.status === 'running' && 'animate-spin')} />
            {call.status}
          </span>
          <span className="text-xs text-text-muted/60 font-mono">
            {formatTimestamp(call.startedAt)}
          </span>
          <ChevronDown
            className={cn('w-3.5 h-3.5 text-text-muted transition-transform', expanded && 'rotate-180')}
          />
        </div>
      </div>

      {/* Expanded section */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="border-t border-border grid grid-cols-2 divide-x divide-border">
              {/* Input */}
              <div className="p-3">
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">Input</p>
                <pre className="text-xs text-text-muted font-mono leading-relaxed overflow-x-auto max-h-48 overflow-y-auto">
                  {safeJsonStringify(call.input)}
                </pre>
              </div>

              {/* Output / Error */}
              <div className="p-3">
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
                  {call.error ? 'Error' : 'Output'}
                </p>
                {call.error ? (
                  <pre className="text-xs text-error font-mono leading-relaxed overflow-x-auto max-h-48 overflow-y-auto">
                    {call.error}
                  </pre>
                ) : call.output !== undefined ? (
                  <pre className="text-xs text-text-muted font-mono leading-relaxed overflow-x-auto max-h-48 overflow-y-auto">
                    {typeof call.output === 'string' ? call.output : safeJsonStringify(call.output)}
                  </pre>
                ) : (
                  <p className="text-xs text-text-muted italic">
                    {call.status === 'running' ? 'Executing…' : 'No output'}
                  </p>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ============================================================
// Main component
// ============================================================

interface ToolLogProps {
  events: AgentEvent[];
}

export function ToolLog({ events }: ToolLogProps) {
  const toolCalls = useMemo(() => extractToolCalls(events), [events]);

  const stats = useMemo(() => ({
    total: toolCalls.length,
    completed: toolCalls.filter((c) => c.status === 'completed').length,
    failed: toolCalls.filter((c) => c.status === 'failed').length,
    running: toolCalls.filter((c) => c.status === 'running').length,
  }), [toolCalls]);

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-text">Tool Log</span>
          <span className="text-xs text-text-muted bg-surface-overlay px-2 py-0.5 rounded-full">
            {stats.total}
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          {stats.running > 0 && (
            <span className="flex items-center gap-1 text-warning">
              <Loader2 className="w-3 h-3 animate-spin" />
              {stats.running} running
            </span>
          )}
          {stats.failed > 0 && (
            <span className="text-error">{stats.failed} failed</span>
          )}
          {stats.completed > 0 && (
            <span className="text-success">{stats.completed} done</span>
          )}
        </div>
      </div>

      {/* Tool list */}
      <div className="flex-1 overflow-y-auto flex flex-col gap-2 pr-1">
        {toolCalls.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 gap-3 text-text-muted">
            <Wrench className="w-6 h-6 opacity-30" />
            <p className="text-xs">No tool calls yet.</p>
          </div>
        ) : (
          toolCalls.map((call) => <ToolRow key={call.id} call={call} />)
        )}
      </div>
    </div>
  );
}
