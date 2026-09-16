/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // a second dev server (another session, a preview) can build into its own
  // dir instead of clobbering .next: NEXT_DIST_DIR=.next-alt npm run dev
  distDir: process.env.NEXT_DIST_DIR || ".next",
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
