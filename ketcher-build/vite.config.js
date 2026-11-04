import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  base: './',
  plugins: [react()],
  define: { 'process.env': {}, global: 'globalThis' },
  resolve: { alias: { events: 'events/', buffer: 'buffer/' } },
  build: { outDir: 'dist', assetsDir: 'assets', chunkSizeWarningLimit: 20000, sourcemap: false },
  worker: { format: 'es' },
});
