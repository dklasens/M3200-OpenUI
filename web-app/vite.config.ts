import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// On the device the agent serves the built SPA and the API from one port, so
// the app uses same-origin relative paths. For local dev/demo the mock agent
// runs separately and we proxy /api to it.
const MOCK_AGENT = process.env.M3200_MOCK_URL ?? 'http://127.0.0.1:9090'

const proxy = {
  '/api': {
    target: MOCK_AGENT,
    changeOrigin: false,
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: './',
  server: { proxy },
  preview: { proxy },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) return 'vendor'
        },
      },
    },
  },
})
