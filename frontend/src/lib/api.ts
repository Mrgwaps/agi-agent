import type { TaskCreate, TaskState, AgentEvent } from './types';

// ============================================================
// API response normalizer (backend uses snake_case / taskId)
// ============================================================

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeTask(raw: any): TaskState {
  return {
    id: raw.id ?? raw.taskId ?? raw.task_id,
    goal: raw.goal,
    status: raw.status,
    mode: raw.mode ?? 'demo',
    constraints: raw.constraints ?? {},
    plan: (raw.plan ?? []).map((s: any) => ({
      id: s.id,
      index: s.index ?? 0,
      title: s.title ?? s.description ?? '',
      description: s.description ?? '',
      toolToUse: s.tool_used ?? s.toolToUse,
      status: s.status,
      startedAt: s.started_at ?? s.startedAt,
      completedAt: s.completed_at ?? s.completedAt,
      actualCostUsd: s.cost_usd ?? s.actualCostUsd ?? 0,
      error: s.error,
    })),
    currentStepIndex: raw.currentStepIndex ?? raw.currentStep ?? 0,
    artifacts: raw.artifacts ?? [],
    createdAt: raw.createdAt ?? raw.created_at ?? new Date().toISOString(),
    startedAt: raw.startedAt ?? raw.started_at,
    completedAt: raw.completedAt ?? raw.completed_at,
    totalCostUsd: raw.totalCostUsd ?? raw.total_cost_usd ?? 0,
    error: raw.error,
    pendingApproval: raw.pendingApproval ?? raw.pending_approval,
  };
}

const BASE_URL =
  typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000')
    : (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000');

// ============================================================
// Generic fetch helper
// ============================================================

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (!res.ok) {
    let errorMessage = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      errorMessage = body.detail || body.message || errorMessage;
    } catch {
      // ignore parse errors
    }
    throw new Error(errorMessage);
  }

  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

// ============================================================
// Task endpoints
// ============================================================

export async function createTask(
  goal: string,
  constraints: TaskCreate['constraints'],
  mode: 'demo' | 'interactive' = 'demo'
): Promise<TaskState> {
  const raw = await apiFetch<unknown>('/tasks', {
    method: 'POST',
    body: JSON.stringify({ goal, constraints, mode } satisfies TaskCreate),
  });
  return normalizeTask(raw);
}

export async function getTask(taskId: string): Promise<TaskState> {
  const raw = await apiFetch<unknown>(`/tasks/${taskId}`);
  return normalizeTask(raw);
}

export async function listTasks(): Promise<TaskState[]> {
  const raw = await apiFetch<unknown[]>('/tasks');
  return (raw ?? []).map(normalizeTask);
}

export async function approveAction(taskId: string): Promise<void> {
  return apiFetch<void>(`/tasks/${taskId}/approve`, { method: 'POST' });
}

export async function denyAction(taskId: string): Promise<void> {
  return apiFetch<void>(`/tasks/${taskId}/deny`, { method: 'POST' });
}

export async function abortTask(taskId: string): Promise<void> {
  return apiFetch<void>(`/tasks/${taskId}/abort`, { method: 'POST' });
}

// ============================================================
// SSE event stream
// ============================================================

export interface StreamEventCallbacks {
  onEvent: (event: AgentEvent) => void;
  onError: (err: Error) => void;
  onClose: () => void;
}

export function streamEvents(
  taskId: string,
  callbacks: StreamEventCallbacks
): () => void {
  const url = `${BASE_URL}/tasks/${taskId}/events`;
  let closed = false;
  let retryTimeout: ReturnType<typeof setTimeout> | null = null;
  let eventSource: EventSource | null = null;

  function connect() {
    if (closed) return;

    eventSource = new EventSource(url);

    eventSource.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as AgentEvent;
        callbacks.onEvent(data);
      } catch {
        // ignore malformed events
      }
    };

    eventSource.onerror = () => {
      eventSource?.close();
      eventSource = null;
      if (!closed) {
        callbacks.onError(new Error('SSE connection lost, retrying…'));
        retryTimeout = setTimeout(connect, 3000);
      }
    };

    eventSource.addEventListener('close', () => {
      eventSource?.close();
      eventSource = null;
      callbacks.onClose();
    });
  }

  connect();

  // Return a cleanup function
  return () => {
    closed = true;
    if (retryTimeout) clearTimeout(retryTimeout);
    eventSource?.close();
    eventSource = null;
  };
}

// ============================================================
// Settings / health checks
// ============================================================

export async function testOllamaConnection(ollamaUrl: string): Promise<{ ok: boolean; models: string[] }> {
  try {
    const res = await fetch(`${ollamaUrl}/api/tags`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) return { ok: false, models: [] };
    const data = await res.json();
    const models = (data.models || []).map((m: { name: string }) => m.name);
    return { ok: true, models };
  } catch {
    return { ok: false, models: [] };
  }
}

export async function testBackendHealth(): Promise<boolean> {
  try {
    await apiFetch<unknown>('/health');
    return true;
  } catch {
    return false;
  }
}
