import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development, forward API and image requests to the FastAPI server,
// so the browser sees one origin and no CORS setup is needed.
const BACKEND = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': BACKEND,
      '/images': BACKEND,
      '/dataset': BACKEND,
    },
  },
})
