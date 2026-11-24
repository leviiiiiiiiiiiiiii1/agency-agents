import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,
  },
  build: {
    // O chunk isolado de gráficos (Recharts) fica em ~524 kB / ~148 kB gzip.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Recharts vai para um chunk próprio (carregado em paralelo, não bloqueia a UI).
        manualChunks: {
          charts: ['recharts'],
        },
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
  },
});
