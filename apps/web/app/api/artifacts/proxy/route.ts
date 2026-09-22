import { NextRequest, NextResponse } from "next/server";

/** Proxy MinIO/public artifact URLs so the browser can fetch PPTX without CORS. */
function allowed(url: URL): boolean {
  const host = url.hostname;
  if (host === "127.0.0.1" || host === "localhost" || host === "minio") {
    return url.port === "9000" || url.port === "" || url.port === "443" || url.port === "80";
  }
  return false;
}

export async function GET(req: NextRequest) {
  const raw = req.nextUrl.searchParams.get("url");
  if (!raw) {
    return NextResponse.json({ error: "url required" }, { status: 400 });
  }
  let target: URL;
  try {
    target = new URL(raw);
  } catch {
    return NextResponse.json({ error: "invalid url" }, { status: 400 });
  }
  if (!allowed(target)) {
    return NextResponse.json({ error: "host not allowed" }, { status: 403 });
  }
  try {
    const upstream = await fetch(target.toString(), { cache: "no-store" });
    if (!upstream.ok) {
      return NextResponse.json(
        { error: `upstream ${upstream.status}` },
        { status: upstream.status },
      );
    }
    const buf = await upstream.arrayBuffer();
    const ctype =
      upstream.headers.get("content-type") ||
      "application/vnd.openxmlformats-officedocument.presentationml.presentation";
    return new NextResponse(buf, {
      status: 200,
      headers: {
        "Content-Type": ctype,
        "Cache-Control": "private, max-age=60",
      },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "proxy failed" },
      { status: 502 },
    );
  }
}
