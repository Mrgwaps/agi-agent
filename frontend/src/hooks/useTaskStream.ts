'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { streamEvents } from '@/lib/api';
import { useStore } from '@/lib/store';
import { type AgentEvent, type TaskStep, EventType, TaskStatus, StepStatus } from '@/lib/types';

interface UseTaskStreamResult {
  events: AgentEvent[];
  isConnected: boolean;
  error: string | null;
}

export function useTaskStream(taskId: string | null): UseTaskStreamResult {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  const addEvent = useStore((s) => s.addEvent);
  const updateTask = useStore((s) => s.updateTask);
  const updateCost = useStore((s) => s.updateCost);
  const addToast = useStore((s) => s.addToast);
  const getTasks = useStore.getState;

  const events = useStore((s) =>
    taskId ? (s.events[taskId] || []) : []
  );

  // Helper: find step index by step_id, fallback to currentStep
  function findStepIndex(taskId: string, stepId: string | undefined): number {
    const task = getTasks().tasks[taskId];
    if (!task?.plan || !stepId) return task?.currentStepIndex ?? 0;
    const idx = task.plan.findIndex((s) => s.id === stepId);
    return idx >= 0 ? idx : (task.currentStepIndex ?? 0);
  }

  const handleEvent = useCallback(
    (event: AgentEvent) => {
      if (!taskId) return;

      addEvent(taskId, event);
      updateCost(taskId, event);

      switch (event.type) {
        // ── Thinking: agent has started processing ──────────────────────────
        case EventType.THINKING: {
          updateTask(taskId, { status: TaskStatus.PLANNING });
          break;
        }

        // ── Task lifecycle ──────────────────────────────────────────────────
        case EventType.TASK_STARTED:
          updateTask(taskId, {
            status: TaskStatus.RUNNING,
            startedAt: event.timestamp,
          });
          break;

        case EventType.TASK_COMPLETED: {
          const resultPreview = event.payload.result as string | undefined;
          updateTask(taskId, {
            status: TaskStatus.COMPLETED,
            completedAt: event.timestamp,
            ...(resultPreview ? { result: resultPreview } : {}),
          });
          setIsConnected(false);
          // Only show toast for fresh completions, not page-reload replays
          const isReplayed = event.payload.replayed === true;
          if (!isReplayed) {
            addToast({
              type: 'success',
              title: 'Task completed',
              message: 'The agent finished successfully.',
            });
          }
          // Fetch the full result from the API (event only has 500-char preview)
          import('@/lib/api').then(({ getTask }) =>
            getTask(taskId).then((full) => {
              if (full.result) updateTask(taskId, { result: full.result });
            }).catch(() => {})
          );
          break;
        }

        case EventType.TASK_FAILED: {
          updateTask(taskId, {
            status: TaskStatus.FAILED,
            error: (event.payload.error as string) || 'Unknown error',
            completedAt: event.timestamp,
          });
          setIsConnected(false);
          if (event.payload.replayed !== true) {
            addToast({
              type: 'error',
              title: 'Task failed',
              message: (event.payload.error as string) || 'The agent encountered an error.',
            });
          }
          break;
        }

        case EventType.TASK_ABORTED:
          updateTask(taskId, {
            status: TaskStatus.ABORTED,
            completedAt: event.timestamp,
          });
          setIsConnected(false);
          break;

        // ── Plan created ────────────────────────────────────────────────────
        case EventType.PLAN_CREATED: {
          // normalizeEvent maps payload.steps → payload.plan (normalized TaskStep[])
          const plan = event.payload.plan as TaskStep[] | undefined;
          if (plan && plan.length > 0) {
            updateTask(taskId, { plan, status: TaskStatus.PLANNING });
          }
          break;
        }

        // ── Step events ─────────────────────────────────────────────────────
        case EventType.STEP_STARTED: {
          const stepId = event.payload.step_id as string | undefined;
          const stepIdx = findStepIndex(taskId, stepId);
          updateTask(taskId, { currentStepIndex: stepIdx, status: TaskStatus.RUNNING });
          const task = getTasks().tasks[taskId];
          if (task?.plan) {
            const plan = task.plan.map((step, i) =>
              i === stepIdx
                ? { ...step, status: StepStatus.RUNNING, startedAt: event.timestamp }
                : step
            );
            updateTask(taskId, { plan });
          }
          break;
        }

        case EventType.STEP_COMPLETED: {
          const stepId = event.payload.step_id as string | undefined;
          const stepIdx = findStepIndex(taskId, stepId);
          const task = getTasks().tasks[taskId];
          if (task?.plan) {
            const plan = task.plan.map((step, i) =>
              i === stepIdx
                ? {
                    ...step,
                    status: StepStatus.COMPLETED,
                    completedAt: event.timestamp,
                    actualCostUsd: (event.payload.costUsd as number) || step.actualCostUsd,
                  }
                : step
            );
            updateTask(taskId, { plan });
          }
          break;
        }

        case EventType.STEP_FAILED: {
          const stepId = event.payload.step_id as string | undefined;
          const stepIdx = findStepIndex(taskId, stepId);
          const task = getTasks().tasks[taskId];
          if (task?.plan) {
            const plan = task.plan.map((step, i) =>
              i === stepIdx
                ? {
                    ...step,
                    status: StepStatus.FAILED,
                    completedAt: event.timestamp,
                    error: (event.payload.error as string) || 'Step failed',
                  }
                : step
            );
            updateTask(taskId, { plan });
          }
          break;
        }

        // ── Error event (executor emits this on step failure) ───────────────
        case EventType.ERROR: {
          const stepId = event.payload.step_id as string | undefined;
          if (stepId) {
            const stepIdx = findStepIndex(taskId, stepId);
            const task = getTasks().tasks[taskId];
            if (task?.plan) {
              const plan = task.plan.map((step, i) =>
                i === stepIdx
                  ? {
                      ...step,
                      status: StepStatus.FAILED,
                      completedAt: event.timestamp,
                      error: (event.payload.error as string) || 'Error',
                    }
                  : step
              );
              updateTask(taskId, { plan });
            }
          }
          break;
        }

        // ── Replan: new plan replacing remaining steps ──────────────────────
        case EventType.REPLAN: {
          // Backend will emit a new plan_created event shortly; nothing to do here
          break;
        }

        // ── Approval flow ───────────────────────────────────────────────────
        case EventType.APPROVAL_REQUIRED: {
          updateTask(taskId, {
            status: TaskStatus.AWAITING_APPROVAL,
            pendingApproval: event.payload as import('@/lib/types').ApprovalRequest,
          });
          addToast({
            type: 'warning',
            title: 'Approval required',
            message: (event.payload.action as string) || 'Human approval needed.',
            duration: 0, // persistent
          });
          break;
        }

        case EventType.APPROVAL_GRANTED:
          updateTask(taskId, {
            status: TaskStatus.RUNNING,
            pendingApproval: undefined,
          });
          break;

        case EventType.APPROVAL_DENIED:
          updateTask(taskId, {
            status: TaskStatus.RUNNING,
            pendingApproval: undefined,
          });
          break;

        // ── Artifacts ───────────────────────────────────────────────────────
        case EventType.ARTIFACT_CREATED: {
          const artifact = event.payload as import('@/lib/types').Artifact;
          const currentTask = getTasks().tasks[taskId];
          if (currentTask) {
            updateTask(taskId, {
              artifacts: [...(currentTask.artifacts || []), artifact],
            });
          }
          break;
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [taskId, addEvent, updateTask, updateCost, addToast]
  );

  useEffect(() => {
    if (!taskId) return;

    // Clean up previous connection
    if (cleanupRef.current) {
      cleanupRef.current();
      cleanupRef.current = null;
    }

    setIsConnected(true);
    setError(null);

    const cleanup = streamEvents(taskId, {
      onEvent: handleEvent,
      onError: (err) => {
        setError(err.message);
        setIsConnected(false);
      },
      onClose: () => {
        setIsConnected(false);
      },
    });

    cleanupRef.current = cleanup;

    return () => {
      cleanup();
      cleanupRef.current = null;
    };
  }, [taskId, handleEvent]);

  return { events, isConnected, error };
}
