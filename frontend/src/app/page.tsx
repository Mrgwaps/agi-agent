'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BrainCircuit, Settings, DollarSign, Activity, TrendingUp } from 'lucide-react';
import { useStore } from '@/lib/store';
import { TaskSidebar } from '@/components/TaskSidebar';
import { TaskInput } from '@/components/TaskInput';
import { TaskView } from '@/components/TaskView';
import { CostTracker } from '@/components/CostTracker';
import { EarningsCard } from '@/components/EarningsCard';
import { SettingsPanel } from '@/components/Settings';
import { ModelIndicator } from '@/components/ModelIndicator';
import { VoicePlayer } from '@/components/VoicePlayer';
import { VoiceAvatar } from '@/components/VoiceAvatar';
import { useHeartbeat } from '@/hooks/useHeartbeat';
import { cn } from '@/lib/utils';

// ============================================================
// Right sidebar panel
// ============================================================

type RightPanel = 'cost' | 'earnings' | null;

// ============================================================
// Header
// ============================================================

function Header({
  currentTaskId,
  onOpenSettings,
  rightPanel,
  setRightPanel,
  voicePlayerSlot,
  avatarSlot,
}: {
  currentTaskId: string | null;
  onOpenSettings: () => void;
  rightPanel: RightPanel;
  setRightPanel: (p: RightPanel) => void;
  voicePlayerSlot?: React.ReactNode;
  avatarSlot?: React.ReactNode;
}) {
  return (
    <header className="flex-shrink-0 h-12 border-b border-border flex items-center px-4 gap-3 bg-card z-10">
      {/* Logo */}
      <div className="flex items-center gap-2 select-none flex-shrink-0">
        <div className="w-7 h-7 rounded-lg bg-primary/10 border border-primary/30 flex items-center justify-center">
          <BrainCircuit className="w-4 h-4 text-primary" />
        </div>
        <span className="text-sm font-bold text-text tracking-tight hidden sm:block">
          AGI Agent
        </span>
        <span className="text-xs text-text-muted hidden sm:block">Neural Interface</span>
      </div>

      <div className="flex-1 flex items-center justify-center">
        <ModelIndicator taskId={currentTaskId} />
      </div>

      {/* Right controls */}
      <div className="flex items-center gap-1.5 flex-shrink-0">
        {/* Voice player status/mute button */}
        {voicePlayerSlot}

        {/* Avatar toggle button */}
        {avatarSlot}

        <button
          onClick={() => setRightPanel(rightPanel === 'cost' ? null : 'cost')}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors',
            rightPanel === 'cost'
              ? 'bg-primary/15 text-accent border border-primary/30'
              : 'text-text-muted hover:text-text hover:bg-surface-elevated'
          )}
        >
          <DollarSign className="w-3.5 h-3.5" />
          <span className="hidden sm:block">Costs</span>
        </button>

        <button
          onClick={() => setRightPanel(rightPanel === 'earnings' ? null : 'earnings')}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors',
            rightPanel === 'earnings'
              ? 'bg-success/15 text-success border border-success/30'
              : 'text-text-muted hover:text-text hover:bg-surface-elevated'
          )}
        >
          <TrendingUp className="w-3.5 h-3.5" />
          <span className="hidden sm:block">Earnings</span>
        </button>

        <button
          onClick={onOpenSettings}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-text-muted hover:text-text hover:bg-surface-elevated transition-colors"
        >
          <Settings className="w-3.5 h-3.5" />
          <span className="hidden sm:block">Settings</span>
        </button>
      </div>
    </header>
  );
}

// ============================================================
// Main page
// ============================================================

export default function HomePage() {
  const currentTaskId = useStore((s) => s.currentTaskId);
  const setCurrentTask = useStore((s) => s.setCurrentTask);
  const settings = useStore((s) => s.settings);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [rightPanel, setRightPanel] = useState<RightPanel>('cost');
  const [showNewTask, setShowNewTask] = useState(false);

  // 30-minute intelligence heartbeat (runs silently, shows toasts)
  useHeartbeat();

  function handleNewTask() {
    setShowNewTask(true);
    setCurrentTask(null);
  }

  function handleTaskCreated(taskId: string) {
    setShowNewTask(false);
  }

  const showInput = !currentTaskId || showNewTask;
  const voiceActive = settings.voiceEnabled && !!settings.falApiKey;
  const avatarActive = settings.avatarEnabled;

  return (
    <div className="neural-bg flex flex-col h-screen overflow-hidden">
      {/* Header */}
      <Header
        currentTaskId={currentTaskId}
        onOpenSettings={() => setSettingsOpen(true)}
        rightPanel={rightPanel}
        setRightPanel={setRightPanel}
        voicePlayerSlot={
          voiceActive ? (
            <VoicePlayer
              taskId={currentTaskId}
              enabled={settings.voiceAutoPlay}
              voice={settings.voiceVoice}
            />
          ) : null
        }
        avatarSlot={
          avatarActive ? (
            <VoiceAvatar enabled={avatarActive} />
          ) : null
        }
      />

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar */}
        <TaskSidebar onNewTask={handleNewTask} />

        {/* Main content */}
        <main className="flex-1 overflow-hidden flex flex-col">
          <AnimatePresence mode="wait">
            {showInput ? (
              <motion.div
                key="input"
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -16 }}
                transition={{ duration: 0.25 }}
                className="flex-1 overflow-y-auto p-6 flex items-start justify-center"
              >
                <TaskInput onTaskCreated={handleTaskCreated} />
              </motion.div>
            ) : currentTaskId ? (
              <motion.div
                key={`task-${currentTaskId}`}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -16 }}
                transition={{ duration: 0.25 }}
                className="flex-1 overflow-hidden"
              >
                <TaskView taskId={currentTaskId} />
              </motion.div>
            ) : (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex-1 flex items-center justify-center"
              >
                <div className="flex flex-col items-center gap-4 text-text-muted">
                  <div className="w-16 h-16 rounded-2xl bg-surface border border-border flex items-center justify-center">
                    <Activity className="w-8 h-8 opacity-30" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-medium">No task selected</p>
                    <p className="text-xs mt-1">Create a new task to get started</p>
                  </div>
                  <button
                    onClick={handleNewTask}
                    className="px-4 py-2 rounded-xl bg-primary hover:bg-primary-hover text-white text-sm font-semibold transition-colors shadow-glow-sm"
                  >
                    Create Task
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </main>

        {/* Right panel */}
        <AnimatePresence>
          {rightPanel === 'cost' && (
            <motion.aside
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 240, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 350, damping: 32 }}
              className="flex-shrink-0 overflow-hidden border-l border-border bg-card"
            >
              <div className="w-60 h-full overflow-y-auto">
                <div className="px-3 pt-3 pb-1 border-b border-border">
                  <p className="text-xs font-semibold text-text-muted uppercase tracking-wider">
                    Cost Tracker
                  </p>
                </div>
                <CostTracker
                  taskId={currentTaskId}
                  onOpenSettings={() => setSettingsOpen(true)}
                />
              </div>
            </motion.aside>
          )}
          {rightPanel === 'earnings' && (
            <motion.aside
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 240, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 350, damping: 32 }}
              className="flex-shrink-0 overflow-hidden border-l border-border bg-card"
            >
              <div className="w-60 h-full overflow-y-auto">
                <EarningsCard pollInterval={30_000} />
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      </div>

      {/* Settings drawer */}
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
