import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/studio/',
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('/d3-') || id.includes('node_modules/d3/')) return 'vendor-d3'
          if (id.includes('lucide-vue-next')) return 'vendor-icons'
          if (id.includes('/vue/') || id.includes('vue-router')) return 'vendor-vue'
          return 'vendor'
        }
      }
    }
  },
  server: {
    proxy: {
      '/api': process.env.WORLDPULSE_API_PROXY || 'http://127.0.0.1:8010'
    }
  }
})
