#!/usr/bin/env node
/**
 * Hermetic Console smoke: golden-path files exist, nav stays frozen.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const required = [
  "app/page.tsx",
  "app/inbox/page.tsx",
  "app/tasks/page.tsx",
  "app/agents/page.tsx",
  "app/workflows/page.tsx",
  "app/settings/page.tsx",
  "app/login/page.tsx",
  "components/ops/ChaosPlaybook.tsx",
  "components/workflows/WorkflowsPageView.tsx",
  "components/shell/PreflightBanner.tsx",
  "hooks/useVisualRuntime.ts",
  "hooks/usePreflight.tsx",
  "lib/api.ts",
];

const missing = required.filter((rel) => !fs.existsSync(path.join(root, rel)));
if (missing.length) {
  console.error("missing:", missing.join(", "));
  process.exit(1);
}

const shell = fs.readFileSync(path.join(root, "components/shell/AppShell.tsx"), "utf8");
const forbiddenNav = ["/marketplace", "/scheduling"];
const leaked = forbiddenNav.filter((href) => shell.includes(`"${href}"`) || shell.includes(`'${href}'`));
if (leaked.length) {
  console.error("nav freeze broken; AppShell still links", leaked.join(", "));
  process.exit(1);
}
if (!shell.includes("/workflows")) {
  console.error("nav missing Flows (/workflows)");
  process.exit(1);
}
if (shell.includes('href: "/inbox"')) {
  console.error("nav freeze: Inbox must stay out of AppShell");
  process.exit(1);
}

const api = fs.readFileSync(path.join(root, "lib/api.ts"), "utf8");
for (const needle of ["recover_steps", "downloadTaskPackage", "listTeammates"]) {
  if (!api.includes(needle)) {
    console.error("lib/api.ts missing", needle);
    process.exit(1);
  }
}

const flows = fs.readFileSync(path.join(root, "components/workflows/WorkflowsPageView.tsx"), "utf8");
if (!flows.includes("approval_mode") || !flows.includes("approver_agent")) {
  console.error("Flows editor dropped approval_mode / approver_agent");
  process.exit(1);
}

console.log("console smoke ok", required.length, "files");
