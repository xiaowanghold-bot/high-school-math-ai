import type { NextConfig } from "next";

const apiInternalUrl = process.env.MATH_AI_API_INTERNAL_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The desktop preview may open the local app through either hostname. Without
  // this allowance Next.js blocks development assets for 127.0.0.1, leaving
  // client-side screens (such as question review) in their loading state.
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiInternalUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
