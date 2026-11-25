/** @type {import('next').NextConfig} */
const securityHeaders = [
  // The googletagmanager/clarity origins cover the optional GA4 + Clarity
  // analytics tags, which only load when the ids are baked in at build time
  // (Dockerfile ARGs: NEXT_PUBLIC_GA_MEASUREMENT_ID / NEXT_PUBLIC_CLARITY_ID).
  { key: "Content-Security-Policy", value: "default-src 'self'; script-src 'self' 'unsafe-inline' https://www.googletagmanager.com https://www.clarity.ms; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' https://api.eepy.host http://localhost:8000 http://127.0.0.1:8000 https://www.google-analytics.com https://www.googletagmanager.com https://www.clarity.ms https://c.clarity.ms; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig = {
  // Security: this SaaS has no need for HTML output escaping of rich text.
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
