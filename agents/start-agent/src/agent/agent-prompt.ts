import type { ProjectInfo } from "../types.js";

export function buildSystemPrompt(project: ProjectInfo, workspace: string): string {
  return `You are DeployPilot's deployment agent powered by Pi.

Mission: analyze the project, produce a concrete deployment plan, execute deployment inside Docker with resource limits, diagnose failures from REAL tool output, and repair up to 3 times.

Hard rules:
1. Never invent success, URLs, ports, or log content. Only report facts returned by tools.
2. Prefer Docker / Docker Compose. Do not run untrusted project code directly on the host.
3. Keep changes minimal and reversible when repairing (Dockerfile, compose, dependency pins, env defaults).
4. When done, output a final JSON block with keys: success, url, runtime, summary, repairs.
5. Working directory for the project source is: ${workspace}
6. Project inspection snapshot:
${JSON.stringify(project, null, 2)}

Available domain skills cover: project-analysis, docker-deployment, python-deployment, nodejs-deployment, database-setup, deployment-debugging.
Use skills when relevant, then call tools.
`;
}

export function buildPlanPrompt(): string {
  return `Create a deployment plan for this project.

Return ONLY a JSON object with this shape:
{
  "summary": string,
  "runtime": "docker" | "docker-compose" | "local-process",
  "imageTag": string,
  "composeFile"?: string,
  "dockerfile"?: string,
  "buildCommands": string[],
  "startCommands": string[],
  "healthUrl"?: string,
  "healthPort"?: number,
  "env": object,
  "notes": string[]
}

Prefer docker-compose when a compose file exists. Otherwise prefer a single Dockerfile container.
imageTag must be deploypilot/<safe-project-name>:latest
`;
}

export function buildRepairPrompt(errorLog: string, attempt: number, max: number): string {
  return `Deployment failed (repair attempt ${attempt}/${max}).

Real error / logs:
\`\`\`
${errorLog.slice(0, 12000)}
\`\`\`

Diagnose the root cause and apply the smallest fix using tools (edit Dockerfile/compose/requirements/package files as needed).
Then reply with a short JSON object:
{
  "action": string,
  "rootCause": string,
  "filesChanged": string[],
  "retryBuild": boolean,
  "retryStart": boolean
}
`;
}

export function extractJsonBlock<T>(text: string): T | undefined {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fenced?.[1]?.trim() || text.trim();
  const start = candidate.indexOf("{");
  const end = candidate.lastIndexOf("}");
  if (start < 0 || end <= start) return undefined;
  try {
    return JSON.parse(candidate.slice(start, end + 1)) as T;
  } catch {
    return undefined;
  }
}
