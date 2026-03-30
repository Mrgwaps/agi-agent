import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import {
  type Settings,
  type TaskState,
  type AgentEvent,
  type CostSummary,
  type Toast,
  type ModelUsage,
  DEFAULT_SETTINGS,
  EventType,
} from './types';

// ============================================================
// Settings slice
// ============================================================

interface SettingsSlice {
  settings: Settings;
  setSettings: (partial: Partial<Settings>) => void;
}

// ============================================================
// Tasks slice
// ============================================================

interface TasksSlice {
  tasks: Record<string, TaskState>;
  currentTaskId: string | null;
  addTask: (task: TaskState) => void;
  updateTask: (taskId: string, partial: Partial<TaskState>) => void;
  setCurrentTask: (taskId: string | null) => void;
  removeTask: (taskId: string) => void;
}

// ============================================================
// Events slice
// ============================================================

interface EventsSlice {
  events: Record<string, AgentEvent[]>;
  addEvent: (taskId: string, event: AgentEvent) => void;
  clearEvents: (taskId: string) => void;
}

// ============================================================
// Cost slice
// ============================================================

interface CostSlice {
  costSummary: Record<string, CostSummary>;
  updateCost: (taskId: string, event: AgentEvent) => void;
  resetCost: (taskId: string) => void;
}

// ============================================================
// Toast slice
// ============================================================

interface ToastSlice {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
}

// ============================================================
// Combined store
// ============================================================

type StoreState = SettingsSlice & TasksSlice & EventsSlice & CostSlice & ToastSlice;

function createEmptyCostSummary(budgetLimitUsd?: number): CostSummary {
  return {
    totalCost: 0,
    freeModelCalls: 0,
    paidModelCalls: 0,
    freeModelSavingsUsd: 0,
    modelBreakdown: [],
    budgetLimitUsd,
  };
}

function updateModelBreakdown(
  breakdown: ModelUsage[],
  model: string,
  inputTokens: number,
  outputTokens: number,
  costUsd: number,
  isFree: boolean
): ModelUsage[] {
  const existing = breakdown.find((m) => m.model === model);
  if (existing) {
    return breakdown.map((m) =>
      m.model === model
        ? {
            ...m,
            calls: m.calls + 1,
            inputTokens: m.inputTokens + inputTokens,
            outputTokens: m.outputTokens + outputTokens,
            totalCostUsd: m.totalCostUsd + costUsd,
          }
        : m
    );
  }
  return [
    ...breakdown,
    {
      model,
      calls: 1,
      inputTokens,
      outputTokens,
      totalCostUsd: costUsd,
      isFree,
    },
  ];
}

export const useStore = create<StoreState>()(
  persist(
    (set, get) => ({
      // ---- Settings ----
      settings: DEFAULT_SETTINGS,
      setSettings: (partial) =>
        set((state) => ({ settings: { ...state.settings, ...partial } })),

      // ---- Tasks ----
      tasks: {},
      currentTaskId: null,
      addTask: (task) =>
        set((state) => ({
          tasks: { ...state.tasks, [task.id]: task },
          currentTaskId: task.id,
        })),
      updateTask: (taskId, partial) =>
        set((state) => {
          const existing = state.tasks[taskId];
          if (!existing) return state;
          return {
            tasks: {
              ...state.tasks,
              [taskId]: { ...existing, ...partial },
            },
          };
        }),
      setCurrentTask: (taskId) => set({ currentTaskId: taskId }),
      removeTask: (taskId) =>
        set((state) => {
          const { [taskId]: _, ...rest } = state.tasks;
          const { [taskId]: _e, ...restEvents } = state.events;
          const { [taskId]: _c, ...restCosts } = state.costSummary;
          return {
            tasks: rest,
            events: restEvents,
            costSummary: restCosts,
            currentTaskId:
              state.currentTaskId === taskId ? null : state.currentTaskId,
          };
        }),

      // ---- Events ----
      events: {},
      addEvent: (taskId, event) =>
        set((state) => {
          const existing = state.events[taskId] || [];
          // Avoid duplicate event IDs
          if (existing.some((e) => e.id === event.id)) return state;
          return {
            events: {
              ...state.events,
              [taskId]: [...existing, event],
            },
          };
        }),
      clearEvents: (taskId) =>
        set((state) => ({
          events: { ...state.events, [taskId]: [] },
        })),

      // ---- Costs ----
      costSummary: {},
      updateCost: (taskId, event) => {
        if (event.type !== EventType.MODEL_CALL) return;
        const payload = event.payload as {
          model?: string;
          inputTokens?: number;
          outputTokens?: number;
          costUsd?: number;
          isFree?: boolean;
          estimatedPaidCostUsd?: number;
        };
        const model = payload.model || event.model || 'unknown';
        const inputTokens = payload.inputTokens || 0;
        const outputTokens = payload.outputTokens || 0;
        const costUsd = payload.costUsd || event.costUsd || 0;
        const isFree = payload.isFree ?? false;
        const estimatedPaidCost = payload.estimatedPaidCostUsd || 0;

        set((state) => {
          const settings = state.settings;
          const current =
            state.costSummary[taskId] ||
            createEmptyCostSummary(settings.maxBudgetUsd);
          return {
            costSummary: {
              ...state.costSummary,
              [taskId]: {
                ...current,
                totalCost: current.totalCost + costUsd,
                freeModelCalls: isFree
                  ? current.freeModelCalls + 1
                  : current.freeModelCalls,
                paidModelCalls: !isFree
                  ? current.paidModelCalls + 1
                  : current.paidModelCalls,
                freeModelSavingsUsd:
                  current.freeModelSavingsUsd + (isFree ? estimatedPaidCost : 0),
                modelBreakdown: updateModelBreakdown(
                  current.modelBreakdown,
                  model,
                  inputTokens,
                  outputTokens,
                  costUsd,
                  isFree
                ),
              },
            },
          };
        });

        // Also update task total cost
        get().updateTask(taskId, {
          totalCostUsd:
            (get().tasks[taskId]?.totalCostUsd || 0) + costUsd,
        });
      },
      resetCost: (taskId) =>
        set((state) => ({
          costSummary: {
            ...state.costSummary,
            [taskId]: createEmptyCostSummary(state.settings.maxBudgetUsd),
          },
        })),

      // ---- Toasts ----
      toasts: [],
      addToast: (toast) =>
        set((state) => ({
          toasts: [
            ...state.toasts,
            { ...toast, id: `toast-${Date.now()}-${Math.random()}` },
          ],
        })),
      removeToast: (id) =>
        set((state) => ({
          toasts: state.toasts.filter((t) => t.id !== id),
        })),
    }),
    {
      name: 'agi-agent-storage',
      storage: createJSONStorage(() =>
        typeof window !== 'undefined' ? localStorage : { getItem: () => null, setItem: () => {}, removeItem: () => {} }
      ),
      partialize: (state) => ({
        settings: state.settings,
        // Persist tasks and events so they survive refreshes
        tasks: state.tasks,
        events: state.events,
        costSummary: state.costSummary,
      }),
      // Prevent SSR/client mismatch: server and first client render both use
      // default state. StoreHydration component triggers rehydration after mount.
      skipHydration: true,
    }
  )
);
