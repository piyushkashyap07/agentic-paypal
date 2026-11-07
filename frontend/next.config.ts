import type { NextConfig } from "next";

// The FastAPI backend. Requests to /api/* are forwarded there,
// so the browser only ever talks to this Next.js app.
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
