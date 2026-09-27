import { defineConfig } from '@playwright/test'

// Locally a pre-installed Chromium can be used: PW_CHROMIUM_PATH=<path to chrome>. In CI: npx playwright install --with-deps chromium.
const executablePath = process.env.PW_CHROMIUM_PATH || undefined

export default defineConfig({
  testDir: 'e2e',
  // One stub on port 8000 is shared by all tests, so they run one by one.
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  outputDir: 'test-results/output',
  snapshotPathTemplate: 'visual-baseline/{arg}{ext}',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    locale: 'ru-RU',
    colorScheme: 'dark',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    launchOptions: {
      executablePath,
      // WebGL for MapLibre in headless Chromium without a GPU.
      args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
    },
  },
  projects: [
    { name: 'e2e', testIgnore: /visual\.spec\.ts/ },
    { name: 'visual', testMatch: /visual\.spec\.ts/ },
  ],
  webServer: {
    command: 'npx vite --host 127.0.0.1 --port 5173 --strictPort',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
