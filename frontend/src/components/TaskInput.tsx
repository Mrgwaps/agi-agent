'use client';

import React, { useState, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  BrainCircuit,
  Globe,
  FolderOpen,
  Code2,
  Cpu,
  DollarSign,
  Send,
  Loader2,
  Sparkles,
  ChevronDown,
  Mic,
  MicOff,
  Square,
} from 'lucide-react';
import { useStore } from '@/lib/store';
import { createTask } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { TaskConstraints } from '@/lib/types';
import { useVoice } from '@/hooks/useVoice';

const DEMO_TASKS = [
  {
    label: 'Research & Report',
    goal: 'Research the latest developments in quantum computing in 2024 and write a comprehensive summary report with key findings, major players, and future outlook.',
    icon: '🔬',
  },
  {
    label: 'Code & Analyze',
    goal: 'Write a Python script that analyzes stock market trends using the Fibonacci sequence, then explain the mathematical relationships found in the data.',
    icon: '📊',
  },
  {
    label: 'Plan & Execute',
    goal: 'Create a detailed 30-day content marketing plan for a B2B SaaS product targeting developers, including post ideas, channels, and engagement strategies.',
    icon: '🚀',
  },
];

interface ConstraintToggleProps {
  label: string;
  icon: React.ReactNode;
  enabled: boolean;
  onToggle: () => void;
  description: string;
}

function ConstraintToggle({ label, icon, enabled, onToggle, description }: ConstraintToggleProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      title={description}
      className={cn(
        'flex items-center gap-2 px-3 py-2 rounded-lg border text-sm font-medium transition-all duration-150 select-none',
        enabled
          ? 'bg-primary/15 border-primary/50 text-accent shadow-glow-sm'
          : 'bg-surface border-border text-text-muted hover:border-border/80 hover:text-text'
      )}
    >
      {icon}
      <span className="text-xs">{label}</span>
      <div
        className={cn(
          'w-2 h-2 rounded-full ml-auto transition-colors',
          enabled ? 'bg-primary' : 'bg-surface-overlay'
        )}
      />
    </button>
  );
}

interface TaskInputProps {
  onTaskCreated?: (taskId: string) => void;
}

export function TaskInput({ onTaskCreated }: TaskInputProps) {
  const settings = useStore((s) => s.settings);
  const addTask = useStore((s) => s.addTask);
  const addToast = useStore((s) => s.addToast);

  const [goal, setGoal] = useState('');
  const [mode, setMode] = useState<'auto' | 'interactive'>('auto');
  const [loading, setLoading] = useState(false);
  const [focused, setFocused] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [constraints, setConstraints] = useState<TaskConstraints>({
    allowWeb: true,
    allowFileSystem: false,
    allowCodeExecution: false,
    allowOllama: settings.ollamaEnabled,
    maxBudgetUsd: settings.maxBudgetUsd,
    maxSteps: 10,
    requireApprovalFor: [],
  });

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Voice / STT
  const { isSupported: voiceSupported, isListening, startListening, stopListening, interimTranscript, error: voiceError } = useVoice({
    onTranscriptChange: (text) => {
      setGoal(text);
      // Auto-resize textarea
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
        textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 240)}px`;
      }
    },
  });

  function toggleConstraint(key: keyof TaskConstraints) {
    setConstraints((prev) => ({
      ...prev,
      [key]: !prev[key as 'allowWeb'],
    }));
  }

  function selectDemo(demo: typeof DEMO_TASKS[number]) {
    setGoal(demo.goal);
    textareaRef.current?.focus();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!goal.trim() || loading) return;

    setLoading(true);
    try {
      const task = await createTask(goal.trim(), constraints, mode);
      addTask(task);
      setGoal('');
      onTaskCreated?.(task.id);
      addToast({ type: 'success', title: 'Task created', message: 'Agent is starting…' });
    } catch (err) {
      addToast({
        type: 'error',
        title: 'Failed to create task',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setLoading(false);
    }
  }

  function handleTextareaInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setGoal(e.target.value);
    // Auto-resize
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 240)}px`;
  }

  return (
    <div className="flex flex-col gap-6 max-w-2xl w-full mx-auto">
      {/* Title */}
      <div className="text-center">
        <div className="flex justify-center mb-3">
          <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/30 flex items-center justify-center shadow-glow-md">
            <BrainCircuit className="w-7 h-7 text-primary" />
          </div>
        </div>
        <h1 className="text-2xl font-bold text-text tracking-tight">AGI Agent Console</h1>
        <p className="text-text-muted text-sm mt-1.5">
          Describe a goal. The agent will plan, reason, and execute autonomously.
        </p>
      </div>

      {/* Demo task buttons */}
      <div className="flex flex-col gap-2">
        <p className="text-xs text-text-muted font-medium uppercase tracking-wider px-1">
          Example tasks
        </p>
        <div className="grid grid-cols-1 gap-2">
          {DEMO_TASKS.map((demo) => (
            <motion.button
              key={demo.label}
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              type="button"
              onClick={() => selectDemo(demo)}
              className={cn(
                'flex items-start gap-3 p-3.5 rounded-xl border text-left transition-all',
                'bg-surface border-border hover:border-primary/40 hover:bg-primary/5 group'
              )}
            >
              <span className="text-xl leading-none mt-0.5">{demo.icon}</span>
              <div>
                <p className="text-sm font-semibold text-text group-hover:text-accent transition-colors">
                  {demo.label}
                </p>
                <p className="text-xs text-text-muted mt-0.5 line-clamp-1">{demo.goal}</p>
              </div>
            </motion.button>
          ))}
        </div>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {/* Goal textarea */}
        <div className="relative">
          <textarea
            ref={textareaRef}
            value={goal}
            onChange={handleTextareaInput}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder={isListening ? 'Listening… speak your goal now' : 'Describe your goal in detail…\n\nThe agent will create a plan, use tools, and work autonomously to achieve it.'}
            rows={5}
            disabled={loading}
            className={cn(
              'w-full resize-none rounded-xl border bg-surface p-4 text-sm text-text',
              'placeholder:text-text-muted/50 leading-relaxed transition-all duration-200',
              'focus-glow',
              focused && 'border-primary/50',
              !focused && 'border-border',
              loading && 'opacity-50 cursor-not-allowed',
              voiceSupported && 'pb-10', // make room for mic button
              isListening && 'border-red-400/60 ring-1 ring-red-400/30'
            )}
          />

          {/* Mic button — bottom-left inside textarea */}
          {voiceSupported && !loading && (
            <button
              type="button"
              onClick={isListening ? stopListening : startListening}
              title={isListening ? 'Stop listening' : 'Start voice input'}
              className={cn(
                'absolute bottom-3 left-3 flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs transition-all duration-150',
                isListening
                  ? 'text-red-400 bg-red-500/10 border border-red-400/30 animate-pulse'
                  : 'text-text-muted hover:text-text hover:bg-surface-overlay border border-transparent'
              )}
            >
              {isListening ? (
                <>
                  <Square className="w-3 h-3" />
                  <span>Stop</span>
                </>
              ) : (
                <>
                  <Mic className="w-3 h-3" />
                  <span>Speak</span>
                </>
              )}
            </button>
          )}

          {/* Interim transcript hint */}
          {isListening && interimTranscript && (
            <div className="absolute bottom-10 left-3 right-10 text-xs text-text-muted/60 italic truncate pointer-events-none">
              {interimTranscript}
            </div>
          )}

          {/* Character count */}
          {goal.length > 0 && !isListening && (
            <div className="absolute bottom-3 right-3 text-xs text-text-muted">
              {goal.length}
            </div>
          )}
        </div>

        {/* Voice error */}
        {voiceError && (
          <p className="text-xs text-error px-1">{voiceError}</p>
        )}

        {/* Mode selector */}
        <div className="flex gap-2">
          {(['auto', 'interactive'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={cn(
                'flex-1 py-2 rounded-lg border text-sm font-medium capitalize transition-all',
                mode === m
                  ? 'bg-primary/15 border-primary/50 text-accent'
                  : 'bg-surface border-border text-text-muted hover:text-text hover:border-border'
              )}
            >
              {m === 'auto' ? '⚡ Auto' : '🤝 Interactive'}
            </button>
          ))}
        </div>

        {/* Constraint toggles */}
        <div>
          <p className="text-xs text-text-muted font-medium uppercase tracking-wider mb-2">
            Capabilities
          </p>
          <div className="grid grid-cols-2 gap-2">
            <ConstraintToggle
              label="Web Access"
              icon={<Globe className="w-3.5 h-3.5" />}
              enabled={constraints.allowWeb}
              onToggle={() => toggleConstraint('allowWeb')}
              description="Allow the agent to browse and search the web"
            />
            <ConstraintToggle
              label="File System"
              icon={<FolderOpen className="w-3.5 h-3.5" />}
              enabled={constraints.allowFileSystem}
              onToggle={() => toggleConstraint('allowFileSystem')}
              description="Allow reading/writing local files"
            />
            <ConstraintToggle
              label="Code Execution"
              icon={<Code2 className="w-3.5 h-3.5" />}
              enabled={constraints.allowCodeExecution}
              onToggle={() => toggleConstraint('allowCodeExecution')}
              description="Allow running Python/shell code"
            />
            <ConstraintToggle
              label="Ollama (Local)"
              icon={<Cpu className="w-3.5 h-3.5" />}
              enabled={constraints.allowOllama}
              onToggle={() => toggleConstraint('allowOllama')}
              description="Use local Ollama models"
            />
          </div>
        </div>

        {/* Advanced / Budget */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text transition-colors"
          >
            <ChevronDown
              className={cn('w-3.5 h-3.5 transition-transform', showAdvanced && 'rotate-180')}
            />
            Advanced options
          </button>
          {showAdvanced && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-3 flex flex-col gap-3"
            >
              <div className="flex items-center gap-3">
                <label className="text-sm text-text-muted flex items-center gap-2 flex-shrink-0">
                  <DollarSign className="w-4 h-4 text-warning" />
                  Budget limit (USD)
                </label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={constraints.maxBudgetUsd}
                  onChange={(e) =>
                    setConstraints((prev) => ({
                      ...prev,
                      maxBudgetUsd: parseFloat(e.target.value) || 0,
                    }))
                  }
                  className="w-24 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-primary/50"
                />
              </div>
              <div className="flex items-center gap-3">
                <label className="text-sm text-text-muted flex-shrink-0">Max steps</label>
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={constraints.maxSteps}
                  onChange={(e) =>
                    setConstraints((prev) => ({
                      ...prev,
                      maxSteps: parseInt(e.target.value) || 10,
                    }))
                  }
                  className="w-24 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:outline-none focus:border-primary/50"
                />
              </div>
            </motion.div>
          )}
        </div>

        {/* Submit */}
        <motion.button
          type="submit"
          disabled={!goal.trim() || loading}
          whileHover={{ scale: goal.trim() && !loading ? 1.01 : 1 }}
          whileTap={{ scale: goal.trim() && !loading ? 0.99 : 1 }}
          className={cn(
            'flex items-center justify-center gap-2.5 px-6 py-3.5 rounded-xl',
            'font-semibold text-sm transition-all duration-150 shadow-glow-sm',
            goal.trim() && !loading
              ? 'bg-primary hover:bg-primary-hover text-white cursor-pointer'
              : 'bg-surface border border-border text-text-muted cursor-not-allowed opacity-60'
          )}
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Creating task…
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4" />
              Launch Agent
              <Send className="w-4 h-4" />
            </>
          )}
        </motion.button>
      </form>
    </div>
  );
}
