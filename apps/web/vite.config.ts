import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// The dev server proxies the API so the browser sees one origin: the session
// cookie and CSRF header work without CORS. Ports follow the shared-env rules.
const api = process.env.WALTRIX_API_TARGET ?? "http://127.0.0.1:4820";

export default defineConfig({
  // Set VITE_BASE when the app is served under a path prefix (e.g. a preview proxy).
  base: process.env.VITE_BASE ?? "/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    host: "127.0.0.1",
    port: Number(process.env.WEB_PORT ?? 4821),
    strictPort: true,
    proxy: { "/api": { target: api, changeOrigin: false } },
  },
  preview: { host: "127.0.0.1", port: Number(process.env.WEB_PORT ?? 4821) },
  build: {
    sourcemap: true,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: { charts: ["recharts"], react: ["react", "react-dom", "react-router-dom"] },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
