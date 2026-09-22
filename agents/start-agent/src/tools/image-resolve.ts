import { execCommand } from "./process.js";

/** Prefer China-friendly mirrors when Docker Hub is unreachable. */
export const IMAGE_MIRRORS = [
  "docker.m.daocloud.io/library",
  "docker.m.daocloud.io",
] as const;

export function mirrorLibraryImage(image: string): string {
  // mysql:8.0 -> docker.m.daocloud.io/library/mysql:8.0
  if (image.includes("/")) {
    // already namespaced (e.g. maven:3.9-eclipse-temurin-17 is library)
    if (
      image.startsWith("docker.m.daocloud.io/") ||
      image.startsWith("ghcr.io/") ||
      image.startsWith("quay.io/")
    ) {
      return image;
    }
    // org/name:tag
    return `docker.m.daocloud.io/${image}`;
  }
  return `docker.m.daocloud.io/library/${image}`;
}

export async function listLocalImageRefs(): Promise<Set<string>> {
  const result = await execCommand(
    "docker",
    ["images", "--format", "{{.Repository}}:{{.Tag}}"],
    { timeoutMs: 15_000 },
  );
  const set = new Set<string>();
  if (result.code !== 0) return set;
  for (const line of result.stdout.split(/\r?\n/)) {
    const t = line.trim();
    if (t && t !== "<none>:<none>") set.add(t);
  }
  return set;
}

/**
 * Resolve an image that ideally already exists locally, else prefer mirror.
 * candidates ordered by preference.
 */
export async function resolveImage(candidates: string[]): Promise<string> {
  const local = await listLocalImageRefs();
  for (const c of candidates) {
    if (local.has(c)) return c;
  }
  // Prefer mirrored forms of the first candidate
  const primary = candidates[0];
  if (primary) {
    const mirrored = mirrorLibraryImage(primary);
    if (local.has(mirrored)) return mirrored;
    return mirrored;
  }
  return candidates[0] || "alpine:3.20";
}

export function isRegistryPullError(message: string): boolean {
  return /failed to resolve reference|dial tcp|i\/o timeout|connection attempt failed|registry-1\.docker\.io|TLS handshake timeout|toomanyrequests/i.test(
    message,
  );
}
