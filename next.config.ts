import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? '.next',
  allowedDevOrigins: ['127.0.0.1'],
  async rewrites() {
    const apiOrigin = process.env.API_PROXY_ORIGIN;

    if (!apiOrigin) return [];

    return {
      beforeFiles: [
        {
          source: '/api/:path*',
          destination: `${apiOrigin}/api/:path*`,
        },
      ],
    };
  },
};

export default nextConfig;
