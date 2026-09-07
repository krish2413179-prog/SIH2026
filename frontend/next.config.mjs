/** @type {import('next').NextConfig} */

const rawBackend =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  process.env.BACKEND_URL ||
  "https://sih2026-wqbe.onrender.com"

const BACKEND_HOST = rawBackend.replace(/\/+$/, "")

const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${BACKEND_HOST}/api/:path*`,
      },
    ]
  },
}

export default nextConfig

