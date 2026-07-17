import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // the UI never talks to the pipeline directly; everything goes through
    // the FastAPI service (see api/main.py)
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
