import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // the UI never talks to the pipeline directly; everything goes through
    // the FastAPI service (see api/main.py). On hosted deployments with no
    // backend, /api/* fails and the UI falls back to recorded-demo mode.
    const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
