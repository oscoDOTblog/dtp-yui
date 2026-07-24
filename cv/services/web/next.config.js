/** @type {import('next').NextConfig} */
const path = require("path");

// Docker Compose: http://api:8000 · local next dev: http://localhost:8000
const apiRewriteTarget = (
  process.env.API_REWRITE_TARGET ||
  process.env.API_BASE_INTERNAL ||
  "http://localhost:8000"
).replace(/\/$/, "");

const nextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname),
  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination: `${apiRewriteTarget}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
