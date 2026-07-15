import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: {
    baseURL: 'http://127.0.0.1:5173/studio/',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  outputDir: 'output/playwright',
  reporter: [['list']],
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'python -m uvicorn app.main:app --host 127.0.0.1 --port 8010',
      cwd: '..',
      env: { WORLDPULSE_DB_PATH: 'data/worldpulse-e2e.db' },
      url: 'http://127.0.0.1:8010/api/health',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      url: 'http://127.0.0.1:5173/studio/',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
