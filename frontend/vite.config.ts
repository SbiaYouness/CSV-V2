import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    cors: {
      origin: 'http://localhost:8500',   // allow only this origin
      // methods: ['GET', 'POST'],        // optional, defaults to all methods
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8500',
        changeOrigin: true,
      },
    },

  },
  optimizeDeps: {
    exclude: ['lucide-react'],
  },
});