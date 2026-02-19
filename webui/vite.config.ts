import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/webui/',
  build: {
    outDir: '../src/mika_chat_core/webui/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/webui/api': 'http://localhost:8080',
    },
  },
})
