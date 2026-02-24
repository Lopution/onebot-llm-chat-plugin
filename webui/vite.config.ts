import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // Use relative assets so static build can be mounted under arbitrary base paths.
  base: './',
  build: {
    outDir: '../src/mika_chat_core/webui/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
      '/webui/api': 'http://localhost:8080',
    },
  },
})
