import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  outputDir: '../.local/playwright-results',
  timeout: 45_000,
  expect: { timeout: 7_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [
    ['list'],
    ['html', { outputFolder: '../.local/playwright-report', open: 'never' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    channel: 'chromium',
    launchOptions: { args: ['--disable-gpu'] },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } },
    },
    {
      name: 'mobile',
      use: { ...devices['Pixel 7'], viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: [
    {
      command: 'cd ../backend && uv run --frozen --env-file ../.env python tests/serve_e2e.py',
      url: 'http://127.0.0.1:8010/api/health',
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173',
      url: 'http://127.0.0.1:5173',
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
})
