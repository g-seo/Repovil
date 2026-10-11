import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The CLI checker loses captured stdout under WSL 1, so use the TypeScript
  // compiler API during production builds. `npm run typecheck` still runs tsc.
  experimental: {
    useTypeScriptCli: false,
  },
};

export default nextConfig;

