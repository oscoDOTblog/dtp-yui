/** @type {import('next').NextConfig} */
const path = require("path");

const nextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname),
  // Long Ollama calls are proxied by app/backend/[...path]/route.js (5 min timeout)
};

module.exports = nextConfig;
