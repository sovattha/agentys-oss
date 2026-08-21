import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Map @/ to src/ (matches tsconfig paths)
      '@/': path.resolve(__dirname, 'src') + '/',
      // Mock Tauri plugins for testing (Story 9-2)
      '@tauri-apps/plugin-shell': path.resolve(__dirname, 'src/__tests__/__mocks__/@tauri-apps/plugin-shell.ts'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.ts'],
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/e2e/**',
      '**/*.spec.ts',
    ],
  },
})
