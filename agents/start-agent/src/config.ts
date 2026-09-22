import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { config as loadDotenv } from "dotenv";
import type { AppConfig, DeployMode } from "./types.js";

export interface UserConfigFile {
  model?: string;
  mode?: DeployMode;
  maxRepairAttempts?: number;
  memoryLimit?: string;
  cpuLimit?: string;
}

function expandHome(path: string): string {
  if (path.startsWith("~/")) return join(homedir(), path.slice(2));
  return path;
}

export function getHomeDir(): string {
  return process.env.DEPLOYPILOT_HOME
    ? expandHome(process.env.DEPLOYPILOT_HOME)
    : join(homedir(), ".deploypilot");
}

export function ensureDirs(homeDir = getHomeDir()): void {
  for (const dir of [
    homeDir,
    join(homeDir, "tasks"),
    join(homeDir, "workspaces"),
    join(homeDir, "logs"),
  ]) {
    mkdirSync(dir, { recursive: true });
  }
}

export function loadUserConfig(homeDir = getHomeDir()): UserConfigFile {
  const configPath = join(homeDir, "config.json");
  if (!existsSync(configPath)) return {};
  try {
    return JSON.parse(readFileSync(configPath, "utf8")) as UserConfigFile;
  } catch {
    return {};
  }
}

export function saveUserConfig(partial: UserConfigFile, homeDir = getHomeDir()): UserConfigFile {
  ensureDirs(homeDir);
  const configPath = join(homeDir, "config.json");
  const next = { ...loadUserConfig(homeDir), ...partial };
  writeFileSync(configPath, JSON.stringify(next, null, 2), "utf8");
  return next;
}

/**
 * Ensure Pi models.json has an OpenAI-compatible provider when OPENAI_BASE_URL is set
 * (e.g. DeepSeek). Idempotent — merges/updates the `deepseek` or `openai-compat` provider.
 */
export function ensurePiModelsConfig(homeDir = getHomeDir()): string {
  ensureDirs(homeDir);
  const modelsPath = join(homeDir, "pi-models.json");
  const baseUrl = (process.env.OPENAI_BASE_URL || "").replace(/\/$/, "");
  const modelId = process.env.OPENAI_MODEL || "deepseek-v4-pro";

  // Normalize DeepSeek base URL to include /v1
  let resolvedBase = baseUrl;
  if (resolvedBase.includes("api.deepseek.com") && !resolvedBase.endsWith("/v1")) {
    resolvedBase = `${resolvedBase}/v1`;
  }

  if (!resolvedBase && !existsSync(modelsPath)) {
    // Seed a DeepSeek-ready stub so users only need OPENAI_API_KEY
    resolvedBase = "https://api.deepseek.com/v1";
  }

  if (!resolvedBase && existsSync(modelsPath)) {
    return modelsPath;
  }

  const providerId = resolvedBase.includes("deepseek") ? "deepseek" : "openai-compat";

  let existing: { providers?: Record<string, unknown> } = {};
  if (existsSync(modelsPath)) {
    try {
      existing = JSON.parse(readFileSync(modelsPath, "utf8")) as typeof existing;
    } catch {
      existing = {};
    }
  }

  const providers = { ...(existing.providers ?? {}) };
  providers[providerId] = {
    baseUrl: resolvedBase || "https://api.deepseek.com/v1",
    api: "openai-completions",
    apiKey: "$OPENAI_API_KEY",
    compat: {
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
    },
    models: [
      {
        id: modelId,
        name: modelId,
        reasoning: /pro|reasoner|r1/i.test(modelId),
        input: ["text"],
        contextWindow: 128000,
        maxTokens: 8192,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      },
      {
        id: "deepseek-chat",
        name: "DeepSeek Chat",
        reasoning: false,
        input: ["text"],
        contextWindow: 128000,
        maxTokens: 8192,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      },
      {
        id: "deepseek-reasoner",
        name: "DeepSeek Reasoner",
        reasoning: true,
        input: ["text"],
        contextWindow: 128000,
        maxTokens: 8192,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      },
    ],
  };

  writeFileSync(modelsPath, JSON.stringify({ providers }, null, 2), "utf8");
  return modelsPath;
}

export function loadAppConfig(cwd = process.cwd()): AppConfig {
  loadDotenv({ path: join(cwd, ".env") });
  loadDotenv({ path: join(getHomeDir(), ".env") });

  const homeDir = getHomeDir();
  ensureDirs(homeDir);
  ensurePiModelsConfig(homeDir);
  const user = loadUserConfig(homeDir);

  const mode = (process.env.DEPLOYPILOT_MODE || user.mode || "docker") as DeployMode;
  const defaultModel =
    process.env.DEPLOYPILOT_MODEL ||
    user.model ||
    (process.env.OPENAI_MODEL
      ? `${(process.env.OPENAI_BASE_URL || "").includes("deepseek") || !process.env.OPENAI_BASE_URL ? "deepseek" : "openai-compat"}/${process.env.OPENAI_MODEL}`
      : undefined);

  return {
    homeDir,
    tasksDir: join(homeDir, "tasks"),
    workspacesDir: join(homeDir, "workspaces"),
    configPath: join(homeDir, "config.json"),
    model: defaultModel,
    mode,
    maxRepairAttempts: Number(
      process.env.DEPLOYPILOT_MAX_REPAIR || user.maxRepairAttempts || 3,
    ),
    memoryLimit: process.env.DEPLOYPILOT_MEMORY_LIMIT || user.memoryLimit || "512m",
    cpuLimit: process.env.DEPLOYPILOT_CPU_LIMIT || user.cpuLimit || "1.0",
    anthropicApiKey: process.env.ANTHROPIC_API_KEY,
    openaiApiKey: process.env.OPENAI_API_KEY,
    googleApiKey: process.env.GOOGLE_API_KEY,
  };
}
