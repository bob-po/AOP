"use client";

import { useEffect, useState } from "react";
import {
  disableAgent,
  downloadMarketplaceBundle,
  enableAgent,
  installMarketplacePackage,
  listMarketplace,
  marketplaceDeployCommands,
  probeHealth,
  type MarketplacePackage,
} from "@/lib/api";

function harnessLabel(harness?: string) {
  if (!harness) return null;
  if (harness === "claude_cli") return "Claude Code";
  if (harness === "pi_cli") return "Pi";
  if (harness === "deepseek") return "DeepSeek";
  return harness;
}

async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
}

export function MarketplacePanel({ embedded = false }: { embedded?: boolean }) {
  const [packages, setPackages] = useState<MarketplacePackage[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [probeMsg, setProbeMsg] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  async function reload(query?: string) {
    const data = await listMarketplace(query);
    setPackages(data.packages || []);
  }

  useEffect(() => {
    let alive = true;
    listMarketplace()
      .then((data) => {
        if (alive) {
          setPackages(data.packages || []);
          setError(null);
        }
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : "failed");
      });
    return () => {
      alive = false;
    };
  }, []);

  async function onRegister(pkg: MarketplacePackage) {
    setBusy(pkg.package_id);
    setError(null);
    try {
      await installMarketplacePackage(pkg.package_id);
      await reload(q);
    } catch (err) {
      setError(err instanceof Error ? err.message : "register failed");
    } finally {
      setBusy(null);
    }
  }

  async function onDownload(pkg: MarketplacePackage) {
    setBusy(`dl:${pkg.package_id}`);
    setError(null);
    try {
      const name = `${pkg.profile || pkg.agent_key || pkg.package_id}-${pkg.version || "0.1.0"}.zip`;
      await downloadMarketplaceBundle(pkg.package_id, name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "download failed");
    } finally {
      setBusy(null);
    }
  }

  async function onCopy(key: string, text: string) {
    try {
      await copyText(text);
      setCopied(key);
      window.setTimeout(() => setCopied((c) => (c === key ? null : c)), 1600);
    } catch {
      setError("clipboard unavailable");
    }
  }

  async function onToggle(pkg: MarketplacePackage) {
    const agentId = pkg.agent?.agent_id;
    if (!agentId) return;
    setBusy(pkg.package_id);
    setError(null);
    try {
      if (pkg.agent?.status === "disabled") {
        await enableAgent(agentId);
      } else {
        await disableAgent(agentId);
      }
      await reload(q);
    } catch (err) {
      setError(err instanceof Error ? err.message : "toggle failed");
    } finally {
      setBusy(null);
    }
  }

  async function onProbe() {
    setBusy("probe");
    setError(null);
    try {
      const data = await probeHealth();
      setProbeMsg(`probed ${data.probed}, online ${data.online}`);
      await reload(q);
    } catch (err) {
      setError(err instanceof Error ? err.message : "probe failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={embedded ? "pb-8" : "mx-auto max-w-5xl px-6 pb-16 pt-6 md:px-10"}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          {!embedded ? (
            <>
              <h1 className="font-display text-4xl text-mist-100">Marketplace</h1>
              <p className="mt-2 max-w-2xl text-sm text-mist-400">
                虚拟 Agent = harness × 角色画像。本机注册 endpoint，或像 Claude Code 一样一键安装到其他主机。
              </p>
            </>
          ) : (
            <p className="text-sm text-mist-400">
              虚拟 Agent（harness × 角色）。Register 写入注册表；Deploy 一键装到远端主机。
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onProbe}
          disabled={busy === "probe"}
          className="rounded-xl border border-signal/30 px-4 py-2 font-mono text-xs uppercase tracking-[0.16em] text-signal transition hover:bg-signal/10 disabled:opacity-40"
        >
          {busy === "probe" ? "Probing…" : "Probe Health"}
        </button>
      </div>

      <div className="mt-8 flex flex-wrap gap-3">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search skills, harness, profile…"
          className="min-w-[240px] flex-1 rounded-xl border border-white/10 bg-ink-800/70 px-4 py-2 text-sm text-mist-100 outline-none focus:border-signal/40"
        />
        <button
          type="button"
          onClick={() => reload(q).catch((err) => setError(String(err)))}
          className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-ink-950"
        >
          Search
        </button>
      </div>

      {probeMsg ? (
        <div className="mt-4 font-mono text-xs text-signal-dim">{probeMsg}</div>
      ) : null}
      {error ? <div className="mt-4 font-mono text-xs text-signal-warm">{error}</div> : null}

      <div className="mt-10 divide-y divide-white/10 border-y border-white/10">
        {packages.map((pkg) => {
          const cmds = marketplaceDeployCommands(pkg);
          const open = expanded === pkg.package_id;
          const hLabel = harnessLabel(pkg.harness);
          return (
            <div key={pkg.package_id} className="py-6">
              <div className="grid gap-4 md:grid-cols-[1.5fr_1fr_auto] md:items-start">
                <div>
                  <div className="font-display text-xl text-mist-100">{pkg.name}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-[11px] text-mist-400">
                    <span>
                      {pkg.publisher} · v{pkg.version} · {pkg.agent_key}
                    </span>
                    {hLabel ? (
                      <span className="rounded-full border border-signal/25 px-2 py-0.5 text-signal-dim">
                        {hLabel}
                        {pkg.profile ? ` × ${pkg.profile}` : ""}
                      </span>
                    ) : null}
                    {pkg.default_port ? (
                      <span className="text-mist-500">:{pkg.default_port}</span>
                    ) : null}
                  </div>
                  <p className="mt-2 text-sm text-mist-400">{pkg.description}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(pkg.skills || []).map((s) => (
                      <span
                        key={s}
                        className="rounded-full border border-signal/20 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-signal-dim"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="font-mono text-xs text-mist-400">
                  {pkg.installed ? (
                    <>
                      Registered ·{" "}
                      <span
                        className={
                          pkg.agent?.status === "online" || pkg.agent?.status === "running"
                            ? "text-signal"
                            : "text-signal-warm"
                        }
                      >
                        {pkg.agent?.status}
                      </span>
                    </>
                  ) : (
                    "Not in registry"
                  )}
                  <div className="mt-1 truncate text-[11px]">{pkg.default_endpoint}</div>
                </div>
                <div className="flex flex-col gap-2">
                  {!pkg.installed ? (
                    <button
                      type="button"
                      disabled={busy === pkg.package_id}
                      onClick={() => onRegister(pkg)}
                      className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-ink-950 disabled:opacity-40"
                      title="Register default_endpoint into tenant registry"
                    >
                      {busy === pkg.package_id ? "…" : "Register"}
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={busy === pkg.package_id}
                      onClick={() => onToggle(pkg)}
                      className="rounded-xl border border-white/15 px-4 py-2 font-mono text-xs uppercase tracking-[0.16em] text-mist-200 hover:border-signal/40 hover:text-signal disabled:opacity-40"
                    >
                      {pkg.agent?.status === "disabled" ? "Enable" : "Disable"}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() =>
                      setExpanded((cur) => (cur === pkg.package_id ? null : pkg.package_id))
                    }
                    className="rounded-xl border border-signal/30 px-4 py-2 font-mono text-xs uppercase tracking-[0.16em] text-signal hover:bg-signal/10"
                  >
                    {open ? "Hide deploy" : "Deploy host"}
                  </button>
                </div>
              </div>

              {open ? (
                <div className="mt-4 rounded-2xl border border-white/10 bg-ink-900/60 p-4">
                  <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist-400">
                    Remote install · Claude Code style
                  </div>
                  <p className="mt-2 text-xs text-mist-400">
                    在目标主机执行一键安装（下载 zip → venv → launcher under ~/.aop）。需先安装对应
                    harness 二进制（Claude / Pi / DeepSeek）。
                  </p>

                  <div className="mt-4 space-y-3">
                    <div>
                      <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                        Windows PowerShell
                      </div>
                      <div className="flex flex-wrap items-start gap-2">
                        <code className="flex-1 break-all rounded-lg border border-white/10 bg-ink-950 px-3 py-2 font-mono text-[11px] text-mist-200">
                          {cmds.windows}
                        </code>
                        <button
                          type="button"
                          onClick={() => onCopy(`${pkg.package_id}:win`, cmds.windows)}
                          className="shrink-0 rounded-lg border border-white/15 px-3 py-2 font-mono text-[10px] uppercase tracking-[0.12em] text-mist-200 hover:border-signal/40 hover:text-signal"
                        >
                          {copied === `${pkg.package_id}:win` ? "Copied" : "Copy"}
                        </button>
                      </div>
                    </div>
                    <div>
                      <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                        Linux / macOS
                      </div>
                      <div className="flex flex-wrap items-start gap-2">
                        <code className="flex-1 break-all rounded-lg border border-white/10 bg-ink-950 px-3 py-2 font-mono text-[11px] text-mist-200">
                          {cmds.unix}
                        </code>
                        <button
                          type="button"
                          onClick={() => onCopy(`${pkg.package_id}:unix`, cmds.unix)}
                          className="shrink-0 rounded-lg border border-white/15 px-3 py-2 font-mono text-[10px] uppercase tracking-[0.12em] text-mist-200 hover:border-signal/40 hover:text-signal"
                        >
                          {copied === `${pkg.package_id}:unix` ? "Copied" : "Copy"}
                        </button>
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={busy === `dl:${pkg.package_id}`}
                      onClick={() => onDownload(pkg)}
                      className="rounded-xl border border-white/15 px-4 py-2 font-mono text-xs uppercase tracking-[0.16em] text-mist-200 hover:border-signal/40 hover:text-signal disabled:opacity-40"
                    >
                      {busy === `dl:${pkg.package_id}` ? "Downloading…" : "Download zip"}
                    </button>
                    <button
                      type="button"
                      onClick={() => onCopy(`${pkg.package_id}:short`, cmds.windowsShort)}
                      className="rounded-xl border border-white/10 px-3 py-2 font-mono text-[10px] text-mist-500 hover:text-mist-200"
                      title={cmds.windowsShort}
                    >
                      Copy short alias
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
