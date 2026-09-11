import type { NextConfig } from "next";

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "img-src 'self' data: blob: https: https://images-na.ssl-images-amazon.com https://m.media-amazon.com",
  "font-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  "script-src 'self' 'unsafe-inline'",
  // connect-src 同时管着 RTCPeerConnection 的 ICE 服务器地址,不只是 fetch/XHR。
  // 少了下面这几条,远程桌面会在**同一个局域网内能连、一出网就失败**,而且浏览器
  // 不给任何明显报错——最难查的那种故障。
  // 这里的 turn: 地址必须与后端 RD_TURN_URLS 保持一致,换节点时两处一起改。
  [
    "connect-src 'self'",
    "stun:stun.l.google.com:19302",
    "turn:45.76.173.147:3478",
    "turn:64.177.117.249:3478",
  ].join(" "),
  "frame-src 'none'",
].join("; ");

const permissionsPolicy = [
  "accelerometer=()",
  "camera=()",
  "geolocation=()",
  "gyroscope=()",
  "magnetometer=()",
  "microphone=()",
  "payment=()",
  "usb=()",
].join(", ");

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: contentSecurityPolicy,
          },
          {
            key: "X-Frame-Options",
            value: "DENY",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: permissionsPolicy,
          },
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains",
          },
        ],
      },
    ];
  },
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
