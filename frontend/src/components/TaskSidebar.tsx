'use client';

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Plus,
  Trash2,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  AlertCircle,
  StopCircle,
  BrainCircuit,
} from 'lucide-react';
import { useStore } from '@/lib/store';
import { TaskStatus } from '@/lib/types';
import { cn, formatRelativeTime, formatCost, truncate } from '@/lib/utils';

const STATUS_CONFIG: Record<TaskStatus, { icon: React.ComponentType<{ className?: string }>; color: string; label: string }> = {
  [TaskStatus.PENDING]: { icon: Clock, color: 'text-text-muted', label: 'Pending' },
  [TaskStatus.PLANNING]: { icon: BrainCircuit, color: 'text-accent', label: 'Planning' },
  [TaskStatus.RUNNING]: { icon: Loader2, color: 'text-primary', label: 'Running' },
  [TaskStatus.AWAITING_APPROVAL]: { icon: AlertCircle, color: 'text-warning', label: 'Needs Approval' },
  [TaskStatus.COMPLETED]: { icon: CheckCircle, color: 'text-success', label: 'Completed' },
  [TaskStatus.FAILED]: { icon: XCircle, color: 'text-error', label: 'Failed' },
  [TaskStatus.ABORTED]: { icon: StopCircle, color: 'text-text-muted', label: 'Aborted' },
};

interface TaskSidebarProps {
  onNewTask: () => void;
}

export function TaskSidebar({ onNewTask }: TaskSidebarProps) {
  const tasks = useStore((s) => s.tasks);
  const currentTaskId = useStore((s) => s.currentTaskId);
  const setCurrentTask = useStore((s) => s.setCurrentTask);
  const removeTask = useStore((s) => s.removeTask);

  const sortedTasks = Object.values(tasks).sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );

  return (
    <aside className="w-64 flex flex-col h-full bg-card border-r border-border">
      {/* Header */}
      <div className="p-3 border-b border-border flex-shrink-0">
        <button
          onClick={onNewTask}
          className={cn(
            'w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl',
            'bg-primary hover:bg-primary-hover text-white font-semibold text-sm',
            'transition-all duration-150 active:scale-95 shadow-glow-sm'
          )}
        >
          <Plus className="w-4 h-4" />
          New Task
        </button>
      </div>

      {/* Task List */}
      <div className="flex-1 overflow-y-auto py-2 px-2">
        {sortedTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 gap-3 text-text-muted">
            <BrainCircuit className="w-8 h-8 opacity-30" />
            <p className="text-xs text-center">No tasks yet.<br />Create one to get started.</p>
          </div>
        ) : (
          <AnimatePresence mode="popLayout">
            {sortedTasks.map((task) => {
              const cfg = STATUS_CONFIG[task.status];
              const Icon = cfg.icon;
              const isActive = task.id === currentTaskId;
              const isRunning = task.status === TaskStatus.RUNNING || task.status === TaskStatus.PLANNING;

              return (
                <motion.div
                  key={task.id}
                  layout
                  initial={{ opacity: 0, x: -16 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -16 }}
                  transition={{ duration: 0.2 }}
                >
                  <div
                    onClick={() => setCurrentTask(task.id)}
                    className={cn(
                      'group relative flex flex-col gap-1.5 p-3 rounded-xl cursor-pointer mb-1',
                      'border transition-all duration-150',
                      isActive
                        ? 'bg-primary/10 border-primary/40 shadow-glow-sm'
                        : 'border-transparent hover:bg-surface-elevated hover:border-border'
                    )}
                  >
                    {/* Goal text */}
                    <p className={cn(
                      'text-xs leading-relaxed line-clamp-2 pr-6',
                      isActive ? 'text-text' : 'text-text-muted group-hover:text-text'
                    )}>
                      {truncate(task.goal, 100)}
                    </p>

                    {/* Status + cost row */}
                    <div className="flex items-center justify-between gap-2">
                      <div className={cn('flex items-center gap-1', cfg.color)}>
                        <Icon className={cn('w-3 h-3', isRunning && 'animate-spin')} />
                        <span className="text-xs font-medium">{cfg.label}</span>
                      </div>
                      {task.totalCostUsd > 0 && (
                        <span className="text-xs text-text-muted font-mono">
                          {formatCost(task.totalCostUsd)}
                        </span>
                      )}
                    </div>

                    {/* Time */}
                    <p className="text-xs text-text-muted opacity-60">
                      {formatRelativeTime(task.createdAt)}
                    </p>

                    {/* Delete button */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        removeTask(task.id);
                      }}
                      className={cn(
                        'absolute top-2 right-2 p-1 rounded opacity-0 group-hover:opacity-100',
                        'transition-opacity text-text-muted hover:text-error'
                      )}
                      aria-label="Delete task"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        )}
      </div>

      {/* Footer count */}
      {sortedTasks.length > 0 && (
        <div className="border-t border-border p-2 text-center">
          <p className="text-xs text-text-muted">{sortedTasks.length} task{sortedTasks.length !== 1 ? 's' : ''}</p>
        </div>
      )}
    </aside>
  );
}
