import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";

export function ensureDir(path: string): void {
  mkdirSync(path, { recursive: true });
}

export function writeText(path: string, content: string): void {
  ensureDir(dirname(path));
  writeFileSync(path, content, "utf8");
}

export function readText(path: string): string {
  return readFileSync(path, "utf8");
}

export function readJson<T>(path: string): T {
  return JSON.parse(readText(path)) as T;
}

export function pathExists(path: string): boolean {
  return existsSync(path);
}

export function isDirectory(path: string): boolean {
  return existsSync(path) && statSync(path).isDirectory();
}

export function listFiles(dir: string, maxDepth = 3): string[] {
  const results: string[] = [];
  const walk = (current: string, depth: number) => {
    if (depth > maxDepth) return;
    let entries: string[];
    try {
      entries = readdirSync(current);
    } catch {
      return;
    }
    for (const name of entries) {
      if (name === "node_modules" || name === ".git" || name === "dist" || name === "__pycache__") {
        continue;
      }
      const full = join(current, name);
      results.push(full);
      try {
        if (statSync(full).isDirectory()) walk(full, depth + 1);
      } catch {
        // ignore
      }
    }
  };
  walk(resolve(dir), 0);
  return results;
}

export function removePath(path: string): void {
  if (existsSync(path)) rmSync(path, { recursive: true, force: true });
}
