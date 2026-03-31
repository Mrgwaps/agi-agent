import type { TaskCreate, TaskState, AgentEvent } from './types';
import { StepStatus } from './types';

// ============================================================
// Task normalizer (backend uses snake_case / taskId)
// ============================================================

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeStep(s: any, index: number) {
  return {
    id: s.id ?? `step-${index}`,
    index,
    title: s.title ?? s.description ?? `Step ${index + 1}`,
    description: s.description ?? s.title ?? '',
    toolToUse: s.tool_used ?? s.toolToUse ?? s.tool,
    status: (s.status as StepStatus) ?? StepStatus.PENDING,
    startedAt: s.started_at ?? s.startedAt,
    completedAt: s.completed_at ?? s.completedAt,
    actualCostUsd: s.cost_usd ?? s.actualCostUsd ?? 0,
    error: s.error,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeTask(raw: any): TaskState {
  return {
    id: raw.id ?? raw.taskId ?? raw.task_id,
    goal: raw.goal ?? '',
    status: raw.status,
    mode: raw.mode ?? 'auto',
    constraints: raw.constraints ?? {},
    plan: (raw.plan ?? []).map(normalizeStep),
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

// ============================================================
// Event normalizer
// Backend AgentEvent uses:
//   eventType (not type), model_used (not model), cost_usd (not costUsd)
//   tool_called / tool_result instead of tool_call_started / tool_call_completed
//   plan_created payload uses { steps: [...] } not { plan: [...] }
// ============================================================

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeEvent(raw: any): AgentEvent {
  // Map eventType → type, rename tool events for frontend compatibility
  let type: string = raw.type ?? raw.eventType ?? 'unknown';

  // Rename backend tool event names to frontend names
  if (type === 'tool_called') type = 'tool_call_started';
  if (type === 'tool_result') type = 'tool_call_completed';

  // Normalize payload
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let payload: Record<string, any> = raw.payload ?? {};

  // plan_created: backend sends payload.steps[], frontend expects payload.plan[]
  if (type === 'plan_created') {
    const steps = payload.steps ?? payload.plan ?? [];
    payload = {
      ...payload,
      plan: steps.map(normalizeStep),
      steps,
    };
  }

  // step_started: ensure description is shown as title
  if (type === 'step_started') {
    payload = {
      ...payload,
      title: payload.title ?? payload.description ?? '',
      toolName: payload.tool ?? payload.toolName,
    };
  }

  // step_completed / step_failed: normalize result/error fields
  if (type === 'step_completed' || type === 'step_failed') {
    payload = {
      ...payload,
      title: payload.title ?? payload.description ?? '',
    };
  }

  // tool events: normalize tool name field
  if (type === 'tool_call_started' || type === 'tool_call_completed' || type === 'tool_call_failed') {
    payload = {
      ...payload,
      toolName: payload.toolName ?? payload.tool ?? 'tool',
    };
  }

  return {
    id: raw.id ?? `evt-${Date.now()}-${Math.random()}`,
    taskId: raw.taskId ?? raw.task_id ?? '',
    type: type as AgentEvent['type'],
    timestamp: raw.timestamp ?? new Date().toISOString(),
    payload,
    model: raw.model ?? raw.model_used,
    costUsd: raw.costUsd ?? raw.cost_usd ?? 0,
    stepIndex: raw.stepIndex ?? raw.step_index,
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
  mode: 'auto' | 'interactive' = 'auto'
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
  return apiFetch<void>(`/tasks/${taskId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved: true }),
  });
}

export async function denyAction(taskId: string): Promise<void> {
  return apiFetch<void>(`/tasks/${taskId}/deny`, {
    method: 'POST',
    body: JSON.stringify({ approved: false }),
  });
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
        const raw = JSON.parse(ev.data);
        callbacks.onEvent(normalizeEvent(raw));
      } catch {
        // ignore malformed events
      }
    };

    // Also listen on named events (sse_starlette sends event name separately)
    const eventNames = [
      'plan_created', 'step_started', 'step_completed', 'tool_called',
      'tool_result', 'thinking', 'retry', 'replan', 'task_completed',
      'task_failed', 'task_aborted', 'cost_update', 'approval_required',
      'approval_granted', 'approval_denied', 'error',
    ];
    for (const name of eventNames) {
      eventSource.addEventListener(name, (ev: MessageEvent) => {
        try {
          const raw = JSON.parse(ev.data);
          callbacks.onEvent(normalizeEvent(raw));
        } catch {
          // ignore malformed events
        }
      });
    }

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

export async function pushSettingsToBackend(keys: {
  openrouterApiKey?: string;
  hyperbrowserApiKey?: string;
  wavespeedApiKey?: string;
  googleMapsApiKey?: string;
  huggingfaceApiKey?: string;
  serpApiKey?: string;
  falApiKey?: string;
  heygenApiKey?: string;
  agentMailApiKey?: string;
  ghostApiKey?: string;
  stripePublishableKey?: string;
  stripeWebhookSecret?: string;
}): Promise<void> {
  try {
    await apiFetch('/settings', {
      method: 'POST',
      body: JSON.stringify({
        openrouter_api_key: keys.openrouterApiKey || undefined,
        hyperbrowser_api_key: keys.hyperbrowserApiKey || undefined,
        wavespeed_api_key: keys.wavespeedApiKey || undefined,
        google_maps_api_key: keys.googleMapsApiKey || undefined,
        huggingface_api_key: keys.huggingfaceApiKey || undefined,
        serp_api_key: keys.serpApiKey || undefined,
        fal_api_key: keys.falApiKey || undefined,
        heygen_api_key: keys.heygenApiKey || undefined,
        agentmail_api_key: keys.agentMailApiKey || undefined,
        ghost_database_url: keys.ghostApiKey || undefined,
        stripe_publishable_key: keys.stripePublishableKey || undefined,
        stripe_webhook_secret: keys.stripeWebhookSecret || undefined,
      }),
    });
  } catch {
    // Non-fatal — settings still saved locally
  }
}
