export interface HealthCheckOptions {
  url: string;
  timeoutMs?: number;
  retries?: number;
  intervalMs?: number;
  acceptStatus?: number[];
}

export interface HealthCheckResult {
  ok: boolean;
  url: string;
  statusCode?: number;
  bodyPreview?: string;
  attempts: number;
  error?: string;
}

export async function healthCheck(options: HealthCheckOptions): Promise<HealthCheckResult> {
  const retries = options.retries ?? 10;
  const intervalMs = options.intervalMs ?? 2000;
  const timeoutMs = options.timeoutMs ?? 5000;
  const accept = options.acceptStatus ?? [
    200, 201, 204, 301, 302, 304,
    // App is listening even if route/auth is missing
    401, 403, 404,
  ];

  let lastError = "";
  for (let attempt = 1; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(options.url, {
        method: "GET",
        redirect: "follow",
        signal: controller.signal,
      });
      clearTimeout(timer);
      const text = await res.text().catch(() => "");
      if (accept.includes(res.status)) {
        return {
          ok: true,
          url: options.url,
          statusCode: res.status,
          bodyPreview: text.slice(0, 200),
          attempts: attempt,
        };
      }
      lastError = `HTTP ${res.status}`;
    } catch (err) {
      clearTimeout(timer);
      lastError = err instanceof Error ? err.message : String(err);
    }
    if (attempt < retries) {
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  }

  return {
    ok: false,
    url: options.url,
    attempts: retries,
    error: lastError,
  };
}

export function guessHealthUrls(port: number, extra: string[] = []): string[] {
  const bases = [`http://127.0.0.1:${port}`, `http://localhost:${port}`];
  const paths = [
    "/",
    "/health",
    "/healthz",
    "/api/health",
    "/ready",
    "/status",
    "/doc.html",
    "/swagger-ui.html",
    "/actuator/health",
  ];
  const urls: string[] = [...extra];
  for (const b of bases) {
    for (const p of paths) urls.push(`${b}${p === "/" ? "" : p}`);
  }
  return [...new Set(urls)];
}

export async function probeAny(urls: string[]): Promise<HealthCheckResult> {
  let last: HealthCheckResult | undefined;
  for (const url of urls) {
    const result = await healthCheck({ url, retries: 3, intervalMs: 1500, timeoutMs: 4000 });
    if (result.ok) return result;
    last = result;
  }
  return (
    last ?? {
      ok: false,
      url: urls[0] ?? "",
      attempts: 0,
      error: "No URLs to probe",
    }
  );
}
