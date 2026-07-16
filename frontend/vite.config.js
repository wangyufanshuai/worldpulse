import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/studio/',
  plugins: [vue()],
  server: {
    proxy: {
      '/api': process.env.WORLDPULSE_API_PROXY || 'http://127.0.0.1:8010'
    }
  }
})
