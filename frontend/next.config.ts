import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // covers come from Deezer, Cover Art Archive (redirects to archive.org) and iTunes; serve them as-is
  images: { unoptimized: true },
  devIndicators: false,
};

export default nextConfig;
