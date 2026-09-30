/**
 * Response headers for every page.
 *
 * The content policy is enforced, and deliberately no stricter than what can
 * be verified to work: Next.js 14 inlines its hydration scripts, so scripts
 * need 'unsafe-inline' until nonces are wired through (docs/SECURITY.md, the
 * open item on a nonce-based policy). What it does close off today: framing
 * by any other site, plugins, <base> hijacking, forms posting elsewhere, and
 * loading scripts, styles, fonts or connections from anywhere but this origin
 * and the API.
 */
const dev = process.env.NODE_ENV !== "production";

function apiOrigin() {
  try {
    const raw = process.env.NEXT_PUBLIC_API_URL?.trim();
    return raw ? new URL(raw).origin : "";
  } catch {
    return "";
  }
}

const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin()}${dev ? " ws: wss:" : ""}`.trim(),
  "frame-ancestors 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  ...(dev ? [] : [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]),
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Nothing uses next/image. Switching the optimiser off removes the
  // /_next/image endpoint, and with it a class of advisories against it.
  images: { unoptimized: true },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
