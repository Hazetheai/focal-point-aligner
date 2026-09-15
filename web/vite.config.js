import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const api = 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/health': api,
      '/prefs': api,
      '/session': api,
      '/focal': api,
      '/confirm': api,
      '/navigate': api,
      '/discard': api,
      '/duplicate': api,
      '/order': api,
      '/shift': api,
      '/mode': api,
      '/crop': api,
      '/previews': api,
      '/thumbs': api,
      '/reset': api,
      '/export': api,
      '/media': api,
      '/batch': api,
      '/import': api,
      '/arrange': api,
      '/dialog': { target: api, timeout: 600000 },
    },
  },
})
