'use client';

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import * as Tabs from '@radix-ui/react-tabs';
import {
  BrainCircuit,
  Activity,
  Wrench,
  Package,
  StopCircle,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  AlertCircle,
} from 'lucide-react';
import { useStore } from '@/lib/store';
import { useTaskStream } from '@/hooks/useTaskStream';
import { abortTask } from '@/lib/api';
import { TaskStatus } from '@/lib/types';
import { PlanView } from './PlanView';
import { EventTimeline } from './EventTimeline';
import { ToolLog } from './ToolLog';
import { ArtifactViewer } from './ArtifactViewer';
import { ApprovalPrompt } from './ApprovalPrompt';
import { cn, formatCost, formatRelativeTime } from '@/lib/utils';

// ============================================================
// Status banner
// ============================================================

const STATUS_CONFIG = {
  [TaskStatus.PENDING]: { icon: Clock, color: 'text-text-muted', bg: 'bg-surface', label: 'Pending' },
  [TaskStatus.PLANNING]: { icon: BrainCircuit, color: 'text-accent', bg: 'bg-accent/10', label: 'Planning…' },
  [TaskStatus.RUNNING]: { icon: Loader2, color: 'text-primary', bg: 'bg-primary/10', label: 'Running' },
  [TaskStatus.AWAITING_APPROVAL]: { icon: AlertCircle, color: 'text-warning', bg: 'bg-warning/10', label: 'Awaiting Approval' },
  [TaskStatus.COMPLETED]: { icon: CheckCircle2, color: 'text-success', bg: 'bg-success/10', label: 'Completed' },
  [TaskStatus.FAILED]: { icon: XCircle, color: 'text-error', bg: 'bg-error/10', label: 'Failed' },
  [TaskStatus.ABORTED]: { icon: StopCircle, color: 'text-text-muted', bg: 'bg-surface', label: 'Aborted' },
};

// ============================================================
// Tab config
// ============================================================

const TABS = [
  { id: 'plan', label: 'Plan', icon: BrainCircuit },
  { id: 'events', label: 'Events', icon: Activity },
  { id: 'tools', label: 'Tools', icon: Wrench },
  { id: 'artifacts', label: 'Artifacts', icon: Package },
] as const;

type TabId = typeof TABS[number]['id'];

// ============================================================
// Main component
// ============================================================

interface TaskViewProps {
  taskId: string;
}

export function TaskView({ taskId }: TaskViewProps) {
  const task = useStore((s) => s.tasks[taskId]);
  const addToast = useStore((s) => s.addToast);
  const [activeTab, setActiveTab] = useState<TabId>('events');
  const [aborting, setAborting] = useState(false);

  const { events, isConnected } = useTaskStream(taskId);

  if (!task) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted">
        <p className="text-sm">Task not found.</p>
      </div>
    );
  }

  const statusCfg = STATUS_CONFIG[task.status] ?? STATUS_CONFIG[TaskStatus.PENDING];
  const StatusIcon = statusCfg.icon;
  const isActive = task.status === TaskStatus.RUNNING || task.status === TaskStatus.PLANNING;
  const plan = task.plan || [];
  const artifacts = task.artifacts || [];

  const toolCallEvents = events.filter(
    (e) => e.type === EventType.TOOL_CALL_STARTED || e.type === EventType.TOOL_CALL_COMPLETED || e.type === EventType.TOOL_CALL_FAILED
  );

  async function handleAbort() {
    if (aborting) return;
    setAborting(true);
    try {
      await abortTask(taskId);
      addToast({ type: 'info', title: 'Task aborted', message: 'The agent has been stopped.' });
    } catch (err) {
      addToast({
        type: 'error',
        title: 'Failed to abort',
        message: err instanceof Error ? err.message : '',
      });
    } finally {
      setAborting(false);
    }
  }

  return (
    <div className="flex flex-col h-full gap-0 overflow-hidden">
      {/* Task header */}
      <div className="flex-shrink-0 px-5 py-4 border-b border-border">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-xs text-text-muted uppercase tracking-wider font-medium mb-1">
              Task Goal
            </p>
            <h2 className="text-sm font-semibold text-text leading-relaxed line-clamp-2">
              {task.goal}
            </h2>
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            {/* Status badge */}
            <div className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold',
              statusCfg.bg, statusCfg.color
            )}>
              <StatusIcon className={cn('w-3.5 h-3.5', isActive && 'animate-spin')} />
              {statusCfg.label}
            </div>

            {/* Abort button */}
            {(isActive || task.status === TaskStatus.AWAITING_APPROVAL) && (
              <button
                onClick={handleAbort}
                disabled={aborting}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium',
                  'border border-error/30 bg-error/10 text-error hover:bg-error/20 transition-colors'
                )}
              >
                {aborting ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <StopCircle className="w-3.5 h-3.5" />
                )}
                Abort
              </button>
            )}
          </div>
        </div>

        {/* Meta row */}
        <div className="flex items-center gap-4 mt-2.5 text-xs text-text-muted">
          <span>{formatRelativeTime(task.createdAt)}</span>
          {task.totalCostUsd > 0 && (
            <span className="font-mono">{formatCost(task.totalCostUsd)}</span>
          )}
          {plan.length > 0 && (
            <span>
              {plan.filter((s) => s.status === 'completed').length}/{plan.length} steps
            </span>
          )}
          <span className={cn('font-mono text-xs', task.mode === 'demo' ? 'text-accent' : 'text-primary')}>
            {task.mode}
          </span>
        </div>

        {/* Error message */}
        {task.error && (
          <div className="mt-3 p-3 rounded-xl bg-error/10 border border-error/20 text-xs text-error">
            {task.error}
          </div>
        )}
      </div>

      {/* Tabs */}
      <Tabs.Root
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as TabId)}
        className="flex-1 flex flex-col overflow-hidden"
      >
        <Tabs.List className="flex-shrink-0 flex items-center gap-0.5 px-4 pt-3 border-b border-border overflow-x-auto">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            let badge = 0;
            if (tab.id === 'artifacts') badge = artifacts.length;
            if (tab.id === 'tools') badge = toolCallEvents.length / 2 | 0;

            return (
              <Tabs.Trigger
                key={tab.id}
                value={tab.id}
                className={cn(
                  'flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-medium rounded-t-lg transition-all',
                  'border-b-2 -mb-px',
                  activeTab === tab.id
                    ? 'text-primary border-primary bg-primary/5'
                    : 'text-text-muted border-transparent hover:text-text hover:bg-surface-elevated'
                )}
              >
                <Icon className="w-3.5 h-3.5" />
                {tab.label}
                {badge > 0 && (
                  <span className={cn(
                    'text-xs px-1.5 py-0.5 rounded-full font-mono',
                    activeTab === tab.id ? 'bg-primary/20 text-accent' : 'bg-surface-overlay text-text-muted'
                  )}>
                    {badge}
                  </span>
                )}
              </Tabs.Trigger>
            );
          })}
        </Tabs.List>

        <div className="flex-1 overflow-hidden">
          <Tabs.Content
            value="plan"
            className="h-full overflow-y-auto p-4"
          >
            {plan.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-32 gap-3 text-text-muted">
                <BrainCircuit className="w-8 h-8 opacity-30" />
                <p className="text-xs">
                  {isActive ? 'The agent is still planning…' : 'No plan generated.'}
                </p>
              </div>
            ) : (
              <PlanView plan={plan} currentStepIndex={task.currentStepIndex} />
            )}
          </Tabs.Content>

          <Tabs.Content
            value="events"
            className="h-full overflow-hidden p-4"
          >
            <EventTimeline events={events} isConnected={isConnected} />
          </Tabs.Content>

          <Tabs.Content
            value="tools"
            className="h-full overflow-hidden p-4"
          >
            <ToolLog events={events} />
          </Tabs.Content>

          <Tabs.Content
            value="artifacts"
            className="h-full overflow-y-auto p-4"
          >
            <ArtifactViewer artifacts={artifacts} />
          </Tabs.Content>
        </div>
      </Tabs.Root>

      {/* Approval modal */}
      {task.status === TaskStatus.AWAITING_APPROVAL && task.pendingApproval && (
        <ApprovalPrompt
          taskId={taskId}
          approval={task.pendingApproval}
          onDone={() => {
            // Task state will update via SSE
          }}
        />
      )}
    </div>
  );
}
