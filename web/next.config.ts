import type { NextConfig } from "next";

// Production: `next build` runs with NEXT_OUTPUT_EXPORT=1, emitting a static
// export that local_redact.server serves directly (same origin as the API,
// no rewrites needed or allowed in export mode).
// Dev: `next dev` proxies /api/* to the FastAPI server on :8420.
const isStaticExport = process.env.NEXT_OUTPUT_EXPORT === "1";

const nextConfig: NextConfig = isStaticExport
  ? { output: "export", turbopack: { root: __dirname } }
  : {
      turbopack: { root: __dirname },
      async rewrites() {
        return [
          { source: "/api/:path*", destination: "http://127.0.0.1:8420/api/:path*" },
        ];
      },
    };

export default nextConfig;
