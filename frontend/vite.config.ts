import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The backend never enables CORS on purpose (see backend/app/main.py) -
// session cookies only work same-origin. In production FastAPI serves the
// built frontend and the /api/* routes from the same origin. In dev, Vite
// proxies /api to the FastAPI backend so the browser still only ever talks
// to one origin, matching production.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});
