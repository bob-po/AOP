/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["pptx-preview"],
  async redirects() {
    return [
      { source: "/favicon.ico", destination: "/favicon.svg", permanent: false },
    ];
  },
};

module.exports = nextConfig;
