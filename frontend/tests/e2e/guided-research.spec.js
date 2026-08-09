import { expect, test } from '@playwright/test'

const API = process.env.WORLDPULSE_E2E_API_BASE || 'http://127.0.0.1:8010/api'

test('Guided Research preserves the project route and exposes cited uncertainty', async ({ page }) => {
  test.setTimeout(90_000)
  const browserErrors = []
  page.on('console', message => {
    if (message.type() === 'error') browserErrors.push(message.text())
  })
  page.on('pageerror', error => browserErrors.push(error.message))
  page.on('response', response => {
    if (response.status() >= 400) browserErrors.push(`${response.status()} ${response.url()}`)
  })

  const loggedIn = await page.request.post(`${API}/v3/auth/login`, {
    data: { username: 'e2e-admin', password: 'e2e administrator secret' },
  })
  expect(loggedIn.ok()).toBeTruthy()
  const csrf = (await loggedIn.json()).csrf_token
  const created = await page.request.post(`${API}/projects`, {
    headers: { 'X-CSRF-Token': csrf },
    data: {
      title: 'Guided Research E2E',
      question: '如何区分确定性推导、事实证据和不确定性？',
      mode: 'research',
      event_types: ['conflict', 'energy'],
    },
  })
  expect(created.ok()).toBeTruthy()
  const project = await created.json()

  await page.route(`**/api/projects/${project.project_id}/run*`, async route => {
    const response = await route.fetch()
    const detail = await response.json()
    detail.report.citations.push({
      citation_id: 'E-UNBOUND-E2E',
      finding_index: 999,
      kind: 'evidence',
      target_id: 'evidence:e2e-unbound',
      title: '未绑定 E2E 证据',
      summary: '该引用必须在引用合同异常区保持可见。',
      source: 'WorldPulse E2E boundary fixture',
      confidence: 88,
    })
    await route.fulfill({ response, json: detail })
  })

  await page.goto(`projects/${project.project_id}`)
  await expect(page.getByTestId('guided-research-host')).toBeVisible()
  await expect(page.getByTestId('war-room-lifecycle-rail')).toHaveCount(0)
  await expect(page.getByTestId('guided-stage-question')).toContainText('已完成')
  await expect(page.getByTestId('guided-stage-evidence-world-model')).toContainText('被阻塞')

  await page.getByTestId('guided-run-action').click()
  await expect(page.getByTestId('guided-stage-evidence-world-model')).toContainText('已完成', { timeout: 20_000 })
  await expect(page.getByTestId('guided-stage-scenario-matrix')).toContainText('可继续')
  await expect(page.getByTestId('guided-stage-runs-compare')).toContainText('可继续')
  await expect(page.getByTestId('guided-stage-runs-compare')).toContainText('尚未加载真实 Run Diff 投影')
  await expect(page.getByTestId('guided-stage-cited-brief')).toContainText('已完成')
  await expect(page.getByTestId('guided-cited-brief')).toBeVisible()
  await expect(page.getByTestId('guided-uncertainty-section')).toContainText('不确定性')
  await expect(page.getByTestId('guided-evidence-section')).toContainText('事实证据')
  const unboundCitations = page.getByTestId('guided-unbound-citations')
  await expect(unboundCitations).toBeVisible()
  await expect(unboundCitations).toContainText('E-UNBOUND-E2E')
  await expect(unboundCitations).toContainText('finding_index=999')
  await expect(unboundCitations).toContainText('该引用必须在引用合同异常区保持可见。')

  const findingButton = page.getByTestId('guided-findings').getByRole('button').first()
  await findingButton.focus()
  await findingButton.click()
  const citationDialog = page.getByRole('dialog', { name: await findingButton.locator('span').innerText() })
  await expect(citationDialog).toBeVisible()
  await expect(citationDialog).toContainText('证据到结论')
  await expect(citationDialog).toContainText('渲染器血缘')
  const closeCitationButton = citationDialog.getByRole('button', { name: '关闭' })
  await expect(closeCitationButton).toBeFocused()
  await expect(page.locator('.studio-header')).toHaveJSProperty('inert', true)
  await page.keyboard.press('Tab')
  await expect(closeCitationButton).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(closeCitationButton).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(citationDialog).toHaveCount(0)
  await expect(page.locator('.studio-header')).toHaveJSProperty('inert', false)
  await expect(findingButton).toBeFocused()
  await expect(page.getByRole('textbox', { name: '研究追问' })).toBeVisible()

  expect(browserErrors).toEqual([])
})
