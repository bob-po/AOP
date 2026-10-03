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
  "components/inbox/HitlInboxView.tsx",
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
if (!shell.includes("/inbox") || !shell.includes("/workflows")) {
  console.error("nav missing Inbox or Flows (/workflows)");
  process.exit(1);
}

const api = fs.readFileSync(path.join(root, "lib/api.ts"), "utf8");
for (const needle of ["recover_steps", "downloadTaskPackage", "listTeammates"]) {
  if (!api.includes(needle)) {
    console.error("lib/api.ts missing", needle);
    process.exit(1);
  }
}

console.log("console smoke ok", required.length, "files");
