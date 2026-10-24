import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// /api đi qua proxy để cookie session cùng origin với PWA. 127.0.0.1 thay localhost: tránh Windows thử IPv6 trước.
const proxy = { "/api": "http://127.0.0.1:8000" };

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy }, // `npm run build && npm run preview` để thử service worker / cài PWA
});
