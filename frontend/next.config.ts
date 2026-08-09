import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces .next/standalone — a self-contained server bundle (only the
  // node_modules it actually uses, traced dependency-by-dependency) instead
  // of requiring the full node_modules tree in the runtime image. See
  // Dockerfile for the multi-stage build this enables.
  output: "standalone",
};

export default nextConfig;
