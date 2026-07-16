import { defineConfig, devices } from '@playwright/test'

const e2eDb = process.env.WORLDPULSE_E2E_DB || `data/worldpulse-e2e-${process.pid}.db`
const apiPort = process.env.WORLDPULSE_E2E_API_PORT || '8010'
const studioPort = process.env.WORLDPULSE_E2E_STUDIO_PORT || '5173'
const apiBase = `http://127.0.0.1:${apiPort}/api`
process.env.WORLDPULSE_E2E_DB = e2eDb
process.env.WORLDPULSE_E2E_API_BASE = apiBase
process.env.AGENT_PROVIDER = 'mock'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: {
    baseURL: `http://127.0.0.1:${studioPort}/studio/`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  outputDir: 'output/playwright',
  reporter: [['list']],
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `python -m app.manage create-admin --username e2e-admin --display-name "E2E Admin" --password "e2e administrator secret" && python -m uvicorn app.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: '..',
      env: { WORLDPULSE_DB_PATH: e2eDb, AGENT_PROVIDER: 'mock', WORLDPULSE_AUTH_MODE: 'local', WORLDPULSE_AUTO_MIGRATE: '1' },
      url: `${apiBase}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${studioPort}`,
      env: { WORLDPULSE_API_PROXY: `http://127.0.0.1:${apiPort}` },
      url: `http://127.0.0.1:${studioPort}/studio/`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
