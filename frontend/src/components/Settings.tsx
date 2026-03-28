'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  Eye,
  EyeOff,
  Save,
  CheckCircle,
  XCircle,
  Loader2,
  Cpu,
  Globe,
  ShieldCheck,
  Key,
  Zap,
  ChevronDown,
  RefreshCw,
} from 'lucide-react';
import { useStore } from '@/lib/store';
import { testOllamaConnection } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { Settings as SettingsType } from '@/lib/types';

// ============================================================
// Form helpers
// ============================================================

interface SectionProps {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  defaultOpen?: boolean;
}

function Section({ title, icon: Icon, children, defaultOpen = true }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 p-3.5 hover:bg-surface-elevated transition-colors"
      >
        <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
          <Icon className="w-3.5 h-3.5 text-primary" />
        </div>
        <span className="text-sm font-semibold text-text flex-1 text-left">{title}</span>
        <ChevronDown
          className={cn('w-4 h-4 text-text-muted transition-transform', open && 'rotate-180')}
        />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="p-4 pt-0 border-t border-border flex flex-col gap-4">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

interface ToggleProps {
  label: string;
  description?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}

function Toggle({ label, description, value, onChange }: ToggleProps) {
  return (
    <label className="flex items-center gap-3 cursor-pointer group">
      <div className="flex-1 min-w-0">
        <p className="text-sm text-text">{label}</p>
        {description && <p className="text-xs text-text-muted mt-0.5">{description}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        onClick={() => onChange(!value)}
        className={cn(
          'relative w-10 h-[22px] rounded-full transition-colors flex-shrink-0',
          'border',
          value ? 'bg-primary border-primary/50' : 'bg-surface-overlay border-border'
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200',
            value ? 'translate-x-5' : 'translate-x-0.5'
          )}
        />
      </button>
    </label>
  );
}

interface SecretInputProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  description?: string;
}

function SecretInput({ label, value, onChange, placeholder, description }: SecretInputProps) {
  const [show, setShow] = useState(false);
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm text-text font-medium">{label}</label>
      {description && <p className="text-xs text-text-muted -mt-0.5">{description}</p>}
      <div className="relative">
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 pr-10 text-sm text-text placeholder:text-text-muted/50 focus:outline-none focus:border-primary/50 transition-colors"
        />
        <button
          type="button"
          onClick={() => setShow(!show)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text transition-colors"
        >
          {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );
}

interface TextInputProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  description?: string;
}

function TextInput({ label, value, onChange, placeholder, description }: TextInputProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm text-text font-medium">{label}</label>
      {description && <p className="text-xs text-text-muted -mt-0.5">{description}</p>}
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm text-text placeholder:text-text-muted/50 focus:outline-none focus:border-primary/50 transition-colors"
      />
    </div>
  );
}

interface NumberInputProps {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  description?: string;
}

function NumberInput({ label, value, onChange, min, max, step = 1, description }: NumberInputProps) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <p className="text-sm text-text">{label}</p>
        {description && <p className="text-xs text-text-muted mt-0.5">{description}</p>}
      </div>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        className="w-24 rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text text-right focus:outline-none focus:border-primary/50 transition-colors"
      />
    </div>
  );
}

// ============================================================
// Main Settings panel
// ============================================================

interface SettingsProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsPanel({ open, onClose }: SettingsProps) {
  const storeSettings = useStore((s) => s.settings);
  const setSettings = useStore((s) => s.setSettings);
  const addToast = useStore((s) => s.addToast);

  const [local, setLocal] = useState<SettingsType>(storeSettings);
  const [saved, setSaved] = useState(false);

  const [ollamaStatus, setOllamaStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);

  // Sync when store changes
  useEffect(() => {
    if (open) setLocal(storeSettings);
  }, [open, storeSettings]);

  function update<K extends keyof SettingsType>(key: K, value: SettingsType[K]) {
    setLocal((prev) => ({ ...prev, [key]: value }));
  }

  function handleSave() {
    setSettings(local);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
    addToast({ type: 'success', title: 'Settings saved', message: 'Changes applied successfully.' });
  }

  async function handleTestOllama() {
    setOllamaStatus('testing');
    const result = await testOllamaConnection(local.ollamaUrl);
    setOllamaStatus(result.ok ? 'ok' : 'fail');
    setOllamaModels(result.models);
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
          />

          {/* Drawer */}
          <motion.div
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 350, damping: 32 }}
            className="fixed right-0 top-0 bottom-0 z-50 w-full max-w-md flex flex-col bg-card border-l border-border shadow-2xl"
          >
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-border flex-shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-xl bg-primary/10 flex items-center justify-center">
                  <Key className="w-4 h-4 text-primary" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-text">Settings</h2>
                  <p className="text-xs text-text-muted">API keys, models & safety</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-2 rounded-xl text-text-muted hover:text-text hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
              {/* Model Provider */}
              <Section title="Model Provider" icon={Zap}>
                <SecretInput
                  label="OpenRouter API Key"
                  value={local.openrouterApiKey}
                  onChange={(v) => update('openrouterApiKey', v)}
                  placeholder="sk-or-v1-…"
                  description="Required for cloud model access. Get one at openrouter.ai"
                />
                <Toggle
                  label="Prefer Free Models"
                  description="Use free-tier models when possible to minimize cost"
                  value={local.preferFreeModels}
                  onChange={(v) => update('preferFreeModels', v)}
                />
                <NumberInput
                  label="Max budget per task (USD)"
                  value={local.maxBudgetUsd}
                  onChange={(v) => update('maxBudgetUsd', v)}
                  min={0}
                  max={100}
                  step={0.1}
                  description="Agent stops if this limit is reached"
                />
                <div className="flex flex-col gap-1.5">
                  <label className="text-sm text-text font-medium">Model override</label>
                  <p className="text-xs text-text-muted">Force a specific model or use auto-selection</p>
                  <select
                    value={local.modelOverride}
                    onChange={(e) => update('modelOverride', e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm text-text focus:outline-none focus:border-primary/50 transition-colors"
                  >
                    <option value="auto">Auto (recommended)</option>
                    <option value="openai/gpt-4o-mini">GPT-4o mini (cheap)</option>
                    <option value="openai/gpt-4o">GPT-4o</option>
                    <option value="anthropic/claude-3-5-haiku">Claude 3.5 Haiku</option>
                    <option value="anthropic/claude-3-5-sonnet">Claude 3.5 Sonnet</option>
                    <option value="google/gemini-flash-1.5">Gemini Flash 1.5 (free)</option>
                    <option value="meta-llama/llama-3.1-8b-instruct:free">Llama 3.1 8B (free)</option>
                    <option value="mistralai/mistral-7b-instruct:free">Mistral 7B (free)</option>
                  </select>
                </div>
              </Section>

              {/* Ollama */}
              <Section title="Local Models (Ollama)" icon={Cpu} defaultOpen={false}>
                <Toggle
                  label="Enable Ollama"
                  description="Use locally running Ollama models"
                  value={local.ollamaEnabled}
                  onChange={(v) => update('ollamaEnabled', v)}
                />
                {local.ollamaEnabled && (
                  <>
                    <TextInput
                      label="Ollama URL"
                      value={local.ollamaUrl}
                      onChange={(v) => update('ollamaUrl', v)}
                      placeholder="http://localhost:11434"
                    />
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={handleTestOllama}
                        disabled={ollamaStatus === 'testing'}
                        className={cn(
                          'flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium border transition-colors',
                          'border-border text-text-muted hover:text-text hover:border-border/80'
                        )}
                      >
                        {ollamaStatus === 'testing' ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <RefreshCw className="w-3.5 h-3.5" />
                        )}
                        Test connection
                      </button>
                      {ollamaStatus === 'ok' && (
                        <span className="flex items-center gap-1 text-xs text-success">
                          <CheckCircle className="w-3.5 h-3.5" />
                          Connected
                        </span>
                      )}
                      {ollamaStatus === 'fail' && (
                        <span className="flex items-center gap-1 text-xs text-error">
                          <XCircle className="w-3.5 h-3.5" />
                          Failed
                        </span>
                      )}
                    </div>
                    {ollamaModels.length > 0 && (
                      <div className="flex flex-col gap-1">
                        <p className="text-xs text-text-muted font-medium">Available models</p>
                        <div className="flex flex-wrap gap-1.5">
                          {ollamaModels.map((m) => (
                            <span
                              key={m}
                              className="text-xs px-2 py-0.5 rounded bg-surface-overlay border border-border font-mono text-text-muted"
                            >
                              {m}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </Section>

              {/* Web Tools */}
              <Section title="Web Tools" icon={Globe} defaultOpen={false}>
                <SecretInput
                  label="Hyperbrowser API Key"
                  value={local.hyperbrowserApiKey}
                  onChange={(v) => update('hyperbrowserApiKey', v)}
                  placeholder="hb-…"
                  description="For advanced browser automation. Get one at hyperbrowser.ai"
                />
                <Toggle
                  label="Fallback to basic scraping"
                  description="Use simple HTTP scraping if Hyperbrowser is unavailable"
                  value={local.fallbackToBasicScraping}
                  onChange={(v) => update('fallbackToBasicScraping', v)}
                />
              </Section>

              {/* Safety */}
              <Section title="Safety & Approvals" icon={ShieldCheck} defaultOpen={false}>
                <p className="text-xs text-text-muted">
                  Require human approval before the agent performs these actions.
                </p>
                <Toggle
                  label="Code execution"
                  description="Python scripts, shell commands"
                  value={local.requireApprovalCodeExec}
                  onChange={(v) => update('requireApprovalCodeExec', v)}
                />
                <Toggle
                  label="File system writes"
                  description="Creating or modifying files"
                  value={local.requireApprovalFileWrite}
                  onChange={(v) => update('requireApprovalFileWrite', v)}
                />
                <Toggle
                  label="Web requests"
                  description="HTTP requests to external URLs"
                  value={local.requireApprovalWebRequests}
                  onChange={(v) => update('requireApprovalWebRequests', v)}
                />
                <NumberInput
                  label="Max retries per step"
                  value={local.maxRetriesPerStep}
                  onChange={(v) => update('maxRetriesPerStep', Math.round(v))}
                  min={1}
                  max={5}
                  description="How many times to retry a failed step"
                />
              </Section>
            </div>

            {/* Footer */}
            <div className="flex-shrink-0 p-4 border-t border-border">
              <button
                type="button"
                onClick={handleSave}
                className={cn(
                  'w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm',
                  'transition-all duration-150',
                  saved
                    ? 'bg-success text-white'
                    : 'bg-primary hover:bg-primary-hover text-white shadow-glow-sm'
                )}
              >
                {saved ? (
                  <>
                    <CheckCircle className="w-4 h-4" />
                    Saved!
                  </>
                ) : (
                  <>
                    <Save className="w-4 h-4" />
                    Save Settings
                  </>
                )}
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
