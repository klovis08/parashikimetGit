import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  serverExternalPackages: ["better-sqlite3"],
  outputFileTracingRoot: path.join(__dirname),
};

export default nextConfig;
