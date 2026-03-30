'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  Zap,
  RefreshCw,
  TrendingUp,
  Code,
  Globe,
  PenTool,
  Database,
  Mail,
  DollarSign,
  Loader2,
  ChevronRight,
  BookOpen,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Skill {
  id: number;
  name: string;
  title: string;
  category: string;
  description: string;
  revenue_potential: string;
  complexity: string;
  tags: string;
  success_rate: number;
  use_count: number;
  updated_at: number;
}

interface SkillStats {
  total_skills: number;
  active_skills: number;
  by_category: Record<string, number>;
  by_revenue_potential: Record<string, number>;
  top_skills: Skill[];
  last_research_session: {
    query: string;
    skills_found: number;
    skills_added: number;
    model_used: string;
    ran_at: number;
  } | null;
}

interface ResearchStatus {
  running: boolean;
  cycles_completed: number;
  last_cycle: {
    topic: string;
    skills_added: number;
    skills_updated: number;
    skills_purged: number;
    model_used: string;
    elapsed_seconds: number;
    timestamp: number;
  } | null;
  db_stats: SkillStats;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const REVENUE_COLORS: Record<string, string> = {
  very_high: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30',
  high:      'text-green-400 bg-green-400/10 border-green-400/30',
  medium:    'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
  low:       'text-blue-400 bg-blue-400/10 border-blue-400/30',
  none:      'text-text-muted bg-surface border-border',
};

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  revenue:       <DollarSign className="w-3 h-3" />,
  automation:    <Zap className="w-3 h-3" />,
  research:      <Globe className="w-3 h-3" />,
  writing:       <PenTool className="w-3 h-3" />,
  coding:        <Code className="w-3 h-3" />,
  communication: <Mail className="w-3 h-3" />,
  data:          <Database className="w-3 h-3" />,
  general:       <BookOpen className="w-3 h-3" />,
};

function fmtRevenue(r: string): string {
  return { very_high: 'Very High', high: 'High', medium: 'Medium', low: 'Low', none: 'None' }[r] ?? r;
}

function fmtTime(ts: number): string {
  const diff = Math.floor(Date.now() / 1000 - ts);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ── SkillsPanel ───────────────────────────────────────────────────────────────

interface SkillsPanelProps {
  className?: string;
  pollInterval?: number;
}

export function SkillsPanel({ className, pollInterval = 60_000 }: SkillsPanelProps) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [status, setStatus] = useState<ResearchStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [skillsRes, statusRes] = await Promise.all([
        fetch(`/api/skills?limit=50${selectedCategory ? `&category=${selectedCategory}` : ''}`),
        fetch('/api/skills/research/status'),
      ]);
      if (skillsRes.ok) {
        const d = await skillsRes.json();
        setSkills(d.skills ?? []);
      }
      if (statusRes.ok) {
        setStatus(await statusRes.json());
      }
      setLastUpdated(new Date());
    } finally {
      setLoading(false);
    }
  }, [selectedCategory]);

  const triggerResearch = async () => {
    setTriggering(true);
    try {
      await fetch('/api/skills/research/trigger', { method: 'POST' });
      setTimeout(refresh, 3000);
    } finally {
      setTimeout(() => setTriggering(false), 3000);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, pollInterval);
    return () => clearInterval(id);
  }, [refresh, pollInterval]);

  const stats = status?.db_stats;
  const categories = Object.keys(stats?.by_category ?? {});

  return (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Header */}
      <div className="px-3 pt-3 pb-2 border-b border-border flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="w-3.5 h-3.5 text-primary" />
            <p className="text-xs font-semibold text-text-muted uppercase tracking-wider">
              Agent Superpowers
            </p>
            {stats && (
              <span className="text-xs bg-primary/15 text-primary border border-primary/30 px-1.5 py-0.5 rounded-full font-medium">
                {stats.active_skills}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={triggerResearch}
              disabled={triggering}
              title="Research new skills now"
              className="p-1 rounded text-text-muted hover:text-primary transition-colors disabled:opacity-40"
            >
              <TrendingUp className={cn('w-3 h-3', triggering && 'animate-pulse text-primary')} />
            </button>
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              title="Refresh"
              className="p-1 rounded text-text-muted hover:text-text transition-colors disabled:opacity-40"
            >
              <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
            </button>
          </div>
        </div>

        {/* Research status */}
        {status?.last_cycle && (
          <p className="text-xs text-text-muted/60 mt-1">
            Last research: {fmtTime(status.last_cycle.timestamp)} · +{status.last_cycle.skills_added} added
            {status.cycles_completed > 0 && ` · ${status.cycles_completed} cycles`}
          </p>
        )}

        {/* Category filter */}
        {categories.length > 0 && (
          <div className="flex gap-1 flex-wrap mt-2">
            <button
              type="button"
              onClick={() => setSelectedCategory('')}
              className={cn(
                'text-xs px-2 py-0.5 rounded-full border transition-colors',
                !selectedCategory
                  ? 'bg-primary/15 text-primary border-primary/30'
                  : 'text-text-muted border-border hover:border-border/80'
              )}
            >
              All
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setSelectedCategory(cat === selectedCategory ? '' : cat)}
                className={cn(
                  'text-xs px-2 py-0.5 rounded-full border transition-colors capitalize',
                  selectedCategory === cat
                    ? 'bg-primary/15 text-primary border-primary/30'
                    : 'text-text-muted border-border hover:border-border/80'
                )}
              >
                {cat}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-1.5">
        {loading && skills.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-8">
            <Loader2 className="w-5 h-5 text-primary animate-spin" />
            <p className="text-xs text-text-muted">Loading skills…</p>
          </div>
        ) : skills.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center px-4">
            <div className="w-9 h-9 rounded-xl bg-surface border border-border flex items-center justify-center">
              <Zap className="w-4 h-4 text-text-muted/40" />
            </div>
            <p className="text-xs text-text-muted">No skills yet</p>
            <p className="text-xs text-text-muted/60">
              Click the research button to discover agent superpowers
            </p>
            <button
              type="button"
              onClick={triggerResearch}
              className="mt-1 text-xs bg-primary text-white px-3 py-1.5 rounded-lg hover:bg-primary/90 transition-colors"
            >
              Start Research
            </button>
          </div>
        ) : (
          skills.map((skill) => (
            <div
              key={skill.id}
              className="p-2.5 rounded-xl border border-border hover:border-border/60 hover:bg-surface transition-all cursor-default"
            >
              <div className="flex items-start gap-2">
                <div className="flex-shrink-0 mt-0.5 text-text-muted/60">
                  {CATEGORY_ICONS[skill.category] ?? <Zap className="w-3 h-3" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <p className="text-xs font-semibold text-text truncate">{skill.title}</p>
                    <span className={cn(
                      'text-xs px-1.5 py-0.5 rounded-full border font-medium flex-shrink-0',
                      REVENUE_COLORS[skill.revenue_potential] ?? REVENUE_COLORS.none,
                    )}>
                      {fmtRevenue(skill.revenue_potential)}
                    </span>
                  </div>
                  <p className="text-xs text-text-muted/80 mt-0.5 line-clamp-2">{skill.description}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs text-text-muted/50 capitalize">{skill.complexity}</span>
                    {skill.success_rate > 0 && (
                      <span className="text-xs text-text-muted/50">
                        {Math.round(skill.success_rate * 100)}% success
                      </span>
                    )}
                    {skill.use_count > 0 && (
                      <span className="text-xs text-text-muted/50">
                        {skill.use_count}× used
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Footer stats */}
      {stats && (
        <div className="flex-shrink-0 border-t border-border px-3 py-2 flex items-center justify-between">
          <p className="text-xs text-text-muted/60">
            {stats.active_skills} active · {stats.total_skills} total
          </p>
          <div className="flex gap-2">
            {Object.entries(stats.by_revenue_potential ?? {})
              .filter(([k]) => k !== 'none')
              .slice(0, 2)
              .map(([k, n]) => (
                <span key={k} className="text-xs text-text-muted/50">
                  {fmtRevenue(k)}: {n}
                </span>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
