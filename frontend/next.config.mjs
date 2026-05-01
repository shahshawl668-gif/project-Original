/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  /** Proxy API through this host so browsers only talk to same origin (fixes CORS / wrong client URL). */
  async rewrites() {
    const raw = (
      process.env.RELAY_BACKEND_ORIGIN ??
      process.env.API_RELAY_TARGET ??
      ""
    ).trim();
    if (!raw) return [];
    const base = raw.replace(/\/$/, "");
    return [{ source: "/api-relay/:path*", destination: `${base}/:path*` }];
  },
};

export default nextConfig;
