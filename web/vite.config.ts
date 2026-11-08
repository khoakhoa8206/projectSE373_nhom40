import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// /api đi qua proxy để cookie session cùng origin với PWA (hợp đồng P4 trong AGENTS.md).
const proxy = { "/api": "http://localhost:8000" };

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  // `npm run build && npm run preview` để thử service worker / cài PWA. Điện thoại cần HTTPS mới cài được và lấy được vị trí:
  // cho phép host của tunnel HTTPS tạm (docs/pwa.md), host lạ khác vẫn bị chặn.
  preview: { proxy, allowedHosts: [".trycloudflare.com"] },
});
