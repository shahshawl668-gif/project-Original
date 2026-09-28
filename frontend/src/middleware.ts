import { NextRequest, NextResponse } from "next/server";

/** Route dedicated domains to their sign-in page; the API still checks membership. */
export function middleware(request: NextRequest) {
  const host = (request.headers.get("host") || "").split(":")[0].toLowerCase();
  const match = host.match(/^([a-z0-9-]+)\.peopleopslab\.in$/);
  if (!match || !["/", "/login"].includes(request.nextUrl.pathname)) return NextResponse.next();
  const workspace = match[1];
  if (workspace === "www") return NextResponse.next();
  const url = request.nextUrl.clone();
  url.pathname = workspace === "admin" ? "/platform/login" : `/w/${workspace}/login`;
  return NextResponse.rewrite(url);
}

export const config = { matcher: ["/", "/login"] };
