'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle2,
  Circle,
  XCircle,
  SkipForward,
  ChevronDown,
  Wrench,
  Target,
  DollarSign,
  Clock,
  Loader2,
} from 'lucide-react';
import { StepStatus, type TaskStep } from '@/lib/types';
import { cn, formatCost } from '@/lib/utils';

const STATUS_ICON: Record<StepStatus, React.ComponentType<{ className?: string }>> = {
  [StepStatus.PENDING]: Circle,
  [StepStatus.RUNNING]: Loader2,
  [StepStatus.COMPLETED]: CheckCircle2,
  [StepStatus.FAILED]: XCircle,
  [StepStatus.SKIPPED]: SkipForward,
};

const STATUS_COLORS: Record<StepStatus, string> = {
  [StepStatus.PENDING]: 'text-text-muted',
  [StepStatus.RUNNING]: 'text-primary',
  [StepStatus.COMPLETED]: 'text-success',
  [StepStatus.FAILED]: 'text-error',
  [StepStatus.SKIPPED]: 'text-text-muted opacity-50',
};

const STATUS_BG: Record<StepStatus, string> = {
  [StepStatus.PENDING]: 'bg-surface border-border',
  [StepStatus.RUNNING]: 'bg-primary/10 border-primary/40 animate-pulse-glow',
  [StepStatus.COMPLETED]: 'bg-success/5 border-success/30',
  [StepStatus.FAILED]: 'bg-error/5 border-error/30',
  [StepStatus.SKIPPED]: 'bg-surface border-border opacity-40',
};

function StepCard({ step, isActive }: { step: TaskStep; isActive: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const Icon = STATUS_ICON[step.status];
  const isRunning = step.status === StepStatus.RUNNING;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'rounded-xl border p-3.5 transition-all duration-300',
        STATUS_BG[step.status],
        isActive && 'ring-1 ring-primary/30'
      )}
    >
      <div
        className="flex items-start gap-3 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        {/* Step number + icon */}
        <div className="flex flex-col items-center gap-1 flex-shrink-0 mt-0.5">
          <div className={cn('w-6 h-6 rounded-full flex items-center justify-center', STATUS_COLORS[step.status])}>
            <Icon className={cn('w-4 h-4', isRunning && 'animate-spin')} />
          </div>
          <span className="text-xs font-mono text-text-muted/60">{step.index + 1}</span>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <p className={cn(
              'text-sm font-semibold leading-snug',
              isRunning ? 'text-accent' : 'text-text'
            )}>
              {step.title}
            </p>
            <div className="flex items-center gap-2 flex-shrink-0">
              {(step.actualCostUsd !== undefined || step.estimatedCostUsd !== undefined) && (
                <span className="text-xs font-mono text-text-muted flex items-center gap-0.5">
                  <DollarSign className="w-3 h-3" />
                  {step.actualCostUsd !== undefined
                    ? formatCost(step.actualCostUsd)
                    : `~${formatCost(step.estimatedCostUsd!)}`}
                </span>
              )}
              {(step.toolToUse || step.expectedOutput) && (
                <ChevronDown
                  className={cn(
                    'w-4 h-4 text-text-muted transition-transform',
                    expanded && 'rotate-180'
                  )}
                />
              )}
            </div>
          </div>

          {/* Description */}
          <p className="text-xs text-text-muted mt-1 leading-relaxed">
            {step.description}
          </p>

          {/* Timing */}
          {(step.startedAt || step.completedAt) && (
            <div className="flex items-center gap-2 mt-2">
              {step.startedAt && step.completedAt && (
                <span className="flex items-center gap-1 text-xs text-text-muted">
                  <Clock className="w-3 h-3" />
                  {((new Date(step.completedAt).getTime() - new Date(step.startedAt).getTime()) / 1000).toFixed(1)}s
                </span>
              )}
              {isRunning && step.startedAt && (
                <span className="flex items-center gap-1 text-xs text-primary">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  Running…
                </span>
              )}
            </div>
          )}

          {/* Error */}
          {step.error && (
            <p className="text-xs text-error mt-2 font-mono bg-error/10 px-2 py-1 rounded">
              {step.error}
            </p>
          )}
        </div>
      </div>

      {/* Expanded details */}
      <AnimatePresence>
        {expanded && (step.toolToUse || step.expectedOutput) && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-3 pt-3 border-t border-border/50 flex flex-col gap-2.5 ml-9">
              {step.toolToUse && (
                <div className="flex items-start gap-2">
                  <Wrench className="w-3.5 h-3.5 text-accent mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-xs text-text-muted uppercase tracking-wider font-medium">Tool</p>
                    <p className="text-xs text-text font-mono mt-0.5">{step.toolToUse}</p>
                  </div>
                </div>
              )}
              {step.expectedOutput && (
                <div className="flex items-start gap-2">
                  <Target className="w-3.5 h-3.5 text-accent mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-xs text-text-muted uppercase tracking-wider font-medium">Expected output</p>
                    <p className="text-xs text-text mt-0.5 leading-relaxed">{step.expectedOutput}</p>
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

interface PlanViewProps {
  plan: TaskStep[];
  currentStepIndex?: number;
}

export function PlanView({ plan, currentStepIndex }: PlanViewProps) {
  const completed = plan.filter((s) => s.status === StepStatus.COMPLETED).length;
  const failed = plan.filter((s) => s.status === StepStatus.FAILED).length;
  const progress = plan.length > 0 ? (completed / plan.length) * 100 : 0;

  const totalEstimated = plan.reduce((sum, s) => sum + (s.estimatedCostUsd || 0), 0);
  const totalActual = plan.reduce((sum, s) => sum + (s.actualCostUsd || 0), 0);

  return (
    <div className="flex flex-col gap-4">
      {/* Progress header */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between text-sm">
          <span className="text-text font-semibold">
            {completed} / {plan.length} steps
          </span>
          <div className="flex items-center gap-3">
            {failed > 0 && (
              <span className="text-error text-xs">{failed} failed</span>
            )}
            <span className="text-text-muted text-xs font-mono">
              {totalActual > 0
                ? formatCost(totalActual)
                : totalEstimated > 0
                ? `~${formatCost(totalEstimated)} est.`
                : ''}
            </span>
          </div>
        </div>

        {/* Progress bar */}
        <div className="h-1.5 rounded-full bg-surface-overlay overflow-hidden">
          <motion.div
            className={cn(
              'h-full rounded-full transition-all',
              failed > 0 ? 'bg-error' : 'bg-primary'
            )}
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
          />
        </div>
      </div>

      {/* Step list */}
      <div className="flex flex-col gap-2">
        {plan.map((step) => (
          <StepCard
            key={step.id}
            step={step}
            isActive={step.index === currentStepIndex}
          />
        ))}
      </div>
    </div>
  );
}
