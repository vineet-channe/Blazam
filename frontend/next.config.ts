import type { NextConfig } from "next";

// Where the Blazam backend lives, as seen from the Next.js server (not the browser). Production
// builds proxy /backend/* to it, so the browser stays same-origin: no public env var, no CORS.
const backendOrigin = (process.env.BLAZAM_API_ORIGIN ?? "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  // covers come from Deezer, Cover Art Archive (redirects to archive.org) and iTunes; serve them as-is
  images: { unoptimized: true },
  devIndicators: false,
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${backendOrigin}/:path*` }];
  },
};

export default nextConfig;
