// ============================================================
// Enums
// ============================================================

export enum TaskStatus {
  PENDING = 'queued',
  PLANNING = 'planning',
  RUNNING = 'running',
  AWAITING_APPROVAL = 'waiting_approval',
  COMPLETED = 'completed',
  FAILED = 'failed',
  ABORTED = 'aborted',
}

export enum EventType {
  TASK_CREATED = 'task_created',
  TASK_STARTED = 'task_started',
  TASK_COMPLETED = 'task_completed',
  TASK_FAILED = 'task_failed',
  TASK_ABORTED = 'task_aborted',
  PLAN_CREATED = 'plan_created',
  STEP_STARTED = 'step_started',
  STEP_COMPLETED = 'step_completed',
  STEP_FAILED = 'step_failed',
  TOOL_CALL_STARTED = 'tool_call_started',
  TOOL_CALL_COMPLETED = 'tool_call_completed',
  TOOL_CALL_FAILED = 'tool_call_failed',
  // Backend-native event types (mapped from tool_called / tool_result)
  TOOL_CALLED = 'tool_called',
  TOOL_RESULT = 'tool_result',
  MODEL_CALL = 'model_call',
  APPROVAL_REQUIRED = 'approval_required',
  APPROVAL_GRANTED = 'approval_granted',
  APPROVAL_DENIED = 'approval_denied',
  ARTIFACT_CREATED = 'artifact_created',
  LOG = 'log',
  ERROR = 'error',
  COST_UPDATE = 'cost_update',
  // Backend thinking / orchestration events
  THINKING = 'thinking',
  RETRY = 'retry',
  REPLAN = 'replan',
}

export enum StepStatus {
  PENDING = 'pending',
  RUNNING = 'running',
  COMPLETED = 'completed',
  FAILED = 'failed',
  SKIPPED = 'skipped',
}

export enum RiskLevel {
  LOW = 'low',
  MEDIUM = 'medium',
  HIGH = 'high',
  CRITICAL = 'critical',
}

// ============================================================
// Task models
// ============================================================

export interface TaskConstraints {
  allowWeb: boolean;
  allowFileSystem: boolean;
  allowCodeExecution: boolean;
  allowOllama: boolean;
  maxBudgetUsd: number;
  maxSteps: number;
  requireApprovalFor: string[];
  timeoutSeconds?: number;
}

export interface TaskCreate {
  goal: string;
  constraints: TaskConstraints;
  mode?: 'demo' | 'interactive';
}

export interface TaskStep {
  id: string;
  index: number;
  title: string;
  description: string;
  toolToUse?: string;
  expectedOutput?: string;
  status: StepStatus;
  startedAt?: string;
  completedAt?: string;
  estimatedCostUsd?: number;
  actualCostUsd?: number;
  error?: string;
}

export interface Artifact {
  id: string;
  taskId: string;
  name: string;
  type: 'text' | 'json' | 'csv' | 'code' | 'markdown' | 'image' | 'binary';
  content: string;
  mimeType?: string;
  sizeBytes?: number;
  createdAt: string;
}

export interface TaskState {
  id: string;
  goal: string;
  status: TaskStatus;
  constraints: TaskConstraints;
  mode: 'demo' | 'interactive';
  plan?: TaskStep[];
  currentStepIndex?: number;
  artifacts: Artifact[];
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  totalCostUsd: number;
  error?: string;
  pendingApproval?: ApprovalRequest;
}

// ============================================================
// Events
// ============================================================

export interface ApprovalRequest {
  action: string;
  description: string;
  impact?: string;
  riskLevel: RiskLevel;
  timeoutSeconds?: number;
}

export interface ModelCallPayload {
  model: string;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  isFree: boolean;
  prompt?: string;
  response?: string;
  latencyMs?: number;
}

export interface ToolCallPayload {
  toolName: string;
  input: Record<string, unknown>;
  output?: unknown;
  error?: string;
  latencyMs?: number;
  costUsd?: number;
}

export interface AgentEvent {
  id: string;
  taskId: string;
  type: EventType;
  timestamp: string;
  payload: Record<string, unknown>;
  model?: string;
  costUsd?: number;
  stepIndex?: number;
}

// ============================================================
// Cost tracking
// ============================================================

export interface ModelCost {
  model: string;
  inputCostPer1M: number;
  outputCostPer1M: number;
}

export interface ModelUsage {
  model: string;
  calls: number;
  inputTokens: number;
  outputTokens: number;
  totalCostUsd: number;
  isFree: boolean;
}

export interface CostSummary {
  totalCost: number;
  freeModelCalls: number;
  paidModelCalls: number;
  freeModelSavingsUsd: number;
  modelBreakdown: ModelUsage[];
  budgetLimitUsd?: number;
}

// ============================================================
// Settings
// ============================================================

export interface Settings {
  openrouterApiKey: string;
  ollamaUrl: string;
  ollamaEnabled: boolean;
  hyperbrowserApiKey: string;
  preferFreeModels: boolean;
  maxBudgetUsd: number;
  modelOverride: string;
  requireApprovalCodeExec: boolean;
  requireApprovalFileWrite: boolean;
  requireApprovalWebRequests: boolean;
  maxRetriesPerStep: number;
  fallbackToBasicScraping: boolean;
  // External API keys
  wavespeedApiKey: string;
  googleMapsApiKey: string;
  huggingfaceApiKey: string;
  serpApiKey: string;
  // Voice & Avatar
  falApiKey: string;
  heygenApiKey: string;
  voiceEnabled: boolean;
  voiceAutoPlay: boolean;
  voiceVoice: string;
  avatarEnabled: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  openrouterApiKey: '',
  ollamaUrl: 'http://localhost:11434',
  ollamaEnabled: false,
  hyperbrowserApiKey: '',
  preferFreeModels: true,
  maxBudgetUsd: 1.0,
  modelOverride: 'auto',
  requireApprovalCodeExec: true,
  requireApprovalFileWrite: true,
  requireApprovalWebRequests: false,
  maxRetriesPerStep: 3,
  fallbackToBasicScraping: true,
  wavespeedApiKey: '',
  googleMapsApiKey: '',
  huggingfaceApiKey: '',
  serpApiKey: '',
  falApiKey: '',
  heygenApiKey: '',
  voiceEnabled: false,
  voiceAutoPlay: true,
  voiceVoice: 'af_sky',
  avatarEnabled: false,
};

// ============================================================
// UI helpers
// ============================================================

export interface Toast {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  title: string;
  message?: string;
  duration?: number;
}
