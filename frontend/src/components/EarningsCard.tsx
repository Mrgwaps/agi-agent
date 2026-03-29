'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  DollarSign,
  TrendingUp,
  RefreshCw,
  Zap,
  CreditCard,
  Globe,
  Loader2,
  ArrowUpRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface EarningsSummary {
  total_usd: number;
  recent_24h_usd: number;
  recent_7d_usd: number;
  by_source: Record<string, number>;
  payment_count: number;
  last_payment: number | null;
}

interface Payment {
  id: string;
  agent_id: string;
  amount_usd: number;
  source: string;
  reference_id: string | null;
  description: string;
  payer_email: string | null;
  created_at: number;
}

const SOURCE_COLORS: Record<string, string> = {
  stripe: 'text-violet-400',
  etsy: 'text-orange-400',
  fiverr: 'text-green-400',
  upwork: 'text-emerald-400',
  mturk: 'text-yellow-400',
  manual: 'text-blue-400',
};

const SOURCE_ICONS: Record<string, React.ReactNode> = {
  stripe: <CreditCard className="w-3 h-3" />,
  etsy: <Globe className="w-3 h-3" />,
  fiverr: <Globe className="w-3 h-3" />,
  upwork: <Globe className="w-3 h-3" />,
  mturk: <Globe className="w-3 h-3" />,
  manual: <DollarSign className="w-3 h-3" />,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtUsd(n: number): string {
  if (n === 0) return '$0.00';
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function fmtTime(ts: number | null): string {
  if (!ts) return 'Never';
  const diff = Math.floor((Date.now() / 1000 - ts));
  if (diff < 60) return 'Just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

async function fetchSummary(agentId?: string): Promise<EarningsSummary | null> {
  try {
    const url = agentId
      ? `/api/agents/${encodeURIComponent(agentId)}/balance`
      : '/api/payments/summary';
    const res = await fetch(url);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

async function fetchRecentPayments(agentId?: string, limit = 10): Promise<Payment[]> {
  try {
    const url = agentId
      ? `/api/agents/${encodeURIComponent(agentId)}/payments?limit=${limit}`
      : `/api/payments/list?limit=${limit}`;
    const res = await fetch(url);
    if (!res.ok) return [];
    const data = await res.json();
    return data.payments || [];
  } catch {
    return [];
  }
}

// ── EarningsCard ──────────────────────────────────────────────────────────────

interface EarningsCardProps {
  agentId?: string;
  /** Poll interval in ms — default 30 000 (30 s) */
  pollInterval?: number;
  className?: string;
}

export function EarningsCard({ agentId, pollInterval = 30_000, className }: EarningsCardProps) {
  const [summary, setSummary] = useState<EarningsSummary | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [s, p] = await Promise.all([fetchSummary(agentId), fetchRecentPayments(agentId)]);
      if (s) setSummary(s);
      setPayments(p);
      setLastUpdated(new Date());
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  // Initial load + polling
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, pollInterval);
    return () => clearInterval(id);
  }, [refresh, pollInterval]);

  // Listen for custom payment events (dispatched by webhook handler proxy)
  useEffect(() => {
    const handler = () => refresh();
    window.addEventListener('payment:received', handler);
    return () => window.removeEventListener('payment:received', handler);
  }, [refresh]);

  const totalUsd = summary?.total_usd ?? 0;
  const recent24h = summary?.recent_24h_usd ?? 0;
  const recent7d = summary?.recent_7d_usd ?? 0;
  const bySource = summary?.by_source ?? {};
  const paymentCount = summary?.payment_count ?? 0;

  return (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Header */}
      <div className="px-3 pt-3 pb-2 border-b border-border flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-3.5 h-3.5 text-success" />
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wider">
              Agent Earnings
            </p>
          </div>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            title="Refresh earnings"
            className="p-1 rounded text-text-muted hover:text-text transition-colors disabled:opacity-40"
          >
            <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
          </button>
        </div>
        {lastUpdated && (
          <p className="text-xs text-text-muted/60 mt-1">
            Updated {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </p>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
        {loading && !summary ? (
          <div className="flex flex-col items-center gap-3 py-8">
            <Loader2 className="w-5 h-5 text-primary animate-spin" />
            <p className="text-xs text-text-muted">Loading earnings…</p>
          </div>
        ) : (
          <>
            {/* Total earnings hero */}
            <div className="rounded-xl bg-success/10 border border-success/20 p-3 text-center">
              <p className="text-xs text-text-muted mb-0.5">Total Earnings</p>
              <p className="text-2xl font-bold text-success tabular-nums">
                {fmtUsd(totalUsd)}
              </p>
              <p className="text-xs text-text-muted/60 mt-0.5">
                {paymentCount} payment{paymentCount !== 1 ? 's' : ''}
              </p>
            </div>

            {/* 24h / 7d row */}
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg bg-surface border border-border p-2 text-center">
                <p className="text-xs text-text-muted/70 mb-0.5">24h</p>
                <p className={cn('text-sm font-semibold tabular-nums', recent24h > 0 ? 'text-success' : 'text-text-muted')}>
                  {fmtUsd(recent24h)}
                </p>
              </div>
              <div className="rounded-lg bg-surface border border-border p-2 text-center">
                <p className="text-xs text-text-muted/70 mb-0.5">7d</p>
                <p className={cn('text-sm font-semibold tabular-nums', recent7d > 0 ? 'text-success' : 'text-text-muted')}>
                  {fmtUsd(recent7d)}
                </p>
              </div>
            </div>

            {/* By source breakdown */}
            {Object.keys(bySource).length > 0 && (
              <div className="flex flex-col gap-1">
                <p className="text-xs text-text-muted/60 uppercase tracking-wider font-medium">
                  By source
                </p>
                {Object.entries(bySource).map(([source, amount]) => (
                  <div key={source} className="flex items-center justify-between py-1 px-2 rounded-lg hover:bg-surface transition-colors">
                    <div className={cn('flex items-center gap-1.5 text-xs capitalize', SOURCE_COLORS[source] ?? 'text-text-muted')}>
                      {SOURCE_ICONS[source] ?? <Zap className="w-3 h-3" />}
                      {source}
                    </div>
                    <span className="text-xs font-medium text-text tabular-nums">
                      {fmtUsd(amount)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Recent payments */}
            {payments.length > 0 ? (
              <div className="flex flex-col gap-1">
                <p className="text-xs text-text-muted/60 uppercase tracking-wider font-medium">
                  Recent
                </p>
                {payments.slice(0, 6).map((p) => (
                  <div
                    key={p.id}
                    className="flex items-start justify-between py-1.5 px-2 rounded-lg hover:bg-surface transition-colors"
                  >
                    <div className="flex flex-col min-w-0">
                      <span className="text-xs text-text truncate">
                        {p.description || p.source}
                      </span>
                      <span className="text-xs text-text-muted/60">
                        {fmtTime(p.created_at)}
                      </span>
                    </div>
                    <span className={cn('text-xs font-semibold tabular-nums flex-shrink-0 ml-2', 'text-success')}>
                      +{fmtUsd(p.amount_usd)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 py-6 text-center">
                <div className="w-9 h-9 rounded-xl bg-surface border border-border flex items-center justify-center">
                  <DollarSign className="w-4 h-4 text-text-muted/40" />
                </div>
                <p className="text-xs text-text-muted">No payments yet</p>
                <p className="text-xs text-text-muted/60">
                  Payments will appear here when agents receive them
                </p>
              </div>
            )}

            {/* Link to full payment history */}
            {payments.length > 0 && (
              <button
                type="button"
                className="flex items-center justify-center gap-1 text-xs text-primary hover:text-accent transition-colors py-1"
                onClick={() => {
                  // Could navigate to a full payments page
                  window.open('/api/payments/list', '_blank');
                }}
              >
                View all payments
                <ArrowUpRight className="w-3 h-3" />
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
