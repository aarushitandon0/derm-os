import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

// Node global, typed here so the app doesn't need @types/node.
declare const process: { env: Record<string, string | undefined> };

// `npm run dev` for laptop work. `npm run dev:https` to open it on a phone over
// the LAN: phone browsers only allow the camera on https (or localhost).
// On Vercel the API lives on Render, so a production build without VITE_API_BASE would call
// the Vercel origin and every request would 404. Fail that build with a clear message instead.
if (process.env.VERCEL && !(process.env.VITE_API_BASE ?? "").trim()) {
  throw new Error("Set VITE_API_BASE to the Render API URL (e.g. https://dermos-api.onrender.com) in Vercel -> Settings -> Environment Variables.");
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === "https" ? [basicSsl()] : [])],
  server: {
    host: true,
    // DERMOS_API_PROXY: another local API port, e.g. http://127.0.0.1:8010 (default 8000).
    proxy: {
      "/api": process.env.DERMOS_API_PROXY ?? "http://127.0.0.1:8000",
      "/media": process.env.DERMOS_API_PROXY ?? "http://127.0.0.1:8000",
      "/health": process.env.DERMOS_API_PROXY ?? "http://127.0.0.1:8000",
    },
  },
}));
