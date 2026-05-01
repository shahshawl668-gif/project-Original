import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL!;

async function handler(
  req: NextRequest,
  { params }: { params: { path?: string[] } }
) {
  try {
    const path = params?.path?.join("/") || "";
    const url = `${BACKEND_URL}/${path}${req.nextUrl.search}`;

    const headers = new Headers();

    // Forward all headers safely
    req.headers.forEach((value, key) => {
      if (key !== "host") {
        headers.set(key, value);
      }
    });

    const res = await fetch(url, {
      method: req.method,
      headers,
      body:
        req.method !== "GET" && req.method !== "HEAD"
          ? await req.text()
          : undefined,
      cache: "no-store",
    });

    const responseHeaders = new Headers(res.headers);

    return new Response(await res.text(), {
      status: res.status,
      headers: responseHeaders,
    });
  } catch (error) {
    return new Response(
      JSON.stringify({
        error: "Proxy failed",
        details: error instanceof Error ? error.message : String(error),
      }),
      { status: 500 }
    );
  }
}

// Support ALL methods
export {
  handler as GET,
  handler as POST,
  handler as PUT,
  handler as DELETE,
  handler as PATCH,
  handler as OPTIONS,
};
