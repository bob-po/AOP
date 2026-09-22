const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8080";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";

const SESSION_KEY = "aop_session_token";

export function getSessionToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(SESSION_KEY) || "";
  } catch {
    return "";
  }
}

export function setSessionToken(token: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (!token) localStorage.removeItem(SESSION_KEY);
    else localStorage.setItem(SESSION_KEY, token);
  } catch {
    /* ignore */
  }
}

function authHeader(): string {
  return getSessionToken() || API_KEY;
}

function isSessionToken(token: string): boolean {
  return token.startsWith("aop_sess_");
}

export type TaskNode = {
  id: string;
  skill: string;
  status: string;
  agent_id?: string | null;
  attempt?: number;
  error_message?: string | null;
};

export type TaskPlan = {
  title?: string;
  goal?: string;
  nodes: Array<{
    id: string;
    skill: string;
    depends_on?: string[];
  }>;
};

export type TaskSummary = {
  task_id: string;
  title?: string;
  status: string;
  progress?: number;
  created_at?: string;
  updated_at?: string;
  finished_at?: string;
};

export type TaskDetail = {
  task_id: string;
  title?: string;
  status: string;
  progress?: number;
  input_json?: { type?: string; content?: string };
  plan_json?: TaskPlan;
  result_json?: {
    summary?: string;
    artifacts?: Array<Record<string, unknown>>;
  };
  nodes: TaskNode[];
  created_at?: string;
  updated_at?: string;
  finished_at?: string;
};

export type TaskEvent = {
  event_type: string;
  message?: string;
  payload?: Record<string, unknown>;
  ts?: string;
};

export type Agent = {
  agent_id: string;
  agent_key: string;
  name: string;
  description?: string;
  status: string;
  endpoint?: string;
  skills: string[];
  priority?: number;
};

export type ArtifactItem = {
  task_id?: string;
  node_id?: string;
  name?: string;
  uri?: string;
  url?: string;
  mime_type?: string;
  type?: string;
  size?: number;
  last_modified?: string;
};

export type OverviewStats = {
  total_tasks: number;
  running: number;
  completed: number;
  failed: number;
  success_rate: number;
  agents_online: number;
  agents_degraded: number;
  agents_offline: number;
  agents_total: number;
  queue_waiting: number;
  trend: Array<{ day: string; count: number }>;
};

export type ApiKeyRecord = {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  status: string;
  created_at?: string;
  expires_at?: string | null;
  last_used_at?: string | null;
  api_key?: string;
};

async function request<T>(
  path: string,
  init?: RequestInit & { __sessionRetried?: boolean },
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  // Login is public — do not attach a stale session Bearer.
  const skipAuth = path === "/v1/auth/login";
  const token = skipAuth ? "" : authHeader();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    // Stale browser session blocks API Key / anonymous local mode — clear and retry once.
    if (
      res.status === 401 &&
      !skipAuth &&
      token &&
      isSessionToken(token) &&
      !init?.__sessionRetried
    ) {
      setSessionToken(null);
      const { __sessionRetried: _ignored, ...rest } = init || {};
      return request<T>(path, { ...rest, __sessionRetried: true });
    }
    throw new Error(`${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

export function createTask(content: string) {
  return request<{
    task_id: string;
    status: string;
    title?: string;
    plan?: TaskPlan;
    ready_nodes?: string[];
    nodes?: TaskNode[];
  }>("/v1/tasks", {
    method: "POST",
    body: JSON.stringify({
      input: { type: "text", content },
    }),
  });
}

export function listTasks(params?: { status?: string; limit?: number }) {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  return request<{ tasks: TaskSummary[] }>(`/v1/tasks${qs ? `?${qs}` : ""}`);
}

export function getTask(taskId: string) {
  return request<TaskDetail>(`/v1/tasks/${taskId}`);
}

export function cancelTask(taskId: string) {
  return request<{ task_id: string; status: string; cancelled?: boolean }>(
    `/v1/tasks/${taskId}/cancel`,
    { method: "POST" },
  );
}

export function getTaskEvents(taskId: string) {
  return request<{ events: TaskEvent[] }>(`/v1/tasks/${taskId}/events`);
}

export function getTaskArtifacts(taskId: string) {
  return request<{ task_id: string; artifacts: ArtifactItem[] }>(
    `/v1/tasks/${taskId}/artifacts`,
  );
}

export function listArtifacts(params?: {
  task_id?: string;
  type?: string;
  limit?: number;
}) {
  const q = new URLSearchParams();
  if (params?.task_id) q.set("task_id", params.task_id);
  if (params?.type) q.set("type", params.type);
  if (params?.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  return request<{ artifacts: ArtifactItem[] }>(`/v1/artifacts${qs ? `?${qs}` : ""}`);
}

export function getOverviewStats() {
  return request<OverviewStats>("/v1/stats/overview");
}

export function listAgents(params?: { skill?: string; status?: string }) {
  const q = new URLSearchParams();
  if (params?.skill) q.set("skill", params.skill);
  if (params?.status) q.set("status", params.status);
  const qs = q.toString();
  return request<{ agents: Agent[] }>(`/v1/agents${qs ? `?${qs}` : ""}`);
}

export function registerAgent(endpoint: string) {
  return request<Record<string, unknown>>("/v1/agents/register", {
    method: "POST",
    body: JSON.stringify({ endpoint }),
  });
}

export function getAgent(agentId: string) {
  return request<Agent>(`/v1/agents/${agentId}`);
}

export function healthCheckAgent(agentId: string) {
  return request<Record<string, unknown>>(`/v1/agents/${agentId}/health`, {
    method: "POST",
  });
}

export type Workflow = {
  workflow_id: string;
  workflow_key: string;
  name: string;
  description?: string;
  status: string;
  version?: string;
  dag?: TaskPlan;
};

export function listWorkflows(status?: string) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<{ workflows: Workflow[] }>(`/v1/workflows${qs}`);
}

export function createWorkflow(body: {
  name: string;
  description?: string;
  workflow_key?: string;
  version?: string;
  publish?: boolean;
  dag: TaskPlan;
}) {
  return request<Workflow>("/v1/workflows", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function runWorkflow(workflowId: string, content: string, title?: string) {
  return request<{
    task_id: string;
    status: string;
    plan?: TaskPlan;
    workflow_id?: string;
  }>(`/v1/workflows/${workflowId}/run`, {
    method: "POST",
    body: JSON.stringify({
      input: { type: "text", content },
      title,
    }),
  });
}

export type MarketplacePackage = {
  package_id: string;
  name: string;
  description?: string;
  publisher?: string;
  version?: string;
  skills?: string[];
  default_endpoint?: string;
  agent_key?: string;
  tags?: string[];
  installed?: boolean;
  agent?: {
    agent_id: string;
    agent_key: string;
    status: string;
    endpoint?: string;
    skills?: string[];
  } | null;
};

export function listMarketplace(q?: string) {
  const qs = q ? `?q=${encodeURIComponent(q)}` : "";
  return request<{ packages: MarketplacePackage[] }>(`/v1/marketplace${qs}`);
}

export function installMarketplacePackage(packageId: string, endpoint?: string) {
  return request<{ installed: boolean; agent: Record<string, unknown> }>(
    "/v1/marketplace/install",
    {
      method: "POST",
      body: JSON.stringify({ package_id: packageId, endpoint }),
    },
  );
}

export function enableAgent(agentId: string) {
  return request<Record<string, unknown>>(`/v1/agents/${agentId}/enable`, {
    method: "POST",
  });
}

export function disableAgent(agentId: string) {
  return request<Record<string, unknown>>(`/v1/agents/${agentId}/disable`, {
    method: "POST",
  });
}

export function probeHealth() {
  return request<{
    probed: number;
    online: number;
    results: Array<Record<string, unknown>>;
  }>("/v1/health/probe", { method: "POST" });
}

export function listApiKeys() {
  return request<{ api_keys: ApiKeyRecord[] }>("/v1/api-keys");
}

export function createApiKey(
  name: string,
  opts?: { role?: string; scopes?: string[] },
) {
  const body: Record<string, unknown> = { name };
  if (opts?.role) body.role = opts.role;
  else body.scopes = opts?.scopes || ["role:operator"];
  return request<ApiKeyRecord>("/v1/api-keys", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function revokeApiKey(keyId: string) {
  return request<{ revoked: boolean; id: string }>(`/v1/api-keys/${keyId}`, {
    method: "DELETE",
  });
}

export type RbacRole = { role: string; scopes: string[] };

export function listRbacRoles() {
  return request<{ roles: RbacRole[]; docs?: string }>("/v1/rbac/roles");
}

export function getRbacMe() {
  return request<{
    authenticated: boolean;
    auth_required?: boolean;
    name?: string;
    scopes?: string[];
    roles?: string[];
    expanded?: string[];
  }>("/v1/rbac/me");
}

export type AuditLogEntry = {
  id: number;
  tenant_id?: string | null;
  action: string;
  resource_type?: string;
  resource_id?: string;
  ip?: string;
  payload?: Record<string, unknown>;
  created_at?: string;
};

export function listAuditLogs(limit = 50) {
  return request<{ audit_logs: AuditLogEntry[] }>(`/v1/audit-logs?limit=${limit}`);
}

export type AuthUser = {
  id: string;
  email: string;
  display_name?: string;
  role: string;
  tenant_id?: string;
  status?: string;
};

export function login(email: string, password: string) {
  return request<{
    token: string;
    token_type: string;
    expires_at: string;
    user: AuthUser;
    scopes: string[];
  }>("/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function logout() {
  return request<{ logged_out: boolean }>("/v1/auth/logout", { method: "POST" });
}

export function getAuthMe() {
  return request<{
    authenticated: boolean;
    auth_required?: boolean;
    kind?: string;
    name?: string;
    email?: string;
    user_id?: string;
    user_role?: string;
    scopes?: string[];
    roles?: string[];
    expanded?: string[];
    user?: AuthUser;
  }>("/v1/auth/me");
}

export function getGatewayHealth() {
  return request<{
    status: string;
    service?: string;
    phase?: string;
    auth_required?: boolean;
  }>("/health");
}

export type TaskEvaluation = {
  id?: string;
  tenant_id?: string;
  task_id: string;
  method: string;
  score: number;
  grade: string;
  dimensions?: Record<string, number>;
  summary?: string;
  details?: Record<string, unknown>;
  created_at?: string;
  task_title?: string;
  task_status?: string;
};

export type EvaluationOverview = {
  total: number;
  avg_score: number;
  grade_a: number;
  grade_b: number;
  grade_c: number;
  grade_df: number;
};

export function getTaskEvaluation(taskId: string) {
  return request<TaskEvaluation>(`/v1/tasks/${taskId}/evaluation`);
}

export function evaluateTask(taskId: string, method = "heuristic") {
  const qs = method ? `?method=${encodeURIComponent(method)}` : "";
  return request<TaskEvaluation>(`/v1/tasks/${taskId}/evaluate${qs}`, {
    method: "POST",
  });
}

export function listEvaluations(params?: { limit?: number; min_score?: number }) {
  const q = new URLSearchParams();
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.min_score != null) q.set("min_score", String(params.min_score));
  const qs = q.toString();
  return request<{ evaluations: TaskEvaluation[] }>(
    `/v1/evaluations${qs ? `?${qs}` : ""}`,
  );
}

export function getEvaluationOverview() {
  return request<EvaluationOverview>("/v1/evaluations/overview");
}

export type MemoryEntry = {
  id?: string;
  task_id: string;
  memory_key: string;
  content: string;
  metadata?: Record<string, unknown>;
  updated_at?: string;
};

export function getTaskMemory(taskId: string) {
  return request<{ task_id: string; memories: MemoryEntry[] }>(
    `/v1/tasks/${taskId}/memory`,
  );
}

export function putTaskMemory(
  taskId: string,
  memoryKey: string,
  content: string,
  metadata?: Record<string, unknown>,
) {
  return request<MemoryEntry>(`/v1/tasks/${taskId}/memory`, {
    method: "PUT",
    body: JSON.stringify({
      memory_key: memoryKey,
      content,
      metadata: metadata || {},
    }),
  });
}

export type MetricsSnapshot = {
  generated_at?: string;
  window_hours?: number;
  tasks?: Record<string, number>;
  agents?: Record<string, number>;
  agent_runs?: Record<string, number>;
  memories?: { total?: number };
  evaluations?: { total?: number; avg_score?: number };
};

export function getMetrics(hours = 24) {
  return request<MetricsSnapshot>(`/v1/metrics?hours=${hours}`);
}

export function approveTask(taskId: string, nodeKey?: string) {
  return request<{
    task_id: string;
    node_key: string;
    approved: boolean;
    status?: string;
    enqueued_nodes?: string[];
  }>(`/v1/tasks/${taskId}/approve`, {
    method: "POST",
    body: JSON.stringify({ node_key: nodeKey || null }),
  });
}

export function rejectTask(taskId: string, reason?: string, nodeKey?: string) {
  return request<{
    task_id: string;
    node_key: string;
    rejected: boolean;
    status?: string;
  }>(`/v1/tasks/${taskId}/reject`, {
    method: "POST",
    body: JSON.stringify({
      node_key: nodeKey || null,
      reason: reason || "rejected by user",
    }),
  });
}

export type AgentPerformance = {
  agent_id: string;
  agent_key: string;
  name: string;
  status: string;
  priority: number;
  request_count: number;
  success_count: number;
  failure_count: number;
  avg_latency_ms: number;
  success_rate: number;
};

export function getAgentStats(limit = 50) {
  return request<{ agents: AgentPerformance[] }>(
    `/v1/stats/agents?limit=${limit}`,
  );
}

export function previewRouter(skill: string) {
  return request<{
    skill: string;
    smart: boolean;
    selected: string | null;
    candidates: Array<{
      agent_id: string;
      agent_key: string;
      name: string;
      score: number;
      priority: number;
      score_breakdown?: Record<string, number>;
    }>;
  }>(`/v1/router/preview?skill=${encodeURIComponent(skill)}`);
}

export type BillingSkillRow = {
  skill: string;
  runs: number;
  success: number;
  failed: number;
  unit_price_usd: number;
  estimated_cost_usd: number;
  stored_cost_usd: number;
  latency_ms_sum: number;
};

export type BillingUsage = {
  tenant_id: string;
  window_days: number;
  since: string;
  currency: string;
  prices: {
    task_created: number;
    agent_run_default: number;
    per_skill: Record<string, number>;
  };
  tasks: {
    total?: number;
    completed?: number;
    failed?: number;
    active?: number;
  };
  task_cost_usd: number;
  agent_runs: {
    total: number;
    by_skill: BillingSkillRow[];
    estimated_cost_usd: number;
    stored_cost_usd: number;
  };
  estimated_total_usd: number;
  daily_tasks: Array<{ day: string; tasks: number }>;
  note?: string;
};

export function getBillingUsage(days = 30) {
  return request<BillingUsage>(`/v1/billing/usage?days=${days}`);
}

export function getBillingSummary() {
  return request<{ d7: BillingUsage; d30: BillingUsage }>("/v1/billing/summary");
}

export type InvoiceLineItem = {
  id: string;
  description: string;
  quantity: number;
  unit_amount_usd: number;
  amount_usd: number;
  skill?: string;
};

export type Invoice = {
  id?: string;
  invoice_number: string;
  tenant_id: string;
  status: string;
  currency: string;
  window_days: number;
  period_start: string;
  period_end: string;
  issued_at?: string;
  created_at?: string;
  issuer?: string;
  line_items: InvoiceLineItem[];
  subtotal_usd: number;
  tax_usd?: number;
  total_usd: number;
  note?: string;
  stripe?: {
    mode?: string;
    checkout_ready?: boolean;
    secret_configured?: boolean;
    line_items?: unknown[];
  };
};

export function getInvoicePreview(days = 30) {
  return request<Invoice>(`/v1/billing/invoice?days=${days}`);
}

export function createInvoice(days = 30, status = "draft") {
  return request<Invoice>("/v1/billing/invoices", {
    method: "POST",
    body: JSON.stringify({ days, status }),
  });
}

export function listInvoices(limit = 20) {
  return request<{ invoices: Invoice[] }>(`/v1/billing/invoices?limit=${limit}`);
}

export function invoiceMarkdownUrl(days = 30) {
  return `/v1/billing/invoice.md?days=${days}`;
}

export type CheckoutResult = {
  checkout: {
    id: string;
    url?: string;
    status?: string;
    dry_run?: boolean;
    amount_total?: number;
    currency?: string;
    note?: string;
  };
  record_id: string;
  invoice_id: string;
  invoice_number?: string;
  stripe_configured: boolean;
};

export function createCheckout(invoiceId: string, dryRun?: boolean) {
  return request<CheckoutResult>(`/v1/billing/invoices/${invoiceId}/checkout`, {
    method: "POST",
    body: JSON.stringify(dryRun === undefined ? {} : { dry_run: dryRun }),
  });
}

export function listCheckouts(limit = 10) {
  return request<{
    checkouts: Array<{
      id: string;
      invoice_id?: string;
      stripe_session_id: string;
      status: string;
      url?: string;
      amount_total_cents?: number;
      currency?: string;
      payment_status?: string;
      paid_at?: string;
      created_at?: string;
    }>;
  }>(`/v1/billing/checkouts?limit=${limit}`);
}

export function simulateCheckoutPaid(stripeSessionId: string) {
  return request<Record<string, unknown>>("/v1/billing/checkouts/simulate-paid", {
    method: "POST",
    body: JSON.stringify({ stripe_session_id: stripeSessionId }),
  });
}

export type QuotaStatus = {
  tenant_id: string;
  enforcement: boolean;
  limits: {
    tenant_id?: string;
    max_tasks_per_day: number;
    max_agent_runs_per_day: number;
    max_concurrent_tasks: number;
    max_estimated_usd_per_month: number;
    enabled: boolean;
    exists?: boolean;
    updated_at?: string | null;
  };
  usage: {
    tasks_today: number;
    agent_runs_today: number;
    concurrent_tasks: number;
    estimated_usd_30d: number;
    as_of?: string;
  };
  headroom: {
    tasks_today: number;
    agent_runs_today: number;
    concurrent_tasks: number;
    estimated_usd_30d: number;
  };
};

export function getQuotaStatus() {
  return request<QuotaStatus>("/v1/quotas");
}

export function updateQuota(body: {
  max_tasks_per_day?: number;
  max_agent_runs_per_day?: number;
  max_concurrent_tasks?: number;
  max_estimated_usd_per_month?: number;
  enabled?: boolean;
}) {
  return request<QuotaStatus["limits"]>("/v1/quotas", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export type EgressPolicy = {
  tenant_id: string;
  mode: "open" | "allowlist" | "denylist" | string;
  patterns: string;
  pattern_list?: string[];
  enabled: boolean;
  exists?: boolean;
  enforcement?: boolean;
  updated_at?: string | null;
};

export function getEgressPolicy() {
  return request<EgressPolicy>("/v1/egress");
}

export function updateEgress(body: {
  mode?: string;
  patterns?: string;
  enabled?: boolean;
}) {
  return request<EgressPolicy>("/v1/egress", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export { API_BASE, API_KEY };
