import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  build: {
    rollupOptions: {
      output: {
        // The three heavy dependencies change far less often than app code,
        // so splitting them keeps them cached across deploys.
        manualChunks: {
          leaflet: ['leaflet', 'react-leaflet', 'leaflet.heat'],
          charts: ['recharts'],
          motion: ['motion'],
        },
      },
    },
  },
});
