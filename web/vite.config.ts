import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const backend = process.env.PERRY_BACKEND ?? "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    proxy: {
      "/api": backend,
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
  build: { target: "es2020", sourcemap: false },
});
