/** @type {import('next').NextConfig} */

// When running Next.js on Windows, localhost:8000 points to Windows — not WSL.
// Use the WSL2 host IP so the rewrite reaches the uvicorn backend running in WSL.
// Falls back to localhost for any non-Windows environment.
const BACKEND_HOST =
  process.env.BACKEND_URL ||
  (process.platform === "win32" ? "http://172.20.240.158:8000" : "http://localhost:8000")

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
