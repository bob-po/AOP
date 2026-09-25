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
  handoff?: Record<string, unknown> | null;
  checkpoint_at?: string | null;
  checkpoint_attempt?: number | null;
  checkpoint_artifact_ids?: string[] | null;
  checkpoint_error?: string | null;
  checkpoint_status?: string | null;
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
  /** Phase 3+ execution snapshot when returned by orchestrator */
  execution?: {
    execute?: { root_task_id?: string; state?: string; [key: string]: unknown } | null;
    delegate?: { root_task_id?: string; [key: string]: unknown } | null;
    [key: string]: unknown;
  } | null;
  collaboration_graph?: unknown;
  runtime_graph?: unknown;
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

export function getTask(taskId: string, opts?: { include_graph?: boolean }) {
  const q = opts?.include_graph ? "?include_graph=true" : "";
  return request<TaskDetail>(`/v1/tasks/${taskId}${q}`);
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

export type MarketplaceInstallMeta = {
  download?: string;
  install_ps1?: string;
  install_sh?: string;
  windows?: string;
  unix?: string;
  windows_full?: string;
  unix_full?: string;
};

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
  /** Virtual agent: harness × role profile */
  harness?: string;
  profile?: string;
  default_port?: number;
  bundle?: boolean;
  download_url?: string;
  install?: MarketplaceInstallMeta;
  agent?: {
    agent_id: string;
    agent_key: string;
    status: string;
    endpoint?: string;
    skills?: string[];
  } | null;
};

/** Prefer Gateway-reachable one-liners (same host as NEXT_PUBLIC_API_BASE). */
export function marketplaceDeployCommands(pkg: MarketplacePackage) {
  const base = API_BASE.replace(/\/$/, "");
  const id = pkg.package_id;
  const profile = pkg.profile || pkg.agent_key || id.replace(/^pkg-/, "");
  const fromApi = pkg.install;
  return {
    windows:
      fromApi?.windows_full ||
      `irm ${base}/v1/marketplace/agents/${id}/install.ps1 | iex`,
    unix:
      fromApi?.unix_full ||
      `curl -fsSL ${base}/v1/marketplace/agents/${id}/install.sh | bash`,
    windowsShort: fromApi?.windows || `irm ${base}/install/${profile}.ps1 | iex`,
    unixShort: fromApi?.unix || `curl -fsSL ${base}/install/${profile}.sh | bash`,
    download:
      fromApi?.download ||
      pkg.download_url ||
      `${base}/v1/marketplace/agents/${id}/download`,
  };
}

export async function downloadMarketplaceBundle(
  packageId: string,
  filename?: string,
): Promise<void> {
  const headers: Record<string, string> = {};
  const token = authHeader();
  if (token) {
    headers.Authorization = token.startsWith("Bearer ") ? token : `Bearer ${token}`;
  }
  const res = await fetch(
    `${API_BASE}/v1/marketplace/agents/${encodeURIComponent(packageId)}/download`,
    { headers, cache: "no-store" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${text}`);
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/i.exec(cd);
  const name = filename || match?.[1] || `${packageId}.zip`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

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

export function approveTask(
  taskId: string,
  nodeKey?: string,
  humanInput?: string,
) {
  return request<{
    task_id: string;
    node_key: string;
    approved: boolean;
    has_human_input?: boolean;
    status?: string;
    enqueued_nodes?: string[];
  }>(`/v1/tasks/${taskId}/approve`, {
    method: "POST",
    body: JSON.stringify({
      node_key: nodeKey || null,
      input: humanInput?.trim() || null,
    }),
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

// ─── A2A OS (Phase 1–6) ───────────────────────────────────────────────────

const ORCHESTRATOR_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_ORCHESTRATOR_BASE) || "";

const DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001";

/** Human-readable API error (403 cross-tenant, 404/503, etc.). */
export function apiErrorMessage(err: unknown, fallback = "请求失败"): string {
  const raw = err instanceof Error ? err.message : String(err || fallback);
  if (/^403\b/.test(raw) || /\b403\b/.test(raw)) {
    return "无权访问其他租户数据";
  }
  if (/^404\b/.test(raw)) return "资源不存在或接口未部署";
  if (/^503\b/.test(raw)) return "服务暂不可用";
  if (/failed to fetch|network|timeout|AbortError/i.test(raw)) {
    return "网络超时或无法连接网关";
  }
  // Strip leading status code for display
  const m = raw.match(/^\d{3}\s+([\s\S]*)/);
  if (m) {
    const body = m[1].trim();
    if (body.length > 180) return body.slice(0, 180) + "…";
    return body || fallback;
  }
  return raw || fallback;
}

export function getDefaultTenantId() {
  return (
    (typeof process !== "undefined" && process.env.NEXT_PUBLIC_DEFAULT_TENANT_ID) ||
    DEFAULT_TENANT_ID
  );
}

async function requestAbsolute<T>(
  base: string,
  path: string,
  init?: RequestInit & { __sessionRetried?: boolean },
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  const token = authHeader();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${base.replace(/\/$/, "")}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    if (
      res.status === 401 &&
      token &&
      isSessionToken(token) &&
      !init?.__sessionRetried
    ) {
      setSessionToken(null);
      const { __sessionRetried: _ignored, ...rest } = init || {};
      return requestAbsolute<T>(base, path, { ...rest, __sessionRetried: true });
    }
    throw new Error(`${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

/** Prefer Orchestrator direct base when set (local dev for capacity/reliability). */
function requestOrchPreferred<T>(path: string, init?: RequestInit) {
  if (ORCHESTRATOR_BASE) {
    return requestAbsolute<T>(ORCHESTRATOR_BASE, path, init);
  }
  return request<T>(path, init);
}

// Discover / Route
export type DiscoverCandidate = {
  agent_id: string;
  agent_key?: string;
  name?: string;
  status?: string;
  endpoint?: string;
  skills?: string[];
  priority?: number;
  score?: number;
  score_breakdown?: Record<string, number>;
  source?: string;
  [key: string]: unknown;
};

export type DiscoverResult = {
  required_skills?: string[];
  match_all_skills?: boolean;
  capabilities?: Record<string, unknown>;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  tenant_id?: string;
  candidates: DiscoverCandidate[];
  selected?: string | null;
  selected_agent?: DiscoverCandidate | null;
  filter_stats?: Record<string, unknown>;
};

export type DiscoverRequest = {
  required_skills?: string[];
  capabilities?: Record<string, unknown>;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  match_all_skills?: boolean;
  exclude_agent_ids?: string[];
  limit?: number;
};

export function discoverAgents(body: DiscoverRequest) {
  return request<DiscoverResult>("/v1/discover", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function routeRequest(body: DiscoverRequest & { skill?: string }) {
  return request<DiscoverResult>("/v1/route", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Runtime / Collaboration
export type RuntimeEdgeInput = {
  caller_agent_id: string;
  target_agent_id: string;
  root_task_id?: string;
  parent_task_id?: string;
  task_id?: string;
  correlation_id?: string;
  skill?: string;
  depth?: number;
  status?: string;
  tenant_id?: string;
};

export type CollaborationNode = {
  id: string;
  type: "agent" | "task" | string;
  label?: string;
  role?: "caller" | "target" | string;
  task_id?: string;
  status?: string;
  skill?: string;
  depth?: number;
  agent_id?: string;
  state?: string;
  active_tasks?: number;
  last_seen?: string;
  task_count?: number;
  [key: string]: unknown;
};

export type CollaborationLink = {
  id: string;
  source: string;
  target: string;
  task_id?: string;
  parent_task_id?: string;
  skill?: string;
  /** Structured handoff reason: why this call happened */
  reason?: string;
  depth?: number;
  status?: string;
  correlation_id?: string;
  created_at?: string;
  [key: string]: unknown;
};

export type CollaborationGraph = {
  root_task_id: string;
  kind?: string;
  source?: string;
  node_count?: number;
  link_count?: number;
  max_depth?: number;
  agents?: string[];
  nodes: CollaborationNode[];
  links: CollaborationLink[];
  tree?: unknown[];
  edges?: unknown[];
};

export type RuntimeGraph = {
  root_task_id: string;
  edges?: unknown[];
  nodes?: unknown[];
  tree?: unknown[];
  agents?: string[];
  max_depth?: number;
};

export type ExecutionEventDict = {
  event_type?: string;
  event_id?: string;
  timestamp?: string;
  root_task_id?: string;
  correlation_id?: string;
  task_id?: string;
  agent_id?: string;
  parent_task_id?: string;
  payload?: Record<string, unknown>;
  sequence?: number;
  [key: string]: unknown;
};

export function recordRuntimeEdge(body: RuntimeEdgeInput) {
  return request<Record<string, unknown>>("/v1/runtime/edges", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getRuntimeGraph(rootTaskId: string) {
  return request<RuntimeGraph>(`/v1/runtime/graph/${encodeURIComponent(rootTaskId)}`);
}

export function getCollaborationGraph(rootTaskId: string) {
  return request<CollaborationGraph>(
    `/v1/collaboration/graph/${encodeURIComponent(rootTaskId)}`,
  );
}

export function getTaskCollaborationGraph(taskId: string) {
  return request<CollaborationGraph>(
    `/v1/tasks/${encodeURIComponent(taskId)}/collaboration-graph`,
  );
}

export function getCollaborationEvents(rootTaskId: string) {
  return request<{ root_task_id: string; events: ExecutionEventDict[]; count: number }>(
    `/v1/collaboration/events/${encodeURIComponent(rootTaskId)}`,
  );
}

// Governance
export type GovernanceCheckRequest = {
  root_task_id?: string;
  caller_agent_id: string;
  target_agent_id: string;
  caller_task_id?: string;
  correlation_id?: string;
  tenant_id?: string;
  requested_units?: number;
  units_estimated?: number;
  deadline?: string;
  claimed_depth?: number;
};

export type GovernanceCheckResult = {
  allowed: boolean;
  code?: string;
  reason?: string;
  context?: Record<string, unknown>;
  queued?: boolean;
  queue?: Record<string, unknown>;
};

export type GovernanceDenial = {
  code?: string;
  reason?: string;
  root_task_id?: string;
  caller_agent_id?: string;
  target_agent_id?: string;
  created_at?: string;
  timestamp?: string;
  context?: Record<string, unknown>;
  [key: string]: unknown;
};

export function governanceCheck(body: GovernanceCheckRequest) {
  return request<GovernanceCheckResult>("/v1/governance/check", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function governanceRelease(body?: Record<string, unknown>) {
  return request<{ released: boolean }>("/v1/governance/release", {
    method: "POST",
    body: JSON.stringify(body || {}),
  });
}

export function listGovernanceDenials(params?: {
  root_task_id?: string;
  code?: string;
  limit?: number;
}) {
  const q = new URLSearchParams();
  if (params?.root_task_id) q.set("root_task_id", params.root_task_id);
  if (params?.code) q.set("code", params.code);
  if (params?.limit != null) q.set("limit", String(params.limit));
  const qs = q.toString();
  return request<{ denials: GovernanceDenial[]; count: number }>(
    `/v1/governance/denials${qs ? `?${qs}` : ""}`,
  );
}

// Execution
export type ExecutionRecord = {
  state?: string;
  attempt?: number;
  max_retries?: number;
  agent_id?: string;
  operation?: string;
  idempotency_key?: string;
  ownership_token?: string;
  error?: string | null;
  branch_lineage?: unknown;
  visited_agents?: string[];
  created_at?: string;
  updated_at?: string;
  started_at?: string;
  finished_at?: string;
  [key: string]: unknown;
};

export type TaskExecutionView = {
  task_id: string;
  execute: ExecutionRecord | null;
  delegate: ExecutionRecord | null;
  events?: ExecutionEventDict[];
  recovery?: { class?: string; [key: string]: unknown } | string | null;
};

export function getTaskExecution(taskId: string) {
  return request<TaskExecutionView>(`/v1/tasks/${encodeURIComponent(taskId)}/execution`);
}

export function recoverTask(taskId: string) {
  return request<Record<string, unknown>>(`/v1/tasks/${encodeURIComponent(taskId)}/recover`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export type NodeCheckpoint = {
  id?: number;
  task_id?: string;
  node_id?: string;
  node_key: string;
  attempt: number;
  status: string;
  snapshot_json?: Record<string, unknown>;
  created_at?: string;
};

export function listTaskCheckpoints(
  taskId: string,
  params?: { node_key?: string; limit?: number },
) {
  const q = new URLSearchParams();
  if (params?.node_key) q.set("node_key", params.node_key);
  if (params?.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  return request<{ task_id: string; checkpoints: NodeCheckpoint[]; count: number }>(
    `/v1/tasks/${encodeURIComponent(taskId)}/checkpoints${qs ? `?${qs}` : ""}`,
  );
}

export function replayTaskNode(
  taskId: string,
  nodeKey: string,
  opts?: { clear_downstream?: boolean },
) {
  return request<{
    task_id: string;
    node_key: string;
    replayed: boolean;
    next_attempt?: number;
    cleared_downstream?: string[];
    enqueued_nodes?: string[];
    status?: string;
  }>(`/v1/tasks/${encodeURIComponent(taskId)}/nodes/${encodeURIComponent(nodeKey)}/replay`, {
    method: "POST",
    body: JSON.stringify({
      clear_downstream: opts?.clear_downstream !== false,
    }),
  });
}

// Agent runtime lifecycle (gateway-safe path for health/heartbeat/drain)
export type AgentRuntimeHealth = {
  agent_id?: string;
  state?: string;
  active_tasks?: number;
  last_seen?: string;
  load?: number;
  version?: string;
  max_concurrency?: number;
  [key: string]: unknown;
};

export type AgentCapacity = {
  agent_id: string;
  health?: AgentRuntimeHealth | Record<string, unknown>;
  queue_depth?: number;
  quota?: Record<string, unknown>;
  accepts?: boolean;
  reason?: string;
};

export type AgentReliability = {
  agent_id: string;
  sample_size?: number;
  availability?: number;
  success_rate?: number;
  note?: string;
};

export function getAgentRuntimeHealth(agentId: string) {
  return request<AgentRuntimeHealth>(
    `/v1/agent-runtime/${encodeURIComponent(agentId)}/health`,
  );
}

/** Prefer Gateway; optional NEXT_PUBLIC_ORCHESTRATOR_BASE for local bypass. */
export function getAgentCapacity(agentId: string) {
  return requestOrchPreferred<AgentCapacity>(
    `/v1/agents/${encodeURIComponent(agentId)}/capacity`,
  );
}

export function getAgentReliability(agentId: string) {
  return requestOrchPreferred<AgentReliability>(
    `/v1/agents/${encodeURIComponent(agentId)}/reliability`,
  );
}

export function heartbeatAgent(agentId: string, body?: Record<string, unknown>) {
  return request<AgentRuntimeHealth>(
    `/v1/agent-runtime/${encodeURIComponent(agentId)}/heartbeat`,
    { method: "POST", body: JSON.stringify(body || {}) },
  );
}

export function drainAgent(agentId: string) {
  return request<AgentRuntimeHealth>(
    `/v1/agent-runtime/${encodeURIComponent(agentId)}/drain`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

// Scheduling
export type ScheduleRequirement = {
  skill?: string;
  version_constraint?: string;
  input_types?: string[];
  output_types?: string[];
  require_gpu?: boolean;
  require_streaming?: boolean;
  [key: string]: unknown;
};

export type ScheduleDecision = {
  selected?: DiscoverCandidate | null;
  candidates?: DiscoverCandidate[];
  excluded?: Array<{ agent_id?: string; reason?: string }>;
  reason?: string;
  scores?: Record<string, unknown>;
  [key: string]: unknown;
};

export type SchedulePreviewResult = {
  preview?: boolean;
  decision?: ScheduleDecision;
  budget?: Record<string, unknown>;
  tenant_id?: string;
  selected?: DiscoverCandidate | null;
  reason?: string;
};

export type RecoveryPlan = {
  classification?: string;
  action?: "abort" | "reselect" | "retry_same" | string;
  exclude_agent_ids?: string[];
  reason?: string;
  [key: string]: unknown;
};

export function listSchedulingCandidates(skill: string, limit = 20) {
  const q = new URLSearchParams({ skill, limit: String(limit) });
  return request<{
    candidates: DiscoverCandidate[];
    excluded: Array<{ agent_id?: string; reason?: string }>;
    count: number;
    tenant_id?: string;
  }>(`/v1/scheduling/candidates?${q}`);
}

export function previewSchedule(body: {
  agents?: DiscoverCandidate[];
  requirement?: ScheduleRequirement;
  exclude_agent_ids?: string[];
  estimated_cost?: number;
  skill?: string;
}) {
  return request<SchedulePreviewResult>("/v1/scheduling/preview", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function selectSchedule(body: {
  agents?: DiscoverCandidate[];
  requirement?: ScheduleRequirement;
  exclude_agent_ids?: string[];
  estimated_cost?: number;
  skill?: string;
}) {
  return request<SchedulePreviewResult>("/v1/scheduling/select", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function simulateSchedule(body: Record<string, unknown>) {
  return request<Record<string, unknown>>("/v1/scheduling/simulate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getRecoveryPlan(body: {
  error_code?: string;
  error?: string;
  agent_id?: string;
  agent_state?: string;
  exclude_agent_ids?: string[];
}) {
  return request<RecoveryPlan>("/v1/scheduling/recovery-plan", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Cost
export type CostAggregate = {
  task_id?: string;
  root_task_id?: string;
  tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  gpu_seconds?: number;
  cpu_seconds?: number;
  wall_time_ms?: number;
  estimated_cost?: number;
  count?: number;
  [key: string]: unknown;
};

export type CostItem = {
  agent_id?: string;
  attempt?: number;
  tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  gpu_seconds?: number;
  cpu_seconds?: number;
  wall_time_ms?: number;
  estimated_cost?: number;
  [key: string]: unknown;
};

export type CostBreakdown = {
  root_task_id?: string;
  total?: CostAggregate;
  by_agent?: Record<string, CostAggregate>;
  items?: CostItem[];
};

export function getTaskCost(taskId: string) {
  return request<CostAggregate & { items?: CostItem[] }>(
    `/v1/tasks/${encodeURIComponent(taskId)}/cost`,
  );
}

export function getTaskCostBreakdown(taskId: string) {
  return request<CostBreakdown>(
    `/v1/tasks/${encodeURIComponent(taskId)}/cost/breakdown`,
  );
}

// Tenants
export type TenantBudgetScope = {
  limit?: number;
  spent?: number;
  remaining?: number;
  [key: string]: unknown;
};

export type TenantBudget = {
  tenant?: TenantBudgetScope;
  day?: TenantBudgetScope;
  month?: TenantBudgetScope;
  task?: TenantBudgetScope;
  [key: string]: TenantBudgetScope | undefined;
};

export type SchedulingPolicyDoc = {
  max_cost?: number;
  max_latency_ms?: number;
  require_gpu?: boolean;
  require_streaming?: boolean;
  priority?: number;
  tenant_weight?: number;
  [key: string]: unknown;
};

export function getTenantQuota(tenantId: string) {
  return request<QuotaStatus | Record<string, unknown>>(
    `/v1/tenants/${encodeURIComponent(tenantId)}/quota`,
  );
}

export function getTenantBudget(tenantId: string) {
  return request<TenantBudget>(`/v1/tenants/${encodeURIComponent(tenantId)}/budget`);
}

export function getTenantCost(tenantId: string) {
  return request<CostAggregate & { tenant_id?: string; trend?: Array<{ day: string; cost: number }> }>(
    `/v1/tenants/${encodeURIComponent(tenantId)}/cost`,
  );
}

export function getTenantPolicy(tenantId: string) {
  return request<{ tenant_id: string; policy: SchedulingPolicyDoc }>(
    `/v1/tenants/${encodeURIComponent(tenantId)}/policy`,
  );
}

export function setTenantPolicy(tenantId: string, policy: SchedulingPolicyDoc) {
  return request<{ tenant_id: string; policy: SchedulingPolicyDoc }>(
    `/v1/tenants/${encodeURIComponent(tenantId)}/policy`,
    { method: "POST", body: JSON.stringify({ policy }) },
  );
}

// Skills
export type SkillManifest = {
  name: string;
  version?: string;
  description?: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  requirements?: Record<string, unknown>;
  dependencies?: Record<string, unknown>;
  tags?: string[];
  status?: string;
  providers?: string[];
  [key: string]: unknown;
};

export function listSkills() {
  return request<{ skills: SkillManifest[] }>("/v1/skills");
}

export function getSkill(name: string) {
  return request<SkillManifest>(`/v1/skills/${encodeURIComponent(name)}`);
}

export function registerSkill(body: Partial<SkillManifest> & { name: string }) {
  return request<SkillManifest>("/v1/skills", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function searchSkills(body: {
  skill?: string;
  name?: string;
  q?: string;
  capability?: string;
  input?: string;
  output?: string;
  modality?: string;
  resource?: string;
  version?: string;
  tags?: string[];
}) {
  return request<{ skills: SkillManifest[]; count: number }>("/v1/skills/search", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function discoverBySkill(body: {
  skill: string;
  version?: string;
  version_constraint?: string;
}) {
  return request<Record<string, unknown>>("/v1/discover/skill", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function invokeBySkill(body: {
  skill: string;
  version?: string;
  version_constraint?: string;
}) {
  return request<Record<string, unknown>>("/v1/invoke/skill", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export { API_BASE, API_KEY, ORCHESTRATOR_BASE };
