import { execCommand, execOrThrow } from "./process.js";

export async function dockerAvailable(): Promise<boolean> {
  try {
    const r = await execCommand("docker", ["version", "--format", "{{.Server.Version}}"], {
      timeoutMs: 15_000,
    });
    return r.code === 0 && Boolean(r.stdout.trim());
  } catch {
    return false;
  }
}

export async function dockerDiagnostics(): Promise<string> {
  try {
    const r = await execCommand("docker", ["info"], { timeoutMs: 15_000 });
    if (r.code === 0) return "Docker daemon is reachable";
    return (r.stderr || r.stdout || "Docker is not reachable").trim().slice(0, 400);
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
}

export async function composeAvailable(): Promise<boolean> {
  try {
    const r = await execCommand("docker", ["compose", "version"], { timeoutMs: 10_000 });
    return r.code === 0;
  } catch {
    return false;
  }
}

export interface DockerRunOptions {
  image: string;
  name: string;
  ports?: Array<{ host: number; container: number }>;
  env?: Record<string, string>;
  memoryLimit?: string;
  cpuLimit?: string;
  workdir?: string;
  detach?: boolean;
  network?: string;
  volumes?: string[];
  command?: string[];
}

export async function dockerBuild(
  contextDir: string,
  tag: string,
  dockerfile = "Dockerfile",
): Promise<{ stdout: string; stderr: string }> {
  const result = await execCommand(
    "docker",
    ["build", "-f", dockerfile, "-t", tag, "."],
    { cwd: contextDir, timeoutMs: 15 * 60_000 },
  );
  if (result.code !== 0) {
    throw new Error(`docker build failed:\n${result.stderr || result.stdout}`);
  }
  return { stdout: result.stdout, stderr: result.stderr };
}

export async function dockerRun(opts: DockerRunOptions): Promise<string> {
  const args = ["run"];
  if (opts.detach !== false) args.push("-d");
  args.push("--name", opts.name);
  if (opts.memoryLimit) args.push("--memory", opts.memoryLimit);
  if (opts.cpuLimit) args.push("--cpus", opts.cpuLimit);
  // Security hardening defaults
  args.push("--pids-limit", "256");
  args.push("--read-only=false");
  if (opts.network) args.push("--network", opts.network);
  if (opts.workdir) args.push("-w", opts.workdir);
  for (const [k, v] of Object.entries(opts.env ?? {})) {
    args.push("-e", `${k}=${v}`);
  }
  for (const p of opts.ports ?? []) {
    args.push("-p", `${p.host}:${p.container}`);
  }
  for (const vol of opts.volumes ?? []) {
    args.push("-v", vol);
  }
  args.push(opts.image);
  if (opts.command?.length) args.push(...opts.command);

  // Remove existing container with same name
  await execCommand("docker", ["rm", "-f", opts.name], { timeoutMs: 30_000 }).catch(() => undefined);

  const result = await execCommand("docker", args, { timeoutMs: 120_000 });
  if (result.code !== 0) {
    throw new Error(`docker run failed:\n${result.stderr || result.stdout}`);
  }
  return result.stdout.trim();
}

export async function dockerLogs(
  container: string,
  tail = 200,
): Promise<string> {
  const result = await execCommand("docker", ["logs", "--tail", String(tail), container], {
    timeoutMs: 30_000,
  });
  return `${result.stdout}\n${result.stderr}`.trim();
}

export async function dockerInspectRunning(container: string): Promise<boolean> {
  const result = await execCommand(
    "docker",
    ["inspect", "-f", "{{.State.Running}}", container],
    { timeoutMs: 15_000 },
  );
  return result.code === 0 && result.stdout.trim() === "true";
}

export async function dockerRm(container: string): Promise<void> {
  await execCommand("docker", ["rm", "-f", container], { timeoutMs: 60_000 });
}

/** List host ports currently published by running containers. */
export async function listPublishedHostPorts(): Promise<number[]> {
  const result = await execCommand(
    "docker",
    ["ps", "--format", "{{.Ports}}"],
    { timeoutMs: 15_000 },
  );
  if (result.code !== 0) return [];
  const ports = new Set<number>();
  for (const line of result.stdout.split(/\r?\n/)) {
    for (const m of line.matchAll(/(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]):(\d+)->/g)) {
      ports.add(Number(m[1]));
    }
  }
  return [...ports];
}

/** Stop/remove other DeployPilot containers that publish a host port. */
export async function freeDeployPilotPort(
  hostPort: number,
  keepContainerName?: string,
): Promise<string[]> {
  const result = await execCommand(
    "docker",
    ["ps", "--format", "{{.Names}}\t{{.Ports}}"],
    { timeoutMs: 15_000 },
  );
  if (result.code !== 0) return [];
  const removed: string[] = [];
  const needle = `:${hostPort}->`;
  for (const line of result.stdout.split(/\r?\n/)) {
    const [name, ports = ""] = line.split("\t");
    if (!name?.startsWith("deploypilot-")) continue;
    if (keepContainerName && name === keepContainerName) continue;
    if (!ports.includes(needle)) continue;
    await dockerRm(name);
    removed.push(name);
  }
  return removed;
}

export async function pickHostPort(preferred: number, occupied: number[]): Promise<number> {
  const busy = new Set(occupied);
  if (!busy.has(preferred)) return preferred;
  for (let p = preferred + 1; p < preferred + 50; p++) {
    if (!busy.has(p)) return p;
  }
  return preferred + 100;
}

export async function composeUp(
  projectDir: string,
  composeFile: string,
  projectName: string,
  env: Record<string, string> = {},
): Promise<{ stdout: string; stderr: string }> {
  const result = await execCommand(
    "docker",
    ["compose", "-f", composeFile, "-p", projectName, "up", "-d", "--build"],
    {
      cwd: projectDir,
      env: { ...process.env, ...env },
      timeoutMs: 15 * 60_000,
    },
  );
  if (result.code !== 0) {
    throw new Error(`docker compose up failed:\n${result.stderr || result.stdout}`);
  }
  return { stdout: result.stdout, stderr: result.stderr };
}

export async function composeDown(
  projectDir: string,
  composeFile: string,
  projectName: string,
): Promise<void> {
  await execCommand(
    "docker",
    ["compose", "-f", composeFile, "-p", projectName, "down", "-v", "--remove-orphans"],
    { cwd: projectDir, timeoutMs: 120_000 },
  );
}

export async function composeLogs(
  projectDir: string,
  composeFile: string,
  projectName: string,
  tail = 200,
): Promise<string> {
  const result = await execCommand(
    "docker",
    ["compose", "-f", composeFile, "-p", projectName, "logs", "--tail", String(tail)],
    { cwd: projectDir, timeoutMs: 60_000 },
  );
  return `${result.stdout}\n${result.stderr}`.trim();
}

export async function composePs(
  projectDir: string,
  composeFile: string,
  projectName: string,
): Promise<string> {
  const result = await execOrThrow(
    "docker",
    ["compose", "-f", composeFile, "-p", projectName, "ps"],
    { cwd: projectDir, timeoutMs: 30_000 },
  );
  return result.stdout;
}
