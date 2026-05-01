import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const HOP_BY_REQUEST_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
]);

/** Server-only: real FastAPI origin (no trailing slash). */
function backendOrigin(): string {
  const raw =
    process.env.BACKEND_URL ??
    process.env.RELAY_BACKEND_ORIGIN ??
    process.env.API_INTERNAL_URL ??
    "";
  return raw.trim().replace(/\/$/, "");
}

async function proxy(req: NextRequest, segments: string[]) {
  const base = backendOrigin();
  if (!base) {
    return NextResponse.json(
      {
        success: false,
        data: null,
        error: {
          detail:
            "Server proxy is enabled but BACKEND_URL is unset. Add BACKEND_URL=https://api.peopleopslab.in to your Next.js host (Vercel → Environment Variables, not NEXT_PUBLIC).",
          code: "proxy_misconfigured",
        },
      },
      { status: 502 },
    );
  }

  const subpath = segments.join("/");
  if (!segments.length || segments[0] !== "api") {
    return NextResponse.json(
      {
        success: false,
        data: null,
        error: { detail: "Proxy only forwards /api/* paths.", code: "proxy_path" },
      },
      { status: 404 },
    );
  }
  const qs = req.nextUrl.search;
  const target = `${base}/${subpath}${qs}`;

  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (HOP_BY_REQUEST_HEADERS.has(key.toLowerCase())) return;
    headers.set(key, value);
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
    return NextResponse.json(
      {
        success: false,
        data: null,
        error: {
          detail: `Upstream unreachable (${msg}). Check BACKEND_URL and that the API accepts requests from your Next.js server.`,
          code: "upstream_unreachable",
        },
      },
      { status: 502 },
    );
  }

  const outHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (key.toLowerCase() === "transfer-encoding") return;
    outHeaders.set(key, value);
  });

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
