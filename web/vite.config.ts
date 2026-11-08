import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In docker compose the API is reachable as http://api:8000; locally it's localhost.
const apiTarget = process.env.VITE_API_PROXY ?? "http://localhost:8000";
// CloudBeaver (web DBeaver) is shown on the Databases tab under /cloudbeaver/.
const cloudbeaverTarget = process.env.VITE_CLOUDBEAVER_PROXY ?? "http://localhost:8978";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
      "/cloudbeaver": { target: cloudbeaverTarget, changeOrigin: true, ws: true },
    },
    // Bind mounts from Windows hosts don't deliver file events; poll instead.
    watch: process.env.CHOKIDAR_USEPOLLING ? { usePolling: true, interval: 300 } : undefined,
  },
});
