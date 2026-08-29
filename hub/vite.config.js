import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  server: {
    host: '0.0.0.0',
    port: 8001,
    strictPort: true,
    proxy: {
      '/hub-api': {
        target: 'http://127.0.0.1:8002',
        changeOrigin: false,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 8001,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
});
