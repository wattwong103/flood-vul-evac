import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  build: {
    rolldownOptions: {
      output: {
        // MapLibre is the single largest dependency and is only needed once the
        // map is first rendered, so it is split out of the entry chunk.
        advancedChunks: {
          groups: [
            { name: "maplibre", test: /node_modules[\\/]maplibre-gl/ },
          ],
        },
      },
    },
  },
});
