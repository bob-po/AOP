import { Type } from "typebox";
import {
  createAgentSession,
  DefaultResourceLoader,
  defineTool,
  ModelRuntime,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { resolveCliModel } from "@earendil-works/pi-coding-agent";
import { join } from "node:path";
import { skillsDir } from "../sandbox/workspace.js";
import { loadAppConfig } from "../config.js";
import { buildSystemPrompt, extractJsonBlock } from "./agent-prompt.js";
import { bindAgentEvents } from "./event-handler.js";
import type { DeployPanel } from "../ui/panel.js";
import type { TaskStore } from "../core/task-store.js";
import type { DeployPlan, ProjectInfo, TaskRecord } from "../types.js";
import { buildHeuristicPlan } from "../tools/project-inspector.js";
import { healthCheck, guessHealthUrls } from "../tools/health-check.js";
import {
  composeLogs,
  dockerBuild,
  dockerLogs,
  dockerInspectRunning,
} from "../tools/docker.js";
import { execCommand } from "../tools/process.js";
import { listFiles, readText, writeText, pathExists } from "../tools/filesystem.js";

export interface PiAgentHandle {
  available: boolean;
  reason?: string;
  session?: Awaited<ReturnType<typeof createAgentSession>>["session"];
  dispose: () => void;
  planDeployment: () => Promise<DeployPlan>;
  repair: (errorLog: string, attempt: number, max: number) => Promise<{
    action: string;
    rootCause: string;
    filesChanged: string[];
    retryBuild: boolean;
    retryStart: boolean;
  }>;
}

function safeImageTag(name: string): string {
  const safe = name.toLowerCase().replace(/[^a-z0-9_-]/g, "-").replace(/^-+/, "") || "app";
  return `deploypilot/${safe}:latest`;
}

function createDeployTools(ctx: {
  project: ProjectInfo;
  task: TaskRecord;
  store: TaskStore;
}) {
  const inspectTool = defineTool({
    name: "dp_inspect",
    label: "Inspect project files",
    description: "List important files under the project root",
    parameters: Type.Object({
      maxDepth: Type.Optional(Type.Number()),
    }),
    execute: async (_id, params) => {
      const files = listFiles(ctx.project.root, params.maxDepth ?? 2).slice(0, 200);
      return {
        content: [{ type: "text", text: JSON.stringify({ root: ctx.project.root, files }, null, 2) }],
        details: {},
      };
    },
  });

  const readTool = defineTool({
    name: "dp_read",
    label: "Read project file",
    description: "Read a text file relative to the project root",
    parameters: Type.Object({
      path: Type.String(),
    }),
    execute: async (_id, params) => {
      const full = join(ctx.project.root, params.path);
      if (!pathExists(full)) {
        return {
          content: [{ type: "text", text: `File not found: ${params.path}` }],
          details: {},
          isError: true,
        };
      }
      return {
        content: [{ type: "text", text: readText(full).slice(0, 50_000) }],
        details: {},
      };
    },
  });

  const writeTool = defineTool({
    name: "dp_write",
    label: "Write project file",
    description: "Write/overwrite a text file relative to the project root (for repair)",
    parameters: Type.Object({
      path: Type.String(),
      content: Type.String(),
    }),
    execute: async (_id, params) => {
      const full = join(ctx.project.root, params.path);
      writeText(full, params.content);
      ctx.store.appendEvent(ctx.task, `Wrote ${params.path}`, "info");
      return {
        content: [{ type: "text", text: `Wrote ${params.path} (${params.content.length} bytes)` }],
        details: {},
      };
    },
  });

  const dockerBuildTool = defineTool({
    name: "dp_docker_build",
    label: "Docker build",
    description: "Build a Docker image from the project root",
    parameters: Type.Object({
      tag: Type.String(),
      dockerfile: Type.Optional(Type.String()),
    }),
    execute: async (_id, params) => {
      try {
        const result = await dockerBuild(
          ctx.project.root,
          params.tag,
          params.dockerfile || "Dockerfile",
        );
        return {
          content: [{ type: "text", text: (result.stdout + "\n" + result.stderr).slice(0, 30_000) }],
          details: {},
        };
      } catch (err) {
        return {
          content: [{ type: "text", text: err instanceof Error ? err.message : String(err) }],
          details: {},
          isError: true,
        };
      }
    },
  });

  const logsTool = defineTool({
    name: "dp_logs",
    label: "Fetch container logs",
    description: "Fetch docker or compose logs",
    parameters: Type.Object({
      container: Type.Optional(Type.String()),
      composeFile: Type.Optional(Type.String()),
      composeProject: Type.Optional(Type.String()),
    }),
    execute: async (_id, params) => {
      try {
        let logs = "";
        if (params.composeFile && params.composeProject) {
          logs = await composeLogs(
            ctx.project.root,
            params.composeFile,
            params.composeProject,
            200,
          );
        } else if (params.container) {
          logs = await dockerLogs(params.container, 200);
        } else {
          logs = "Provide container or composeFile+composeProject";
        }
        return { content: [{ type: "text", text: logs.slice(0, 30_000) }], details: {} };
      } catch (err) {
        return {
          content: [{ type: "text", text: err instanceof Error ? err.message : String(err) }],
          details: {},
          isError: true,
        };
      }
    },
  });

  const healthTool = defineTool({
    name: "dp_health",
    label: "HTTP health check",
    description: "Probe a URL and return real HTTP status",
    parameters: Type.Object({
      url: Type.String(),
      retries: Type.Optional(Type.Number()),
    }),
    execute: async (_id, params) => {
      const result = await healthCheck({
        url: params.url,
        retries: params.retries ?? 5,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        details: {},
        isError: !result.ok,
      };
    },
  });

  const shellTool = defineTool({
    name: "dp_sandbox_shell",
    label: "Sandbox shell",
    description:
      "Run a shell command inside a disposable Docker container with resource limits. Do not use for long-running servers.",
    parameters: Type.Object({
      image: Type.String({ default: "alpine:3.20" }),
      command: Type.String(),
      memory: Type.Optional(Type.String()),
    }),
    execute: async (_id, params) => {
      const config = loadAppConfig();
      const result = await execCommand(
        "docker",
        [
          "run",
          "--rm",
          "--network",
          "none",
          "--memory",
          params.memory || config.memoryLimit,
          "--cpus",
          config.cpuLimit,
          "--pids-limit",
          "128",
          "-v",
          `${ctx.project.root}:/workspace:ro`,
          "-w",
          "/workspace",
          params.image,
          "sh",
          "-c",
          params.command,
        ],
        { timeoutMs: 120_000 },
      );
      const text = `exit=${result.code}\n${result.stdout}\n${result.stderr}`.slice(0, 30_000);
      return {
        content: [{ type: "text", text }],
        details: {},
        isError: result.code !== 0,
      };
    },
  });

  const statusTool = defineTool({
    name: "dp_container_status",
    label: "Container status",
    description: "Check whether a container is running",
    parameters: Type.Object({
      container: Type.String(),
    }),
    execute: async (_id, params) => {
      const running = await dockerInspectRunning(params.container);
      return {
        content: [{ type: "text", text: JSON.stringify({ container: params.container, running }) }],
        details: {},
      };
    },
  });

  return [
    inspectTool,
    readTool,
    writeTool,
    dockerBuildTool,
    logsTool,
    healthTool,
    shellTool,
    statusTool,
  ];
}

export async function createPiAgent(opts: {
  project: ProjectInfo;
  task: TaskRecord;
  store: TaskStore;
  panel: DeployPanel;
  model?: string;
}): Promise<PiAgentHandle> {
  const config = loadAppConfig();
  const disposeFns: Array<() => void> = [];

  const fallback: PiAgentHandle = {
    available: false,
    reason: "Pi model/auth not configured",
    dispose: () => undefined,
    planDeployment: async () => buildHeuristicPlan(opts.project, safeImageTag(opts.project.name)),
    repair: async (errorLog, attempt) => {
      if (/port is already allocated|address already in use/i.test(errorLog)) {
        return {
          action: "Free conflicting DeployPilot container / remap host port",
          rootCause: "Host port already allocated by another container",
          filesChanged: [],
          retryBuild: false,
          retryStart: true,
        };
      }
      if (/failed to resolve reference|registry-1\.docker\.io|dial tcp|connection attempt failed/i.test(errorLog)) {
        // Rewrite generated compose/Dockerfile to use mirror registries
        try {
          const { rewriteComposeImagesToMirror, ensureGeneratedDockerfile, ensureGeneratedCompose } =
            await import("../sandbox/workspace.js");
          const composePath = join(opts.project.root, "docker-compose.yml");
          rewriteComposeImagesToMirror(composePath);
          // Force regenerate Dockerfile with mirrored base images
          opts.project.hasDockerfile = false;
          ensureGeneratedDockerfile(opts.project);
          opts.project.hasDockerfile = true;
          if (opts.task.plan) {
            ensureGeneratedCompose(opts.project, opts.task.plan);
          }
        } catch {
          // ignore rewrite errors; retry may still help if images were pulled mid-flight
        }
        return {
          action: "Switch base images to DaoCloud mirror and retry",
          rootCause: "Docker Hub registry unreachable",
          filesChanged: ["Dockerfile", "docker-compose.yml"],
          retryBuild: true,
          retryStart: true,
        };
      }
      return {
        action: `Heuristic repair attempt ${attempt}`,
        rootCause: errorLog.split("\n").slice(0, 5).join(" "),
        filesChanged: [],
        retryBuild: true,
        retryStart: true,
      };
    },
  };

  try {
    const modelRuntime = await ModelRuntime.create({
      authPath: join(config.homeDir, "pi-auth.json"),
      modelsPath: join(config.homeDir, "pi-models.json"),
    });

    // Apply env API keys as runtime overrides when present
    if (config.anthropicApiKey) {
      await modelRuntime.setRuntimeApiKey("anthropic", config.anthropicApiKey);
    }
    if (config.openaiApiKey) {
      await modelRuntime.setRuntimeApiKey("openai", config.openaiApiKey);
      // OpenAI-compatible custom providers (DeepSeek etc.)
      for (const providerId of ["deepseek", "openai-compat"]) {
        try {
          await modelRuntime.setRuntimeApiKey(providerId, config.openaiApiKey);
        } catch {
          // provider may not be registered yet
        }
      }
    }
    if (config.googleApiKey) {
      try {
        await modelRuntime.setRuntimeApiKey("google", config.googleApiKey);
      } catch {
        // provider id may differ across versions
      }
    }

    const available = await modelRuntime.getAvailable();
    if (!available.length) {
      return {
        ...fallback,
        reason:
          "No authenticated Pi model found. Run `deploypilot config` or set ANTHROPIC_API_KEY / OPENAI_API_KEY.",
      };
    }

    let model = available[0];
    const modelSpec = opts.model || config.model;
    if (modelSpec) {
      const resolved = resolveCliModel({
        cliModel: modelSpec,
        modelRuntime,
      });
      if (!resolved.error && resolved.model) {
        model = resolved.model;
      }
    }

    const loader = new DefaultResourceLoader({
      cwd: opts.project.root,
      agentDir: join(config.homeDir, "pi-agent"),
      additionalSkillPaths: [skillsDir()],
      systemPromptOverride: () => buildSystemPrompt(opts.project, opts.project.root),
      noExtensions: true,
    });
    await loader.reload();

    const customTools = createDeployTools({
      project: opts.project,
      task: opts.task,
      store: opts.store,
    });

    const sessionFile = join(opts.task.workspaceDir, "pi-session.jsonl");
    const sessionManager = pathExists(sessionFile)
      ? SessionManager.open(sessionFile, opts.task.workspaceDir, opts.project.root)
      : SessionManager.create(opts.project.root, opts.task.workspaceDir);

    const { session } = await createAgentSession({
      cwd: opts.project.root,
      agentDir: join(config.homeDir, "pi-agent"),
      model,
      thinkingLevel: "low",
      modelRuntime,
      tools: ["read", "bash", "edit", "write", "grep", "find", "ls"],
      customTools,
      resourceLoader: loader,
      sessionManager,
    });

    opts.task.agentSessionFile = sessionFile;
    opts.store.save(opts.task);

    const unsub = bindAgentEvents(session, {
      panel: opts.panel,
      store: opts.store,
      task: opts.task,
    });
    disposeFns.push(unsub, () => session.dispose());

    const collectAssistantText = (): string => {
      const messages = session.messages as Array<{
        role?: string;
        content?: Array<{ type?: string; text?: string }> | string;
      }>;
      const assistant = [...messages].reverse().find((m) => m.role === "assistant");
      if (!assistant) return "";
      if (typeof assistant.content === "string") return assistant.content;
      return (assistant.content || [])
        .filter((c) => c.type === "text" && c.text)
        .map((c) => c.text!)
        .join("\n");
    };

    return {
      available: true,
      session,
      dispose: () => {
        for (const fn of disposeFns.reverse()) {
          try {
            fn();
          } catch {
            // ignore
          }
        }
      },
      planDeployment: async () => {
        const { buildPlanPrompt } = await import("./agent-prompt.js");
        await session.prompt(buildPlanPrompt());
        const text = collectAssistantText();
        const parsed = extractJsonBlock<DeployPlan>(text);
        if (parsed?.runtime && parsed?.imageTag) {
          return { ...parsed, generatedBy: "agent", env: parsed.env ?? {}, notes: parsed.notes ?? [] };
        }
        opts.panel.agent("Plan JSON incomplete; falling back to heuristic plan");
        return buildHeuristicPlan(opts.project, safeImageTag(opts.project.name));
      },
      repair: async (errorLog, attempt, max) => {
        const { buildRepairPrompt } = await import("./agent-prompt.js");
        await session.prompt(buildRepairPrompt(errorLog, attempt, max));
        const text = collectAssistantText();
        const parsed = extractJsonBlock<{
          action?: string;
          rootCause?: string;
          filesChanged?: string[];
          retryBuild?: boolean;
          retryStart?: boolean;
        }>(text);
        return {
          action: parsed?.action || "Attempted agent repair",
          rootCause: parsed?.rootCause || "See error logs",
          filesChanged: parsed?.filesChanged || [],
          retryBuild: parsed?.retryBuild !== false,
          retryStart: parsed?.retryStart !== false,
        };
      },
    };
  } catch (err) {
    return {
      ...fallback,
      reason: err instanceof Error ? err.message : String(err),
    };
  }
}

export async function verifyHealthFromPlan(plan: DeployPlan): Promise<{
  ok: boolean;
  url?: string;
  detail: string;
}> {
  const urls: string[] = [];
  if (plan.healthUrl) urls.push(plan.healthUrl);
  if (plan.healthPort) urls.push(...guessHealthUrls(plan.healthPort));
  if (!urls.length) {
    return { ok: false, detail: "No health URL/port in plan" };
  }
  // Spring Boot / Maven apps can take a while after compose up
  let last: Awaited<ReturnType<typeof healthCheck>> | undefined;
  for (const url of [...new Set(urls)]) {
    const result = await healthCheck({
      url,
      retries: 20,
      intervalMs: 3000,
      timeoutMs: 5000,
    });
    if (result.ok) {
      return {
        ok: true,
        url: result.url,
        detail: `HTTP ${result.statusCode} after ${result.attempts} attempt(s)`,
      };
    }
    last = result;
  }
  return {
    ok: false,
    url: plan.healthUrl || urls[0],
    detail: last?.error || "health check failed",
  };
}
