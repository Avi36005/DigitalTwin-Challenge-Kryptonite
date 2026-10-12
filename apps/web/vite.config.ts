/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env.GLUCOTWIN_API_URL ?? "http://127.0.0.1:8000";
const proxy = { "/api": { target: apiTarget, changeOrigin: false } };

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@contracts": fileURLToPath(new URL("../../packages/contracts", import.meta.url)),
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 4173, strictPort: true, proxy },
  build: { chunkSizeWarningLimit: 1200 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
