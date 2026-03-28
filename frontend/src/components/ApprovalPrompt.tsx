'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ShieldAlert,
  CheckCircle,
  XCircle,
  AlertTriangle,
  AlertCircle,
  Clock,
  Loader2,
} from 'lucide-react';
import { approveAction, denyAction } from '@/lib/api';
import { useStore } from '@/lib/store';
import { RiskLevel, type ApprovalRequest } from '@/lib/types';
import { cn } from '@/lib/utils';

// ============================================================
// Risk level config
// ============================================================

const RISK_CONFIG: Record<RiskLevel, {
  label: string;
  color: string;
  bg: string;
  border: string;
  icon: React.ComponentType<{ className?: string }>;
}> = {
  [RiskLevel.LOW]: {
    label: 'Low Risk',
    color: 'text-success',
    bg: 'bg-success/10',
    border: 'border-success/30',
    icon: CheckCircle,
  },
  [RiskLevel.MEDIUM]: {
    label: 'Medium Risk',
    color: 'text-warning',
    bg: 'bg-warning/10',
    border: 'border-warning/30',
    icon: AlertCircle,
  },
  [RiskLevel.HIGH]: {
    label: 'High Risk',
    color: 'text-error',
    bg: 'bg-error/10',
    border: 'border-error/30',
    icon: AlertTriangle,
  },
  [RiskLevel.CRITICAL]: {
    label: 'Critical Risk',
    color: 'text-error',
    bg: 'bg-error/15',
    border: 'border-error/50',
    icon: ShieldAlert,
  },
};

// ============================================================
// Countdown timer
// ============================================================

function CountdownRing({ seconds, total }: { seconds: number; total: number }) {
  const percent = (seconds / total) * 100;
  const circumference = 2 * Math.PI * 20;
  const dash = (percent / 100) * circumference;
  const color = percent > 50 ? '#f59e0b' : '#ef4444';

  return (
    <div className="relative w-12 h-12 flex items-center justify-center">
      <svg width="48" height="48" viewBox="0 0 48 48" className="-rotate-90 absolute inset-0">
        <circle cx="24" cy="24" r="20" fill="none" stroke="#1e1e2e" strokeWidth="3" />
        <circle
          cx="24" cy="24" r="20"
          fill="none"
          stroke={color}
          strokeWidth="3"
          strokeDasharray={`${dash} ${circumference - dash}`}
          strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 1s linear, stroke 0.3s' }}
        />
      </svg>
      <span className="text-sm font-bold font-mono text-text z-10">{seconds}</span>
    </div>
  );
}

// ============================================================
// Main component
// ============================================================

interface ApprovalPromptProps {
  taskId: string;
  approval: ApprovalRequest;
  onDone?: () => void;
}

export function ApprovalPrompt({ taskId, approval, onDone }: ApprovalPromptProps) {
  const addToast = useStore((s) => s.addToast);
  const [loading, setLoading] = useState<'approve' | 'deny' | null>(null);
  const timeoutSec = approval.timeoutSeconds ?? 60;
  const [remaining, setRemaining] = useState(timeoutSec);

  const risk = approval.riskLevel in RISK_CONFIG
    ? approval.riskLevel
    : RiskLevel.MEDIUM;
  const riskCfg = RISK_CONFIG[risk];
  const RiskIcon = riskCfg.icon;

  const handleDeny = useCallback(async () => {
    if (loading) return;
    setLoading('deny');
    try {
      await denyAction(taskId);
      addToast({ type: 'info', title: 'Action denied', message: 'The agent will try an alternative.' });
      onDone?.();
    } catch (err) {
      addToast({ type: 'error', title: 'Failed to deny', message: err instanceof Error ? err.message : '' });
    } finally {
      setLoading(null);
    }
  }, [taskId, loading, addToast, onDone]);

  // Auto-deny countdown
  useEffect(() => {
    if (remaining <= 0) {
      handleDeny();
      return;
    }
    const t = setTimeout(() => setRemaining((r) => r - 1), 1000);
    return () => clearTimeout(t);
  }, [remaining, handleDeny]);

  async function handleApprove() {
    if (loading) return;
    setLoading('approve');
    try {
      await approveAction(taskId);
      addToast({ type: 'success', title: 'Action approved', message: 'The agent will proceed.' });
      onDone?.();
    } catch (err) {
      addToast({ type: 'error', title: 'Failed to approve', message: err instanceof Error ? err.message : '' });
    } finally {
      setLoading(null);
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
      >
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        />

        {/* Modal */}
        <motion.div
          initial={{ scale: 0.92, opacity: 0, y: 16 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.92, opacity: 0, y: 16 }}
          transition={{ type: 'spring', stiffness: 400, damping: 28 }}
          className={cn(
            'relative w-full max-w-md glass-card rounded-2xl p-6',
            'border shadow-glow-md',
            riskCfg.border
          )}
        >
          {/* Header */}
          <div className="flex items-start gap-4 mb-5">
            <div className={cn('w-12 h-12 rounded-2xl flex items-center justify-center flex-shrink-0', riskCfg.bg)}>
              <RiskIcon className={cn('w-6 h-6', riskCfg.color)} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <h2 className="text-base font-bold text-text">Approval Required</h2>
                <span className={cn('text-xs font-semibold px-2 py-0.5 rounded-full', riskCfg.bg, riskCfg.color)}>
                  {riskCfg.label}
                </span>
              </div>
              <p className="text-sm font-semibold text-accent">{approval.action}</p>
            </div>
            <CountdownRing seconds={remaining} total={timeoutSec} />
          </div>

          {/* Description */}
          <div className="mb-4 p-3.5 rounded-xl bg-surface border border-border">
            <p className="text-sm text-text leading-relaxed">{approval.description}</p>
          </div>

          {/* Impact */}
          {approval.impact && (
            <div className="mb-5 p-3.5 rounded-xl bg-surface-overlay border border-border">
              <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1.5">
                Impact Preview
              </p>
              <p className="text-sm text-text-muted leading-relaxed">{approval.impact}</p>
            </div>
          )}

          {/* Auto-deny notice */}
          <div className="flex items-center gap-2 mb-5 text-xs text-text-muted">
            <Clock className="w-3.5 h-3.5" />
            <span>
              Auto-deny in <span className="font-semibold text-warning">{remaining}s</span> if no response
            </span>
          </div>

          {/* Buttons */}
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={handleDeny}
              disabled={!!loading}
              className={cn(
                'flex items-center justify-center gap-2 py-3 px-4 rounded-xl font-semibold text-sm',
                'border border-error/30 bg-error/10 text-error',
                'hover:bg-error/20 transition-colors',
                loading && 'opacity-60 cursor-not-allowed'
              )}
            >
              {loading === 'deny' ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <XCircle className="w-4 h-4" />
              )}
              Deny
            </button>

            <button
              onClick={handleApprove}
              disabled={!!loading}
              className={cn(
                'flex items-center justify-center gap-2 py-3 px-4 rounded-xl font-semibold text-sm',
                'bg-success hover:bg-success/90 text-white',
                'transition-colors shadow-glow-sm',
                loading && 'opacity-60 cursor-not-allowed'
              )}
            >
              {loading === 'approve' ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <CheckCircle className="w-4 h-4" />
              )}
              Approve
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
