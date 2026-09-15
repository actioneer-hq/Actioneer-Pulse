import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Built into ../src/voiceobs/api/static so the Python package ships the UI and the
// API serves it from one origin — no CORS, no second container.
export default defineConfig({
  plugins: [tailwindcss(), react()],
  build: { outDir: "../src/voiceobs/api/static", emptyOutDir: true },
  server: { proxy: { "/v1": "http://localhost:8000" } },
});
