import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/shell/AppShell";

export const metadata: Metadata = {
  title: "A2A OS",
  description: "Agent registration, discovery, orchestration and observability",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen font-sans antialiased">
        <div
          className="pointer-events-none fixed inset-0 opacity-[0.035]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(232,242,238,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(232,242,238,0.5) 1px, transparent 1px)",
            backgroundSize: "48px 48px",
          }}
        />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
