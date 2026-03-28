'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { streamEvents } from '@/lib/api';
import { useStore } from '@/lib/store';
import { type AgentEvent, EventType, TaskStatus, StepStatus } from '@/lib/types';

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

  const handleEvent = useCallback(
    (event: AgentEvent) => {
      if (!taskId) return;

      addEvent(taskId, event);
      updateCost(taskId, event);

      // Sync task state from events
      switch (event.type) {
        case EventType.TASK_STARTED:
          updateTask(taskId, {
            status: TaskStatus.RUNNING,
            startedAt: event.timestamp,
          });
          break;

        case EventType.TASK_COMPLETED:
          updateTask(taskId, {
            status: TaskStatus.COMPLETED,
            completedAt: event.timestamp,
          });
          setIsConnected(false);
          addToast({
            type: 'success',
            title: 'Task completed',
            message: 'The agent finished successfully.',
          });
          break;

        case EventType.TASK_FAILED:
          updateTask(taskId, {
            status: TaskStatus.FAILED,
            error: (event.payload.error as string) || 'Unknown error',
            completedAt: event.timestamp,
          });
          setIsConnected(false);
          addToast({
            type: 'error',
            title: 'Task failed',
            message: (event.payload.error as string) || 'The agent encountered an error.',
          });
          break;

        case EventType.TASK_ABORTED:
          updateTask(taskId, {
            status: TaskStatus.ABORTED,
            completedAt: event.timestamp,
          });
          setIsConnected(false);
          break;

        case EventType.PLAN_CREATED: {
          const plan = event.payload.plan as import('@/lib/types').TaskStep[] | undefined;
          if (plan) {
            updateTask(taskId, { plan, status: TaskStatus.PLANNING });
          }
          break;
        }

        case EventType.STEP_STARTED: {
          const stepIndex = event.stepIndex ?? (event.payload.stepIndex as number) ?? 0;
          updateTask(taskId, { currentStepIndex: stepIndex, status: TaskStatus.RUNNING });
          // Update the step status in plan
          const task = getTasks().tasks[taskId];
          if (task?.plan) {
            const plan = task.plan.map((step, i) =>
              i === stepIndex
                ? { ...step, status: StepStatus.RUNNING, startedAt: event.timestamp }
                : step
            );
            updateTask(taskId, { plan });
          }
          break;
        }

        case EventType.STEP_COMPLETED: {
          const stepIndex = event.stepIndex ?? (event.payload.stepIndex as number) ?? 0;
          const task = getTasks().tasks[taskId];
          if (task?.plan) {
            const plan = task.plan.map((step, i) =>
              i === stepIndex
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
          const stepIndex = event.stepIndex ?? (event.payload.stepIndex as number) ?? 0;
          const task = getTasks().tasks[taskId];
          if (task?.plan) {
            const plan = task.plan.map((step, i) =>
              i === stepIndex
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

        case EventType.ERROR:
          addToast({
            type: 'error',
            title: 'Agent error',
            message: (event.payload.message as string) || 'An error occurred.',
          });
          break;
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
