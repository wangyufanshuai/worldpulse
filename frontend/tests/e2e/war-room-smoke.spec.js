import { expect, test } from '@playwright/test'

test('War Room lifecycle shell and modules remain interactive', async ({ page, request }) => {
  const created = await request.post('http://127.0.0.1:8010/api/projects', {
    data: {
      title: 'Playwright V0.7 smoke',
      question: '验证 War Room 生命周期与模块导航',
      mode: 'war_room',
      event_types: ['conflict', 'energy', 'trade'],
      scenario_config: { scenario_key: 'strait_blockade_30d', duration_days: 30, intensity: 0.7, propagation: 0.45 },
    },
  })
  expect(created.ok()).toBeTruthy()
  const project = await created.json()

  await page.goto(`projects/${project.project_id}/war-room/overview`)
  await expect(page.getByTestId('war-room-lifecycle-rail')).toBeVisible()
  await expect(page.getByTestId('war-room-lifecycle-map')).toBeVisible()
  await expect(page.getByTestId('war-room-event-stream')).toBeVisible()
  await expect(page.getByTestId('war-room-lifecycle-kpis')).toBeVisible()

  await page.getByTestId('war-room-run-action').click()
  await expect(page.getByTestId('war-room-cancel-action')).toBeEnabled()
  await page.getByTestId('war-room-pause-action').click()
  await expect(page.getByTestId('war-room-resume-action')).toBeEnabled()
  await page.getByTestId('war-room-resume-action').click()
  await page.getByTestId('war-room-cancel-action').click()
  await expect(page.getByTestId('war-room-retry-action')).toBeEnabled()

  const modules = {
    sandbox: 'war-room-sandbox-module', analysis: 'war-room-analysis-module',
    graph: 'war-room-graph-module', data: 'war-room-data-module',
    settings: 'war-room-settings-module', replay: 'war-room-replay-module',
  }
  for (const [section, testId] of Object.entries(modules)) {
    await page.goto(`projects/${project.project_id}/war-room/${section}`)
    await expect(page.getByTestId(testId)).toBeVisible()
  }
})
