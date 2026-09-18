"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  getAuthMe,
  getSessionToken,
  logout,
  setSessionToken,
} from "@/lib/api";

const NAV = [
  { href: "/", label: "首页", hint: "Dashboard" },
  { href: "/tasks", label: "任务", hint: "Tasks" },
  { href: "/agents", label: "Agent", hint: "Agents" },
  { href: "/workflows", label: "工作流", hint: "Workflows" },
  { href: "/artifacts", label: "产物", hint: "Artifacts" },
  { href: "/settings", label: "设置", hint: "Settings" },
];

function navActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [userLabel, setUserLabel] = useState("访客");
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await getAuthMe();
        if (cancelled) return;
        if (me.authenticated) {
          setAuthed(true);
          setUserLabel(me.user?.display_name || me.email || me.name || "已登录");
        } else {
          setAuthed(!!getSessionToken());
          setUserLabel(getSessionToken() ? "会话" : "访客");
        }
      } catch {
        if (!cancelled) {
          setAuthed(!!getSessionToken());
          setUserLabel(getSessionToken() ? "会话" : "访客");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  async function onLogout() {
    try {
      await logout();
    } catch {
      /* ignore */
    }
    setSessionToken(null);
    setAuthed(false);
    setUserLabel("访客");
    router.push("/login");
  }

  if (pathname === "/login") {
    return <div className="relative z-10 min-h-screen">{children}</div>;
  }

  return (
    <div className="relative z-10 flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-white/10 bg-ink-950/80 px-4 backdrop-blur-md md:px-6">
        <Link href="/" className="group flex items-baseline gap-2">
          <span className="font-display text-xl tracking-tight text-mist-100 transition group-hover:text-signal md:text-2xl">
            A2A OS
          </span>
          <span className="hidden font-mono text-[10px] uppercase tracking-[0.22em] text-mist-400 sm:inline">
            control plane
          </span>
        </Link>
        <div className="flex items-center gap-3 font-mono text-[11px] text-mist-400">
          <span className="rounded-full border border-white/10 px-3 py-1">
            租户: <span className="text-mist-200">Default</span>
          </span>
          {authed ? (
            <>
              <span className="rounded-full border border-white/10 px-2 py-1 text-mist-200">
                {userLabel}
              </span>
              <button
                type="button"
                onClick={onLogout}
                className="rounded-full border border-white/15 px-2 py-1 text-mist-300 hover:text-signal"
              >
                退出
              </button>
            </>
          ) : (
            <Link
              href="/login"
              className="rounded-full border border-signal/30 px-3 py-1 text-signal"
            >
              登录
            </Link>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="sticky top-14 hidden h-[calc(100vh-3.5rem)] w-48 shrink-0 flex-col border-r border-white/10 bg-ink-900/40 px-3 py-5 md:flex">
          <nav className="flex flex-col gap-1">
            {NAV.map((item) => {
              const active = navActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-lg px-3 py-2.5 transition ${
                    active
                      ? "bg-signal/10 text-signal"
                      : "text-mist-400 hover:bg-white/5 hover:text-mist-100"
                  }`}
                >
                  <div className="font-sans text-sm font-medium">{item.label}</div>
                  <div className="font-mono text-[10px] uppercase tracking-[0.14em] opacity-70">
                    {item.hint}
                  </div>
                </Link>
              );
            })}
          </nav>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <nav className="flex gap-1 overflow-x-auto border-b border-white/10 px-2 py-2 md:hidden">
            {NAV.map((item) => {
              const active = navActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`whitespace-nowrap rounded-lg px-3 py-1.5 font-mono text-[11px] uppercase ${
                    active ? "bg-signal/15 text-signal" : "text-mist-400"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <main className="flex-1">{children}</main>
        </div>
      </div>
    </div>
  );
}
