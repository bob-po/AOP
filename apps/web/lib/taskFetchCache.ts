/** Short TTL + inflight dedupe so task switch does not stampede Gateway. */

const memo = new Map<string, { at: number; data: unknown }>();
const inflight = new Map<string, Promise<unknown>>();
const MAX = 48;

export function cachedGet<T>(
  key: string,
  ttlMs: number,
  run: () => Promise<T>,
  opts?: { bust?: boolean },
): Promise<T> {
  if (opts?.bust) {
    memo.delete(key);
    inflight.delete(key);
  }
  const now = Date.now();
  const hit = memo.get(key);
  if (hit && now - hit.at < ttlMs) {
    return Promise.resolve(hit.data as T);
  }
  const pending = inflight.get(key);
  if (pending) return pending as Promise<T>;
  const p = run()
    .then((data) => {
      if (memo.size >= MAX) {
        const oldest = memo.keys().next().value;
        if (oldest) memo.delete(oldest);
      }
      memo.set(key, { at: Date.now(), data });
      inflight.delete(key);
      return data;
    })
    .catch((err) => {
      inflight.delete(key);
      throw err;
    });
  inflight.set(key, p);
  return p;
}

export function invalidateTaskCache(taskId: string): void {
  const needle = `:${taskId}`;
  for (const k of [...memo.keys()]) {
    if (k.includes(needle) || k.endsWith(taskId)) memo.delete(k);
  }
  for (const k of [...inflight.keys()]) {
    if (k.includes(needle) || k.endsWith(taskId)) inflight.delete(k);
  }
}
