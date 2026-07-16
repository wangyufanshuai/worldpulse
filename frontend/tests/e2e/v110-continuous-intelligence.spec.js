import { expect, test } from '@playwright/test'

const API = process.env.WORLDPULSE_E2E_API_BASE || 'http://127.0.0.1:8010/api'

async function login(request) {
  const response = await request.post(`${API}/v3/auth/login`, {
    data: { username: 'e2e-admin', password: 'e2e administrator secret' },
  })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).csrf_token
}

test('Admin configures a governed Source and immutable Watchlist without starting a run', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })

  const csrf = await login(page.request)
  const created = await page.request.post(`${API}/projects`, {
    headers: { 'X-CSRF-Token': csrf },
    data: { title: 'V1.10 intelligence E2E', question: 'Govern public feed signals', mode: 'war_room' },
  })
  expect(created.ok()).toBeTruthy()
  const project = await created.json()

  await page.goto(`projects/${project.project_id}/war-room/intelligence`)
  const module = page.getByTestId('war-room-intelligence-module')
  await expect(module).toBeVisible()
  await expect(module).toContainText('不会自动改变风险数值、创建 Draft 或启动推演')

  await module.getByPlaceholder('Source 名称').fill('E2E Public Feed')
  await module.getByPlaceholder('https://example.org/feed.xml').fill('https://example.com/feed.xml')
  await module.getByPlaceholder('Publisher').fill('E2E Publisher')
  await module.getByPlaceholder('License').fill('Public Test')
  const sourceResponse = page.waitForResponse(response => response.url().includes('/monitoring/sources') && response.request().method() === 'POST')
  await module.getByRole('button', { name: '创建 Source' }).click()
  const sourceResult = await sourceResponse
  expect(sourceResult.status(), `${sourceResult.url()} ${await sourceResult.text()}`).toBe(200)
  await expect(module).toContainText('E2E Public Feed')

  await module.getByPlaceholder('监测清单名称').fill('E2E China Watch')
  await module.getByPlaceholder('规范值，例如 CHN').fill('CHN')
  const watchlistResponse = page.waitForResponse(response => response.url().endsWith('/watchlists') && response.request().method() === 'POST')
  await module.getByRole('button', { name: '创建清单' }).click()
  const watchlistResult = await watchlistResponse
  expect(watchlistResult.status(), await watchlistResult.text()).toBe(200)
  await expect(module).toContainText('E2E China Watch')
  await module.getByRole('button', { name: '激活' }).click()
  await expect(module).toContainText('active')

  const jobs = await page.request.get(`${API}/v2/projects/${project.project_id}/runs`)
  // No monitoring configuration action may create a lifecycle run.
  expect([200, 404, 405].includes(jobs.status())).toBeTruthy()
  if (jobs.ok()) expect((await jobs.json()).length).toBe(0)
  expect(errors).toEqual([])
})
