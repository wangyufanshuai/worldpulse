import { expect, test } from '@playwright/test'
import { execFile } from 'node:child_process'
import path from 'node:path'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

test('War Room lifecycle shell and modules remain interactive', async ({ page, request }) => {
  const browserErrors = []
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text())
  })
  page.on('pageerror', (error) => browserErrors.push(error.message))

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
  await expect(page.getByTestId('consistency-audit-panel')).toBeVisible()
  await expect(page.getByTestId('consistency-status')).toHaveText('待评估')
  await expect(page.getByTestId('war-room-lifecycle-kpis')).toBeVisible()

  await page.getByLabel('设置').click()
  await page.getByTestId('lifecycle-engine-mode').selectOption('hybrid')
  await page.getByRole('button', { name: '返回战情总览' }).click()

  await page.getByTestId('war-room-run-action').click()
  await expect(page.getByTestId('war-room-cancel-action')).toBeEnabled()
  await page.getByTestId('war-room-pause-action').click()
  await expect(page.getByTestId('war-room-resume-action')).toBeEnabled()
  await page.getByTestId('war-room-resume-action').click()
  await page.getByTestId('war-room-cancel-action').click()
  await expect(page.getByTestId('war-room-lifecycle-control')).toContainText('cancelled', { timeout: 15_000 })
  await expect(page.getByTestId('war-room-retry-action')).toBeEnabled({ timeout: 15_000 })
  await page.getByTestId('war-room-retry-action').click()

  await execFileAsync('python', ['-m', 'app.workers.run_worker', '--once'], {
    cwd: path.resolve(process.cwd(), '..'),
    env: { ...process.env, WORLDPULSE_DB_PATH: process.env.WORLDPULSE_E2E_DB },
  })
  await expect(page.getByTestId('consistency-status')).toHaveText('部分评估')
  await expect(page.getByTestId('consistency-finding')).toHaveCount(1)
  await expect(page.getByTestId('consistency-artifact-hash')).toHaveText(/^[a-f0-9]{64}$/)
  await expect(page.getByTestId('agent-proposal-decision')).toHaveCount(4)
  await expect(page.getByTestId('agent-proposal-decisions')).toContainText('已接受')
  await expect(page.getByTestId('lifecycle-kpi-agent_proposals')).toContainText('4')
  await expect(page.getByTestId('lifecycle-kpi-consistency')).toContainText('部分评估')
  await expect(page.getByTestId('hybrid-result-summary')).toBeVisible()
  await expect(page.getByTestId('hybrid-accepted-count')).toHaveText('4')
  await expect(page.getByTestId('hybrid-final-hash')).toHaveText(/^[a-f0-9]{64}$/)
  await page.getByTestId('hybrid-view-toggle').getByRole('button', { name: '确定性基线' }).click()
  await expect(page.getByTestId('hybrid-view-toggle').getByRole('button', { name: '确定性基线' })).toHaveClass(/active/)
  await page.getByTestId('hybrid-view-toggle').getByRole('button', { name: '混合最终结果' }).click()

  await page.getByTestId('war-room-map-tick-7').click()
  await expect(page.getByTestId('war-room-lifecycle-map')).toContainText('D+7')
  await page.getByTestId('war-room-causal-toggle').click()
  await expect(page.getByTestId('war-room-graph-module')).toBeVisible()

  await page.getByRole('link', { name: '智能分析' }).click()
  await expect(page.getByTestId('agent-negotiation-panel')).toBeVisible()
  await expect(page.getByTestId('agent-negotiation-proposal')).toHaveCount(4)
  await page.getByRole('link', { name: '数据中台' }).click()
  await expect(page.getByTestId('lifecycle-artifact-table')).toBeVisible()
  await expect(page.getByTestId('lifecycle-step-table')).toBeVisible()
  await expect(page.getByTestId('lifecycle-attempt-table')).toBeVisible()
  await expect(page.getByTestId('lifecycle-invocations')).toBeVisible()
  await page.getByLabel('设置').click()
  await expect(page.getByTestId('agent-provider-setting')).toContainText('mock')
  await expect(page.getByTestId('worker-status-setting')).toContainText('completed')

  const modules = {
    sandbox: 'war-room-sandbox-module', analysis: 'war-room-analysis-module',
    graph: 'war-room-graph-module', data: 'war-room-data-module',
    settings: 'war-room-settings-module', replay: 'war-room-replay-module',
  }
  for (const [section, testId] of Object.entries(modules)) {
    await page.goto(`projects/${project.project_id}/war-room/${section}`)
    await expect(page.getByTestId(testId)).toBeVisible()
  }
  expect(browserErrors).toEqual([])
})
