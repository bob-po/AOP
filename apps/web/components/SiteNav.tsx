import Link from "next/link";

export function SiteNav() {
  return (
    <header className="relative z-20 flex items-center justify-between px-6 py-5 md:px-10">
      <Link href="/" className="group flex items-baseline gap-2">
        <span className="font-display text-2xl tracking-tight text-mist-100 transition group-hover:text-signal">
          A2A OS
        </span>
        <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-mist-400">
          control plane
        </span>
      </Link>
      <nav className="flex items-center gap-6 font-mono text-xs uppercase tracking-[0.18em] text-mist-400">
        <Link href="/agents" className="transition hover:text-signal">
          Agents
        </Link>
        <Link href="/marketplace" className="transition hover:text-signal">
          Market
        </Link>
        <Link href="/workflows" className="transition hover:text-signal">
          Workflows
        </Link>
        <Link href="/" className="transition hover:text-signal">
          Tasks
        </Link>
      </nav>
    </header>
  );
}
