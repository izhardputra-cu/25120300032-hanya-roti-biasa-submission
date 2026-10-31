import { defineConfig, devices } from '@playwright/test'

// Verifies the real `frontend/dist` build served by FastAPI (no Vite server),
// matching the production container shape: one origin, SPA deep links, JSON API.
export default defineConfig({
  testDir: './e2e-production',
  outputDir: '../.local/playwright-production-results',
  timeout: 45_000,
  expect: { timeout: 7_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [
    ['list'],
    ['html', { outputFolder: '../.local/playwright-production-report', open: 'never' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:8020',
    channel: 'chromium',
    launchOptions: { args: ['--disable-gpu'] },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'production',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } },
    },
  ],
  webServer: [
    {
      command: 'cd ../backend && uv run --frozen --env-file ../.env python tests/serve_e2e.py',
      url: 'http://127.0.0.1:8020/api/health',
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
      env: {
        ...process.env,
        E2E_PORT: '8020',
        E2E_ORIGINS: '["http://127.0.0.1:8020"]',
        E2E_SERVE_FRONTEND: '1',
      },
    },
  ],
})
