/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async redirects() {
    // the development directory and civic list folded into the unified
    // /topics directory; query strings (?q=) pass through automatically
    return [
      { source: "/development", destination: "/topics?official=true", permanent: true },
      { source: "/civic", destination: "/topics?type=topic", permanent: true },
    ];
  },
};

export default nextConfig;
