import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SAFE_FORWARD_HEADERS = new Set([
  "accept",
  "accept-language",
  "authorization",
  "content-type",
  "user-agent",
  "x-request-id",
  "x-tenant-id",
]);

function backendOrigin(): string {
  const raw =
    process.env.BACKEND_URL ??
    process.env.RELAY_BACKEND_ORIGIN ??
    process.env.API_INTERNAL_URL ??
    "";
  return raw.trim().replace(/\/$/, "");
}

function envelopeError(
  status: number,
  detail: string,
  code: string,
): NextResponse {
  return NextResponse.json(
    { success: false, data: null, error: { detail, code } },
    { status },
  );
}

async function proxy(req: NextRequest, segments: string[]): Promise<Response> {
  const base = backendOrigin();
  if (!base) {
    return envelopeError(
      502,
      "Server proxy is enabled but BACKEND_URL is unset. Set BACKEND_URL=https://api.peopleopslab.in on the host (Vercel → Environment Variables, NOT NEXT_PUBLIC) and redeploy.",
      "proxy_misconfigured",
    );
  }
  if (!segments.length || segments[0] !== "api") {
    return envelopeError(404, "Proxy only forwards /api/* paths.", "proxy_path");
  }

  const subpath = segments.join("/");
  const qs = req.nextUrl.search;
  const target = `${base}/${subpath}${qs}`;

  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (SAFE_FORWARD_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const init: RequestInit & { duplex?: "half" } = {
    method: req.method,
    headers,
    redirect: "follow",
  };

  if (!["GET", "HEAD"].includes(req.method) && req.body) {
    init.body = req.body;
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (e) {
    const msg = e instanceof Error ? e.message : "upstream fetch failed";
    return envelopeError(
      502,
      `Upstream API unreachable (${msg}). Check BACKEND_URL and that the API allows requests from your Next.js server.`,
      "upstream_unreachable",
    );
  }

  // Stream the response body through, preserving headers (except hop-by-hop).
  const outHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (lower === "transfer-encoding" || lower === "content-encoding") return;
    outHeaders.set(key, value);
  });
  outHeaders.set("X-Proxy-Path", "/api/proxy");

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: outHeaders,
  });
}

type Ctx = { params: { path: string[] } };

export async function GET(req: NextRequest, ctx: Ctx) {
  return proxy(req, ctx.params.path);
}
export async function POST(req: NextRequest, ctx: Ctx) {
  return proxy(req, ctx.params.path);
}
export async function PUT(req: NextRequest, ctx: Ctx) {
  return proxy(req, ctx.params.path);
}
export async function PATCH(req: NextRequest, ctx: Ctx) {
  return proxy(req, ctx.params.path);
}
export async function DELETE(req: NextRequest, ctx: Ctx) {
  return proxy(req, ctx.params.path);
}
export async function HEAD(req: NextRequest, ctx: Ctx) {
  return proxy(req, ctx.params.path);
}
export async function OPTIONS() {
  return new NextResponse(null, { status: 204 });
}
