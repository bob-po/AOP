"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  createApiKey,
  createCheckout,
  createInvoice,
  getBillingUsage,
  getEgressPolicy,
  getGatewayHealth,
  getInvoicePreview,
  getQuotaStatus,
  getRbacMe,
  invoiceMarkdownUrl,
  listApiKeys,
  listAuditLogs,
  listCheckouts,
  listInvoices,
  listRbacRoles,
  probeHealth,
  revokeApiKey,
  simulateCheckoutPaid,
  updateEgress,
  updateQuota,
  type ApiKeyRecord,
  type AuditLogEntry,
  type BillingUsage,
  type CheckoutResult,
  type EgressPolicy,
  type Invoice,
  type QuotaStatus,
  type RbacRole,
} from "@/lib/api";
import { TenantPanel } from "@/components/settings/TenantPanel";
import { GovernancePanel } from "@/components/settings/GovernancePanel";

const TABS = [
  { id: "tenant", label: "租户" },
  { id: "governance", label: "治理" },
  { id: "keys", label: "API Keys" },
  { id: "rbac", label: "权限" },
  { id: "billing", label: "用量" },
  { id: "quotas", label: "配额" },
  { id: "egress", label: "出站" },
  { id: "monitor", label: "监控" },
  { id: "storage", label: "存储" },
  { id: "audit", label: "审计" },
] as const;

type TabId = (typeof TABS)[number]["id"];

const FALLBACK_ROLES: RbacRole[] = [
  { role: "viewer", scopes: ["task.read", "agent.read", "memory.read"] },
  {
    role: "operator",
    scopes: [
      "task.read",
      "task.write",
      "agent.read",
      "agent.write",
      "memory.read",
      "memory.write",
    ],
  },
  { role: "admin", scopes: ["*"] },
];

function usd(n: number | undefined) {
  return `$${(n ?? 0).toFixed(4)}`;
}

export function SettingsPageView() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const tabFromUrl = searchParams.get("tab") as TabId | null;
  const rootFromUrl = searchParams.get("root_task_id");
  const [tab, setTab] = useState<TabId>(
    tabFromUrl && TABS.some((t) => t.id === tabFromUrl) ? tabFromUrl : "keys",
  );
  const [keys, setKeys] = useState<ApiKeyRecord[]>([]);
  const [roles, setRoles] = useState<RbacRole[]>(FALLBACK_ROLES);
  const [me, setMe] = useState<Record<string, unknown> | null>(null);
  const [audits, setAudits] = useState<AuditLogEntry[]>([]);
  const [billing, setBilling] = useState<BillingUsage | null>(null);
  const [billingDays, setBillingDays] = useState(30);
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [lastCheckout, setLastCheckout] = useState<CheckoutResult | null>(null);
  const [checkouts, setCheckouts] = useState<
    Array<{
      id: string;
      stripe_session_id: string;
      status: string;
      payment_status?: string;
      paid_at?: string;
    }>
  >([]);
  const [quota, setQuota] = useState<QuotaStatus | null>(null);
  const [egress, setEgress] = useState<EgressPolicy | null>(null);
  const [egressForm, setEgressForm] = useState({
    mode: "open",
    patterns: "",
    enabled: true,
  });
  const [quotaForm, setQuotaForm] = useState({
    max_tasks_per_day: 100,
    max_agent_runs_per_day: 500,
    max_concurrent_tasks: 20,
    max_estimated_usd_per_month: 100,
    enabled: true,
  });
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("console-key");
  const [role, setRole] = useState("operator");
  const [createdPlain, setCreatedPlain] = useState<string | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [probe, setProbe] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (tabFromUrl && TABS.some((t) => t.id === tabFromUrl)) {
      setTab(tabFromUrl);
    }
  }, [tabFromUrl]);

  function selectTab(id: TabId) {
    setTab(id);
    const q = new URLSearchParams(searchParams.toString());
    q.set("tab", id);
    router.replace(`/settings?${q.toString()}`);
  }

  async function loadKeys() {
    try {
      const data = await listApiKeys();
      setKeys(data.api_keys || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load keys failed");
    }
  }

  async function loadRbac() {
    try {
      const [r, m] = await Promise.all([listRbacRoles(), getRbacMe()]);
      if (r.roles?.length) setRoles(r.roles);
      setMe(m as unknown as Record<string, unknown>);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load rbac failed");
    }
  }

  async function loadAudits() {
    try {
      const data = await listAuditLogs(40);
      setAudits(data.audit_logs || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load audit failed");
    }
  }

  async function loadBilling(days = billingDays) {
    try {
      const [data, inv, listed, cos] = await Promise.all([
        getBillingUsage(days),
        getInvoicePreview(days),
        listInvoices(10).catch(() => ({ invoices: [] as Invoice[] })),
        listCheckouts(10).catch(() => ({ checkouts: [] })),
      ]);
      setBilling(data);
      setInvoice(inv);
      setInvoices(listed.invoices || []);
      setCheckouts(cos.checkouts || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load billing failed");
    }
  }

  async function onCreateInvoice() {
    setBusy(true);
    try {
      await createInvoice(billingDays, "draft");
      await loadBilling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "create invoice failed");
    } finally {
      setBusy(false);
    }
  }

  async function onCheckout(invoiceId: string, dryRun?: boolean) {
    setBusy(true);
    try {
      const result = await createCheckout(invoiceId, dryRun);
      setLastCheckout(result);
      setError(null);
      if (result.checkout?.url && !result.checkout.dry_run) {
        window.open(result.checkout.url, "_blank", "noopener,noreferrer");
      }
      await loadBilling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "checkout failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSimulatePaid(sessionId: string) {
    setBusy(true);
    try {
      await simulateCheckoutPaid(sessionId);
      await loadBilling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "simulate paid failed");
    } finally {
      setBusy(false);
    }
  }

  async function loadQuota() {
    try {
      const data = await getQuotaStatus();
      setQuota(data);
      setQuotaForm({
        max_tasks_per_day: data.limits.max_tasks_per_day,
        max_agent_runs_per_day: data.limits.max_agent_runs_per_day,
        max_concurrent_tasks: data.limits.max_concurrent_tasks,
        max_estimated_usd_per_month: data.limits.max_estimated_usd_per_month,
        enabled: data.limits.enabled,
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load quotas failed");
    }
  }

  async function loadEgress() {
    try {
      const data = await getEgressPolicy();
      setEgress(data);
      setEgressForm({
        mode: data.mode || "open",
        patterns: data.patterns || "",
        enabled: data.enabled,
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load egress failed");
    }
  }

  useEffect(() => {
    if (tab === "keys") loadKeys();
    if (tab === "rbac") loadRbac();
    if (tab === "audit") loadAudits();
    if (tab === "billing") loadBilling();
    if (tab === "quotas") loadQuota();
    if (tab === "egress") loadEgress();
    if (tab === "monitor") {
      getGatewayHealth()
        .then((h) => setHealth(h as unknown as Record<string, unknown>))
        .catch(() => setHealth(null));
    }
  }, [tab]);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setCreatedPlain(null);
    try {
      const rec = await createApiKey(name.trim() || "api-key", { role });
      setCreatedPlain(rec.api_key || null);
      await loadKeys();
    } catch (err) {
      setError(err instanceof Error ? err.message : "create failed");
    } finally {
      setBusy(false);
    }
  }

  async function onRevoke(id: string) {
    setBusy(true);
    try {
      await revokeApiKey(id);
      await loadKeys();
    } catch (err) {
      setError(err instanceof Error ? err.message : "revoke failed");
    } finally {
      setBusy(false);
    }
  }

  async function onProbe() {
    setBusy(true);
    try {
      const data = await probeHealth();
      setProbe(`probed ${data.probed}, online ${data.online}`);
      const h = await getGatewayHealth();
      setHealth(h as unknown as Record<string, unknown>);
    } catch (err) {
      setError(err instanceof Error ? err.message : "probe failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSaveQuota(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await updateQuota(quotaForm);
      await loadQuota();
    } catch (err) {
      setError(err instanceof Error ? err.message : "save quota failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSaveEgress(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await updateEgress(egressForm);
      await loadEgress();
    } catch (err) {
      setError(err instanceof Error ? err.message : "save egress failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="px-4 py-6 md:px-8">
      <h1 className="font-display text-3xl text-mist-100">系统设置</h1>
      <p className="mt-1 text-sm text-mist-400">租户、密钥、角色权限与基础运维配置。</p>

      <div className="mt-5 flex flex-wrap gap-1 border-b border-white/10 pb-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => selectTab(t.id)}
            className={`rounded-lg px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] ${
              tab === t.id ? "bg-signal/15 text-signal" : "text-mist-400"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error ? <div className="mt-4 font-mono text-xs text-signal-warm">{error}</div> : null}

      <div className="mt-6 max-w-3xl">
        {tab === "tenant" ? <TenantPanel /> : null}

        {tab === "governance" ? (
          <GovernancePanel initialRootTaskId={rootFromUrl} />
        ) : null}

        {tab === "keys" ? (
          <div className="space-y-5">
            <form onSubmit={onCreate} className="flex flex-wrap items-end gap-2">
              <label className="block">
                <span className="font-mono text-[10px] uppercase text-mist-400">名称</span>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="mt-1 block rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 text-sm text-mist-100"
                />
              </label>
              <label className="block">
                <span className="font-mono text-[10px] uppercase text-mist-400">角色</span>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="mt-1 block rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 text-sm text-mist-100"
                >
                  {roles.map((r) => (
                    <option key={r.role} value={r.role}>
                      {r.role}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="submit"
                disabled={busy}
                className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase text-ink-950 disabled:opacity-40"
              >
                创建
              </button>
            </form>
            {createdPlain ? (
              <div className="rounded-xl border border-signal/30 bg-signal/10 p-3 font-mono text-xs text-signal">
                明文密钥（仅显示一次）：{createdPlain}
              </div>
            ) : null}
            <div className="divide-y divide-white/10 border-y border-white/10">
              {keys.map((k) => (
                <div key={k.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <div>
                    <div className="text-sm text-mist-100">{k.name}</div>
                    <div className="font-mono text-[11px] text-mist-400">
                      {k.key_prefix}… · {k.status} · {(k.scopes || []).join(",")}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={busy || k.status === "revoked"}
                    onClick={() => onRevoke(k.id)}
                    className="rounded-lg border border-white/15 px-3 py-1 font-mono text-[10px] uppercase text-mist-300 disabled:opacity-40"
                  >
                    撤销
                  </button>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {tab === "rbac" ? (
          <div className="space-y-5">
            <div className="overflow-hidden rounded-2xl border border-white/10">
              <table className="w-full text-left text-sm">
                <thead className="bg-ink-900/80 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-400">
                  <tr>
                    <th className="px-4 py-3">Role</th>
                    <th className="px-4 py-3">Scopes</th>
                  </tr>
                </thead>
                <tbody>
                  {roles.map((r) => (
                    <tr key={r.role} className="border-t border-white/10">
                      <td className="px-4 py-3 font-mono text-signal-dim">{r.role}</td>
                      <td className="px-4 py-3 font-mono text-xs text-mist-300">
                        {(r.scopes || []).join(", ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="border-t border-white/10 px-4 py-3 text-xs text-mist-400">
                创建 API Key 时可选择角色；网关鉴权时展开为具体 scopes。
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
                当前身份 /v1/rbac/me
              </div>
              <pre className="mt-2 overflow-auto font-mono text-[11px] text-mist-300">
                {JSON.stringify(me, null, 2) || "—"}
              </pre>
            </div>
          </div>
        ) : null}

        {tab === "billing" ? (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              {[7, 30, 90].map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => {
                    setBillingDays(d);
                    loadBilling(d);
                  }}
                  className={`rounded-lg px-3 py-1.5 font-mono text-[11px] uppercase ${
                    billingDays === d
                      ? "bg-signal/15 text-signal"
                      : "border border-white/10 text-mist-400"
                  }`}
                >
                  {d}d
                </button>
              ))}
              <button
                type="button"
                onClick={() => loadBilling()}
                className="ml-auto font-mono text-[10px] uppercase text-signal"
              >
                刷新
              </button>
            </div>
            {billing ? (
              <>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
                    <div className="font-mono text-[10px] uppercase text-mist-400">
                      预估合计
                    </div>
                    <div className="mt-2 font-mono text-2xl text-signal">
                      {usd(billing.estimated_total_usd)}
                    </div>
                    <div className="mt-1 font-mono text-[10px] text-mist-500">
                      {billing.currency} · {billing.window_days}d
                    </div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
                    <div className="font-mono text-[10px] uppercase text-mist-400">
                      Tasks
                    </div>
                    <div className="mt-2 font-mono text-2xl text-mist-100">
                      {billing.tasks?.total ?? 0}
                    </div>
                    <div className="mt-1 font-mono text-[10px] text-mist-500">
                      {usd(billing.task_cost_usd)} · done{" "}
                      {billing.tasks?.completed ?? 0}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
                    <div className="font-mono text-[10px] uppercase text-mist-400">
                      Agent Runs
                    </div>
                    <div className="mt-2 font-mono text-2xl text-mist-100">
                      {billing.agent_runs?.total ?? 0}
                    </div>
                    <div className="mt-1 font-mono text-[10px] text-mist-500">
                      {usd(billing.agent_runs?.estimated_cost_usd)}
                    </div>
                  </div>
                </div>
                <div className="overflow-hidden rounded-2xl border border-white/10">
                  <div className="border-b border-white/10 px-4 py-3 font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
                    By Skill
                  </div>
                  {(billing.agent_runs?.by_skill || []).length === 0 ? (
                    <p className="px-4 py-8 text-center text-sm text-mist-400">
                      窗口内无 agent runs
                    </p>
                  ) : (
                    <table className="w-full text-left text-sm">
                      <thead className="bg-ink-900/80 font-mono text-[10px] uppercase text-mist-400">
                        <tr>
                          <th className="px-4 py-2">Skill</th>
                          <th className="px-4 py-2">Runs</th>
                          <th className="px-4 py-2">Unit</th>
                          <th className="px-4 py-2">Est.</th>
                        </tr>
                      </thead>
                      <tbody>
                        {billing.agent_runs.by_skill.map((row) => (
                          <tr key={row.skill} className="border-t border-white/10">
                            <td className="px-4 py-2 font-mono text-xs text-signal-dim">
                              {row.skill}
                            </td>
                            <td className="px-4 py-2 font-mono text-xs text-mist-300">
                              {row.runs}
                            </td>
                            <td className="px-4 py-2 font-mono text-xs text-mist-400">
                              {usd(row.unit_price_usd)}
                            </td>
                            <td className="px-4 py-2 font-mono text-xs text-mist-200">
                              {usd(row.estimated_cost_usd)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
                <p className="text-xs text-mist-500">{billing.note}</p>
                {invoice ? (
                  <div className="space-y-3 rounded-2xl border border-white/10 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
                        Invoice Preview {invoice.invoice_number}
                      </div>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={onCreateInvoice}
                        className="ml-auto rounded-lg border border-signal/30 px-3 py-1 font-mono text-[10px] uppercase text-signal disabled:opacity-40"
                      >
                        保存快照
                      </button>
                      <a
                        href={invoiceMarkdownUrl(billingDays)}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-lg border border-white/15 px-3 py-1 font-mono text-[10px] uppercase text-mist-300"
                      >
                        Markdown
                      </a>
                    </div>
                    <div className="font-mono text-sm text-mist-100">
                      Total {usd(invoice.total_usd)} · {invoice.line_items?.length || 0} lines
                    </div>
                    <div className="font-mono text-[10px] text-mist-500">
                      Stripe checkout ready:{" "}
                      {invoice.stripe?.checkout_ready ? "yes" : "no"} · secret{" "}
                      {invoice.stripe?.secret_configured ? "set" : "unset"}
                    </div>
                    {lastCheckout ? (
                      <div className="rounded-xl border border-white/10 bg-ink-950 p-3 font-mono text-[11px] text-mist-300">
                        Last checkout: {lastCheckout.checkout.id} ·{" "}
                        {lastCheckout.checkout.dry_run ? "dry-run" : "live"} ·{" "}
                        {lastCheckout.checkout.url ? (
                          <a
                            href={lastCheckout.checkout.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-signal"
                          >
                            open
                          </a>
                        ) : (
                          "no url"
                        )}
                      </div>
                    ) : null}
                    {invoices.length > 0 ? (
                      <div className="divide-y divide-white/10 border-t border-white/10 pt-2">
                        {invoices.map((inv) => (
                          <div
                            key={inv.id || inv.invoice_number}
                            className="flex flex-wrap items-center justify-between gap-2 py-2 font-mono text-[11px] text-mist-400"
                          >
                            <span>
                              {inv.invoice_number} · {usd(inv.total_usd)} · {inv.status}
                            </span>
                            {inv.id && (inv.total_usd || 0) > 0 ? (
                              <span className="flex gap-1">
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() => onCheckout(inv.id!, true)}
                                  className="rounded border border-white/15 px-2 py-0.5 uppercase text-mist-300 disabled:opacity-40"
                                >
                                  Dry-run
                                </button>
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() => onCheckout(inv.id!)}
                                  className="rounded border border-signal/30 px-2 py-0.5 uppercase text-signal disabled:opacity-40"
                                >
                                  Checkout
                                </button>
                              </span>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {checkouts.length > 0 ? (
                      <div className="space-y-2 border-t border-white/10 pt-3">
                        <div className="font-mono text-[10px] uppercase text-mist-400">
                          Checkout Sessions
                        </div>
                        {checkouts.map((c) => (
                          <div
                            key={c.id}
                            className="flex flex-wrap items-center justify-between gap-2 font-mono text-[11px] text-mist-400"
                          >
                            <span>
                              {c.stripe_session_id.slice(0, 24)}… · {c.status}
                              {c.paid_at ? " · paid" : ""}
                            </span>
                            {c.status !== "paid" ? (
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => onSimulatePaid(c.stripe_session_id)}
                                className="rounded border border-white/15 px-2 py-0.5 uppercase text-mist-300 disabled:opacity-40"
                              >
                                Mark paid
                              </button>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : (
              <p className="text-sm text-mist-400">加载中…</p>
            )}
          </div>
        ) : null}

        {tab === "quotas" ? (
          <div className="space-y-5">
            {quota ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
                  <div className="font-mono text-[10px] uppercase text-mist-400">
                    Today / Concurrent
                  </div>
                  <div className="mt-2 font-mono text-sm text-mist-100">
                    tasks {quota.usage.tasks_today}/{quota.limits.max_tasks_per_day}
                  </div>
                  <div className="mt-1 font-mono text-sm text-mist-100">
                    runs {quota.usage.agent_runs_today}/{quota.limits.max_agent_runs_per_day}
                  </div>
                  <div className="mt-1 font-mono text-sm text-mist-100">
                    concurrent {quota.usage.concurrent_tasks}/
                    {quota.limits.max_concurrent_tasks}
                  </div>
                </div>
                <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-4">
                  <div className="font-mono text-[10px] uppercase text-mist-400">
                    30d Est. USD
                  </div>
                  <div className="mt-2 font-mono text-2xl text-signal">
                    ${quota.usage.estimated_usd_30d.toFixed(4)}
                  </div>
                  <div className="mt-1 font-mono text-[10px] text-mist-500">
                    limit ${quota.limits.max_estimated_usd_per_month.toFixed(2)} ·
                    enforcement {quota.enforcement ? "on" : "off"}
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-mist-400">加载中…</p>
            )}
            <form onSubmit={onSaveQuota} className="space-y-3 rounded-2xl border border-white/10 p-4">
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
                Edit Limits
              </div>
              {(
                [
                  ["max_tasks_per_day", "Tasks / day"],
                  ["max_agent_runs_per_day", "Runs / day"],
                  ["max_concurrent_tasks", "Concurrent"],
                  ["max_estimated_usd_per_month", "USD / 30d"],
                ] as const
              ).map(([key, label]) => (
                <label key={key} className="block">
                  <span className="font-mono text-[10px] uppercase text-mist-400">{label}</span>
                  <input
                    type="number"
                    step={key.includes("usd") ? "0.01" : "1"}
                    value={quotaForm[key]}
                    onChange={(e) =>
                      setQuotaForm((f) => ({
                        ...f,
                        [key]: key.includes("usd")
                          ? Number(e.target.value)
                          : parseInt(e.target.value || "0", 10),
                      }))
                    }
                    className="mt-1 block w-full rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 text-sm text-mist-100"
                  />
                </label>
              ))}
              <label className="flex items-center gap-2 font-mono text-xs text-mist-300">
                <input
                  type="checkbox"
                  checked={quotaForm.enabled}
                  onChange={(e) =>
                    setQuotaForm((f) => ({ ...f, enabled: e.target.checked }))
                  }
                />
                enabled
              </label>
              <button
                type="submit"
                disabled={busy}
                className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase text-ink-950 disabled:opacity-40"
              >
                保存
              </button>
            </form>
          </div>
        ) : null}

        {tab === "egress" ? (
          <form onSubmit={onSaveEgress} className="space-y-4 rounded-2xl border border-white/10 p-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
              Browser 出站 · enforcement {egress?.enforcement ? "on" : "off"}
            </div>
            <p className="text-xs text-mist-500">
              作用于 skill <span className="font-mono">browser-automation</span> 文本中的 URL。
              模式 open / allowlist / denylist。通配 <span className="font-mono">*.example.com</span>。
            </p>
            <label className="block">
              <span className="font-mono text-[10px] uppercase text-mist-400">Mode</span>
              <select
                value={egressForm.mode}
                onChange={(e) => setEgressForm((f) => ({ ...f, mode: e.target.value }))}
                className="mt-1 block w-full rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 text-sm text-mist-100"
              >
                <option value="open">open</option>
                <option value="allowlist">allowlist</option>
                <option value="denylist">denylist</option>
              </select>
            </label>
            <label className="block">
              <span className="font-mono text-[10px] uppercase text-mist-400">Patterns</span>
              <input
                value={egressForm.patterns}
                onChange={(e) => setEgressForm((f) => ({ ...f, patterns: e.target.value }))}
                placeholder="example.com, *.wikipedia.org"
                className="mt-1 block w-full rounded-xl border border-white/10 bg-ink-800/60 px-3 py-2 text-sm text-mist-100"
              />
            </label>
            <label className="flex items-center gap-2 font-mono text-xs text-mist-300">
              <input
                type="checkbox"
                checked={egressForm.enabled}
                onChange={(e) => setEgressForm((f) => ({ ...f, enabled: e.target.checked }))}
              />
              enabled
            </label>
            <button
              type="submit"
              disabled={busy}
              className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase text-ink-950 disabled:opacity-40"
            >
              保存
            </button>
          </form>
        ) : null}

        {tab === "monitor" ? (
          <div className="space-y-4 rounded-2xl border border-white/10 bg-ink-900/50 p-5">
            <button
              type="button"
              disabled={busy}
              onClick={onProbe}
              className="rounded-xl border border-signal/30 px-4 py-2 font-mono text-xs uppercase tracking-[0.14em] text-signal"
            >
              运行 Health Probe
            </button>
            {probe ? <div className="font-mono text-xs text-mist-200">{probe}</div> : null}
            <pre className="overflow-auto rounded-xl border border-white/10 bg-ink-950 p-3 font-mono text-[11px] text-mist-300">
              {JSON.stringify(health, null, 2) || "—"}
            </pre>
          </div>
        ) : null}

        {tab === "storage" ? (
          <div className="rounded-2xl border border-white/10 bg-ink-900/50 p-5 text-sm text-mist-300">
            <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
              MinIO（开发默认）
            </div>
            <ul className="mt-3 space-y-1 font-mono text-xs">
              <li>Endpoint: 127.0.0.1:9000</li>
              <li>Bucket: aop-artifacts</li>
              <li>Path: s3://aop-artifacts/tasks/{"{task_id}"}/{"{node}"}/…</li>
              <li>Console: http://127.0.0.1:9001</li>
            </ul>
          </div>
        ) : null}

        {tab === "audit" ? (
          <div className="overflow-hidden rounded-2xl border border-white/10">
            <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
                Audit Logs
              </div>
              <button
                type="button"
                onClick={loadAudits}
                className="font-mono text-[10px] uppercase text-signal"
              >
                刷新
              </button>
            </div>
            {audits.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-mist-400">暂无审计记录</p>
            ) : (
              <div className="divide-y divide-white/10">
                {audits.map((a) => (
                  <div key={a.id} className="px-4 py-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-mono text-sm text-signal-dim">{a.action}</span>
                      <span className="font-mono text-[10px] text-mist-500">
                        {a.created_at || ""}
                      </span>
                    </div>
                    <div className="mt-1 font-mono text-[11px] text-mist-400">
                      {[a.resource_type, a.resource_id].filter(Boolean).join(" · ") || "—"}
                      {a.ip ? ` · ${a.ip}` : ""}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
