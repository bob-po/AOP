import { existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { execCommand, execOrThrow } from "./process.js";

const GITHUB_RE =
  /^(https?:\/\/)?(www\.)?github\.com\/[\w.-]+\/[\w.-]+(\.git)?\/?$/i;
const GIT_URL_RE = /^(https?:\/\/|git@).+\.git$/i;

export function isGitHubUrl(source: string): boolean {
  return GITHUB_RE.test(source.trim()) || /github\.com[:/]/.test(source);
}

export function isRemoteGitUrl(source: string): boolean {
  const s = source.trim();
  return isGitHubUrl(s) || GIT_URL_RE.test(s) || s.startsWith("git@");
}

export function normalizeGitUrl(source: string): string {
  let url = source.trim();
  if (url.endsWith("/")) url = url.slice(0, -1);
  if (isGitHubUrl(url) && !url.endsWith(".git") && url.includes("github.com")) {
    url = `${url.replace(/\.git$/, "")}.git`;
  }
  if (!/^https?:\/\//.test(url) && !url.startsWith("git@") && isGitHubUrl(url)) {
    url = `https://${url.replace(/^\/\//, "")}`;
  }
  return url;
}

export async function cloneRepository(
  source: string,
  destDir: string,
): Promise<{ sourceDir: string; cloned: boolean }> {
  mkdirSync(dirname(destDir), { recursive: true });
  if (existsSync(destDir)) {
    rmSync(destDir, { recursive: true, force: true });
  }

  const url = normalizeGitUrl(source);
  await execOrThrow("git", ["clone", "--depth", "1", url, destDir], {
    timeoutMs: 5 * 60_000,
  });
  return { sourceDir: destDir, cloned: true };
}

export async function prepareLocalSource(
  source: string,
  destDir: string,
): Promise<{ sourceDir: string; cloned: boolean }> {
  const abs = resolve(source);
  if (!existsSync(abs) || !statSync(abs).isDirectory()) {
    throw new Error(`Local path not found or not a directory: ${source}`);
  }

  mkdirSync(dirname(destDir), { recursive: true });
  if (existsSync(destDir)) {
    rmSync(destDir, { recursive: true, force: true });
  }

  // Prefer git worktree-like copy via git clone --local when it's a git repo;
  // otherwise recursive copy with robocopy/cp.
  if (existsSync(join(abs, ".git"))) {
    await execOrThrow("git", ["clone", "--local", "--depth", "1", abs, destDir], {
      timeoutMs: 120_000,
    });
  } else if (process.platform === "win32") {
    mkdirSync(destDir, { recursive: true });
    const copied = await execCommand(
      "robocopy",
      [abs, destDir, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/nc", "/ns", "/np"],
      { timeoutMs: 120_000 },
    );
    // robocopy: exit codes 0-7 indicate success
    if (copied.code >= 8 || !existsSync(destDir) || readdirSync(destDir).length === 0) {
      await execOrThrow(
        "powershell",
        [
          "-NoProfile",
          "-Command",
          `Copy-Item -Path '${abs}\\*' -Destination '${destDir}' -Recurse -Force`,
        ],
        { timeoutMs: 120_000 },
      );
    }
  } else {
    await execOrThrow("cp", ["-a", abs, destDir], { timeoutMs: 120_000 });
  }

  return { sourceDir: destDir, cloned: false };
}

export async function prepareSource(
  source: string,
  destDir: string,
): Promise<{ sourceDir: string; cloned: boolean }> {
  if (isRemoteGitUrl(source)) {
    return cloneRepository(source, destDir);
  }
  return prepareLocalSource(source, destDir);
}
