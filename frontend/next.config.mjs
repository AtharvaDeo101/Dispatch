/** @type {import('next').NextConfig} */

// Where the Flask backend actually lives. Server-side only — the browser never
// sees this host, it talks to /api on this app's own origin instead.
const API_ORIGIN = process.env.INTERNAL_API_BASE_URL || "http://localhost:5000";

const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  // Same-origin proxy. Deployed, the frontend is on *.vercel.app and the
  // backend on *.onrender.com — separate registrable domains, so the session
  // cookie was third-party and Safari, Brave and Chrome-incognito refused to
  // send it, which logged every user straight back out. Routing through /api
  // keeps every request first-party.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_ORIGIN}/:path*`,
      },
    ];
  },
}

export default nextConfig
