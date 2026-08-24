/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `standalone` produces a self-contained server bundle, which is what keeps
  // the production Docker image small (no node_modules copied into the runner).
  output: "standalone",
  eslint: { ignoreDuringBuilds: false },
};

export default nextConfig;
