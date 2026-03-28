'use client';

import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  DollarSign,
  Zap,
  TrendingUp,
  AlertTriangle,
  BarChart3,
  Sparkles,
  Settings,
} from 'lucide-react';
import { useStore } from '@/lib/store';
import { cn, formatCost, formatTokens } from '@/lib/utils';

// ============================================================
// Donut chart (pure CSS/SVG)
// ============================================================

interface DonutChartProps {
  free: number;
  paid: number;
  size?: number;
}

function DonutChart({ free, paid, size = 72 }: DonutChartProps) {
  const total = free + paid;
  if (total === 0) {
    return (
      <svg width={size} height={size} viewBox="0 0 72 72">
        <circle cx="36" cy="36" r="28" fill="none" stroke="#1e1e2e" strokeWidth="8" />
        <text x="36" y="40" textAnchor="middle" className="text-xs" fill="#64748b" fontSize="10">
          0
        </text>
      </svg>
    );
  }

  const radius = 28;
  const circumference = 2 * Math.PI * radius;
  const freePercent = free / total;
  const freeDash = freePercent * circumference;

  return (
    <svg width={size} height={size} viewBox="0 0 72 72" className="-rotate-90">
      {/* Background ring */}
      <circle cx="36" cy="36" r={radius} fill="none" stroke="#1e1e2e" strokeWidth="8" />
      {/* Paid ring (full) */}
      {paid > 0 && (
        <circle
          cx="36" cy="36" r={radius}
          fill="none"
          stroke="#f59e0b"
          strokeWidth="8"
          strokeDasharray={circumference}
        />
      )}
      {/* Free ring (on top) */}
      {free > 0 && (
        <circle
          cx="36" cy="36" r={radius}
          fill="none"
          stroke="#22c55e"
          strokeWidth="8"
          strokeDasharray={`${freeDash} ${circumference - freeDash}`}
          strokeLinecap="round"
        />
      )}
      {/* Center text – rotate back */}
      <text
        x="36" y="40"
        textAnchor="middle"
        fill="#e2e8f0"
        fontSize="12"
        fontWeight="600"
        className="rotate-90"
        transform="rotate(90, 36, 36)"
      >
        {total}
      </text>
    </svg>
  );
}

// ============================================================
// Budget progress bar
// ============================================================

interface BudgetBarProps {
  spent: number;
  limit: number;
}

function BudgetBar({ spent, limit }: BudgetBarProps) {
  const percent = limit > 0 ? Math.min((spent / limit) * 100, 100) : 0;
  const isOver = spent > limit && limit > 0;
  const isNear = percent > 80 && !isOver;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-text-muted">Budget used</span>
        <span className={cn(
          'font-mono font-medium',
          isOver ? 'text-error' : isNear ? 'text-warning' : 'text-text'
        )}>
          {formatCost(spent)} / {formatCost(limit)}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-overlay overflow-hidden">
        <motion.div
          className={cn(
            'h-full rounded-full transition-all',
            isOver ? 'bg-error' : isNear ? 'bg-warning' : 'bg-success'
          )}
          initial={{ width: 0 }}
          animate={{ width: `${percent}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        />
      </div>
      {isOver && (
        <div className="flex items-center gap-1 text-xs text-error">
          <AlertTriangle className="w-3 h-3" />
          Budget exceeded by {formatCost(spent - limit)}
        </div>
      )}
    </div>
  );
}

// ============================================================
// Model row in breakdown table
// ============================================================

function ModelRow({ model, calls, inputTokens, outputTokens, totalCostUsd, isFree }: {
  model: string;
  calls: number;
  inputTokens: number;
  outputTokens: number;
  totalCostUsd: number;
  isFree: boolean;
}) {
  const shortName = model.split('/').pop() || model;
  const costColor = isFree ? 'text-success'
    : totalCostUsd < 0.001 ? 'text-warning'
    : 'text-error';

  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-border/50 last:border-0">
      <div className={cn(
        'w-1.5 h-1.5 rounded-full flex-shrink-0',
        isFree ? 'bg-success' : totalCostUsd < 0.001 ? 'bg-warning' : 'bg-error'
      )} />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-mono text-text truncate" title={model}>{shortName}</p>
        <p className="text-xs text-text-muted">
          {formatTokens(inputTokens + outputTokens)} tokens
        </p>
      </div>
      <div className="text-right flex-shrink-0">
        <p className={cn('text-xs font-mono font-semibold', costColor)}>
          {isFree ? 'FREE' : formatCost(totalCostUsd)}
        </p>
        <p className="text-xs text-text-muted">{calls}x</p>
      </div>
    </div>
  );
}

// ============================================================
// Main component
// ============================================================

interface CostTrackerProps {
  taskId?: string | null;
  onOpenSettings?: () => void;
}

export function CostTracker({ taskId, onOpenSettings }: CostTrackerProps) {
  const costSummary = useStore((s) =>
    taskId ? s.costSummary[taskId] : undefined
  );
  const settings = useStore((s) => s.settings);

  // Aggregate across all tasks for "session total"
  const allCosts = useStore((s) => s.costSummary);
  const sessionTotal = useMemo(
    () => Object.values(allCosts).reduce((sum, c) => sum + c.totalCost, 0),
    [allCosts]
  );

  const summary = costSummary;
  const budgetLimit = settings.maxBudgetUsd;

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Session total */}
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <span className="text-xs text-text-muted uppercase tracking-wider font-medium">Session Total</span>
          <button
            onClick={onOpenSettings}
            className="p-1 rounded text-text-muted hover:text-text transition-colors"
            title="Settings"
          >
            <Settings className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="flex items-end gap-1">
          <span className="text-3xl font-bold text-text font-mono leading-none">
            {formatCost(sessionTotal)}
          </span>
          <span className="text-xs text-text-muted mb-0.5">USD</span>
        </div>
      </div>

      {/* Task cost if available */}
      {summary && taskId && (
        <>
          <div className="h-px bg-border" />

          {/* Free vs paid donut */}
          <div className="flex items-center gap-4">
            <DonutChart free={summary.freeModelCalls} paid={summary.paidModelCalls} />
            <div className="flex flex-col gap-2 flex-1">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-success flex-shrink-0" />
                <span className="text-xs text-text-muted">Free calls</span>
                <span className="text-xs font-semibold text-success ml-auto">
                  {summary.freeModelCalls}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-warning flex-shrink-0" />
                <span className="text-xs text-text-muted">Paid calls</span>
                <span className="text-xs font-semibold text-warning ml-auto">
                  {summary.paidModelCalls}
                </span>
              </div>
            </div>
          </div>

          {/* Savings message */}
          {summary.freeModelSavingsUsd > 0 && (
            <div className="flex items-center gap-2 p-2.5 rounded-xl bg-success/10 border border-success/20">
              <Sparkles className="w-4 h-4 text-success flex-shrink-0" />
              <p className="text-xs text-success">
                Free models saved you{' '}
                <span className="font-semibold">{formatCost(summary.freeModelSavingsUsd)}</span>
              </p>
            </div>
          )}

          {/* Task cost */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-text-muted">Task cost</span>
            <span className="text-sm font-semibold font-mono text-text">
              {formatCost(summary.totalCost)}
            </span>
          </div>

          {/* Budget bar */}
          {budgetLimit > 0 && (
            <BudgetBar spent={summary.totalCost} limit={budgetLimit} />
          )}

          {/* Model breakdown */}
          {summary.modelBreakdown.length > 0 && (
            <>
              <div className="h-px bg-border" />
              <div className="flex flex-col gap-0">
                <div className="flex items-center gap-2 mb-2">
                  <BarChart3 className="w-3.5 h-3.5 text-text-muted" />
                  <span className="text-xs font-medium text-text-muted uppercase tracking-wider">Model Breakdown</span>
                </div>
                {summary.modelBreakdown.map((m) => (
                  <ModelRow key={m.model} {...m} />
                ))}
              </div>
            </>
          )}
        </>
      )}

      {/* No active task */}
      {!summary && (
        <div className="flex flex-col items-center gap-2 py-4 text-text-muted">
          <DollarSign className="w-6 h-6 opacity-30" />
          <p className="text-xs text-center">Cost tracking will appear<br />when a task is running.</p>
        </div>
      )}

      {/* Settings link */}
      <button
        onClick={onOpenSettings}
        className={cn(
          'flex items-center justify-center gap-2 py-2 rounded-xl border border-border',
          'text-xs text-text-muted hover:text-text hover:border-border/80 transition-colors'
        )}
      >
        <TrendingUp className="w-3.5 h-3.5" />
        Manage budget & providers
      </button>
    </div>
  );
}
