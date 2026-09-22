import { spawn } from "node:child_process";

export interface ExecResult {
  code: number;
  stdout: string;
  stderr: string;
  command: string;
}

export interface ExecOptions {
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  timeoutMs?: number;
  input?: string;
}

export function execCommand(
  command: string,
  args: string[],
  options: ExecOptions = {},
): Promise<ExecResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: { ...process.env, ...options.env },
      shell: false,
      windowsHide: true,
    });

    let stdout = "";
    let stderr = "";
    let settled = false;

    const timer =
      options.timeoutMs &&
      setTimeout(() => {
        child.kill("SIGKILL");
        if (!settled) {
          settled = true;
          reject(new Error(`Command timed out: ${command} ${args.join(" ")}`));
        }
      }, options.timeoutMs);

    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });

    child.on("error", (err) => {
      if (timer) clearTimeout(timer);
      if (!settled) {
        settled = true;
        reject(err);
      }
    });

    child.on("close", (code) => {
      if (timer) clearTimeout(timer);
      if (settled) return;
      settled = true;
      resolve({
        code: code ?? 1,
        stdout,
        stderr,
        command: `${command} ${args.join(" ")}`.trim(),
      });
    });

    if (options.input) {
      child.stdin.write(options.input);
      child.stdin.end();
    }
  });
}

export async function execOrThrow(
  command: string,
  args: string[],
  options: ExecOptions = {},
): Promise<ExecResult> {
  const result = await execCommand(command, args, options);
  if (result.code !== 0) {
    throw new Error(
      `${result.command} failed (exit ${result.code})\n${result.stderr || result.stdout}`,
    );
  }
  return result;
}
