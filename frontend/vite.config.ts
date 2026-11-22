import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// HTTPS so a phone on the same Wi-Fi can use the camera.
// /api, /health and /internal are proxied to the FastAPI backend, so the phone needs one address only.
const backend = 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), basicSsl()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': backend,
      '/health': backend,
      '/internal': backend, // manual escalation (POST /internal/escalate)
    },
  },
})
