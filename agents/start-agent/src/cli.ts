#!/usr/bin/env node
import { buildProgram } from "./commands/deploy.js";

const program = buildProgram();
program.parseAsync(process.argv).catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
