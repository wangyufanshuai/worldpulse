import { defineConfig, devices } from '@playwright/test'

const e2eDb = process.env.WORLDPULSE_E2E_DB || `data/worldpulse-e2e-${process.pid}.db`
process.env.WORLDPULSE_E2E_DB = e2eDb
process.env.AGENT_PROVIDER = 'mock'

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
      command: 'python -m app.manage create-admin --username e2e-admin --display-name "E2E Admin" --password "e2e administrator secret" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8010',
      cwd: '..',
      env: { WORLDPULSE_DB_PATH: e2eDb, AGENT_PROVIDER: 'mock', WORLDPULSE_AUTH_MODE: 'local', WORLDPULSE_AUTO_MIGRATE: '1' },
      url: 'http://127.0.0.1:8010/api/health',
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      url: 'http://127.0.0.1:5173/studio/',
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
