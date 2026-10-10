import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = process.env.VIGIL_BACKEND ?? 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5180,
    proxy: {
      '/api': { target: backend, ws: true, changeOrigin: true },
      '/media': { target: backend, changeOrigin: true },
    },
  },
})
