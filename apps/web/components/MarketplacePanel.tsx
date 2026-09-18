"use client";

import { useEffect, useState } from "react";
import {
  disableAgent,
  enableAgent,
  installMarketplacePackage,
  listMarketplace,
  probeHealth,
  type MarketplacePackage,
} from "@/lib/api";

export function MarketplacePanel({ embedded = false }: { embedded?: boolean }) {
  const [packages, setPackages] = useState<MarketplacePackage[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [probeMsg, setProbeMsg] = useState<string | null>(null);

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

  async function onInstall(pkg: MarketplacePackage) {
    setBusy(pkg.package_id);
    setError(null);
    try {
      await installMarketplacePackage(pkg.package_id);
      await reload(q);
    } catch (err) {
      setError(err instanceof Error ? err.message : "install failed");
    } finally {
      setBusy(null);
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
                Discover official agents, install into the registry, and keep health status fresh.
              </p>
            </>
          ) : (
            <p className="text-sm text-mist-400">从市场安装 Agent 到当前租户注册表。</p>
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
          placeholder="Search skills, tags, name…"
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
        {packages.map((pkg) => (
          <div
            key={pkg.package_id}
            className="grid gap-4 py-6 md:grid-cols-[1.5fr_1fr_auto] md:items-center"
          >
            <div>
              <div className="font-display text-xl text-mist-100">{pkg.name}</div>
              <div className="mt-1 font-mono text-[11px] text-mist-400">
                {pkg.publisher} · v{pkg.version} · {pkg.agent_key}
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
                  Installed ·{" "}
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
                "Not installed"
              )}
              <div className="mt-1 truncate text-[11px]">{pkg.default_endpoint}</div>
            </div>
            <div className="flex flex-col gap-2">
              {!pkg.installed ? (
                <button
                  type="button"
                  disabled={busy === pkg.package_id}
                  onClick={() => onInstall(pkg)}
                  className="rounded-xl bg-signal px-4 py-2 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-ink-950 disabled:opacity-40"
                >
                  {busy === pkg.package_id ? "Installing…" : "Install"}
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
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
