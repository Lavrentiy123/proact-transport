import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// BACKEND_ORIGIN lets parallel test runs point the proxy at their own stub.
const backend = process.env.BACKEND_ORIGIN ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': backend,
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
})
