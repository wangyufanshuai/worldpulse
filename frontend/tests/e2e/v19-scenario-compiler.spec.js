import { expect, test } from '@playwright/test'
import { execFile } from 'node:child_process'
import path from 'node:path'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)
const API = process.env.WORLDPULSE_E2E_API_BASE || 'http://127.0.0.1:8010/api'

async function login(request, username, password) {
  const response = await request.post(`${API}/v3/auth/login`, { data: { username, password } })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).csrf_token
}

test('Analyst/Admin compiles evidence and independent Reviewer approves a negotiation run', async ({ page }) => {
  test.setTimeout(120_000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })

  let csrf = await login(page.request, 'e2e-admin', 'e2e administrator secret')
  const created = await page.request.post(`${API}/projects`, {
    headers: { 'X-CSRF-Token': csrf },
    data: { title: 'V1.9 compiler E2E', question: 'Evidence-backed negotiation', mode: 'war_room' },
  })
  expect(created.ok()).toBeTruthy()
  const project = await created.json()

  await page.goto(`projects/${project.project_id}/war-room/compiler`)
  const compiler = page.getByTestId('war-room-scenario-compiler')
  await expect(compiler).toBeVisible()
  await page.getByTestId('compiler-file-input').setInputFiles({
    name: 'governed-brief.md', mimeType: 'text/markdown',
    buffer: Buffer.from('# 30-day Strait Blockade\nUnited States and China discuss sanctions, chips and shipping.\n美国、中国、制裁、芯片与海运。'),
  })
  await compiler.getByLabel('分类').fill('conflict')
  await compiler.getByLabel('发布机构').fill('E2E Research')
  await compiler.getByLabel('许可/授权').fill('Internal Use')
  await compiler.getByLabel('观察时间').fill('2025-01-01T00:00')
  await compiler.getByLabel('截止时间').fill('2025-01-02T00:00')
  await page.getByTestId('compiler-upload-submit').click()
  await expect(compiler).toContainText('governed-brief.md')
  await compiler.getByRole('button', { name: '抽取' }).click()
  // The UI action is the primary path; the idempotent API call makes the E2E
  // deterministic if a hot-reload races the composable's first organization load.
  const documentList = await page.request.get(`${API}/v8/organizations/org_default/projects/${project.project_id}/documents`)
  const document = (await documentList.json())[0]
  const extraction = await page.request.post(`${API}/v8/organizations/org_default/projects/${project.project_id}/documents/${document.document_id}/extract`, { headers: { 'X-CSRF-Token': csrf } })
  expect(extraction.ok()).toBeTruthy()

  await execFileAsync('python', ['-m', 'app.workers.ingestion_worker', '--once'], {
    cwd: path.resolve(process.cwd(), '..'),
    env: { ...process.env, WORLDPULSE_DB_PATH: process.env.WORLDPULSE_E2E_DB },
  })
  await compiler.getByRole('button', { name: '刷新' }).click()
  await expect(compiler).toContainText('completed')
  await page.getByTestId('compiler-step-candidates').click()
  await expect(page.getByTestId('compiler-candidates-panel')).toContainText('场景预设')

  const candidatesResponse = await page.request.get(`${API}/v8/organizations/org_default/projects/${project.project_id}/scenario-candidates`)
  const candidates = await candidatesResponse.json()
  const selected = []
  const seen = new Set()
  for (const candidate of candidates) {
    if (!['scenario_preset', 'country', 'supply_chain', 'policy_action'].includes(candidate.candidate_type)) continue
    if (candidate.candidate_type === 'scenario_preset' && seen.has('scenario_preset')) continue
    const decision = await page.request.post(`${API}/v8/organizations/org_default/projects/${project.project_id}/scenario-candidates/${candidate.candidate_id}/decision`, {
      headers: { 'X-CSRF-Token': csrf }, data: { decision: 'accepted', comment: 'E2E source locator verified' },
    })
    expect(decision.ok()).toBeTruthy()
    selected.push(candidate.candidate_id); seen.add(candidate.candidate_type)
  }
  await compiler.getByRole('button', { name: '刷新' }).click()
  await page.getByTestId('compiler-step-draft').click()
  await compiler.getByLabel('人工假设理由').fill('E2E 明确记录默认参数与测试调整')
  await page.getByTestId('compiler-create-draft').click()
  await expect(compiler).toContainText('draft')
  await page.getByTestId('compiler-submit-draft').click()
  await expect(compiler).toContainText('submitted')

  const draftsResponse = await page.request.get(`${API}/v8/organizations/org_default/projects/${project.project_id}/scenario-drafts`)
  const submitted = (await draftsResponse.json()).find(item => item.status === 'submitted')
  const selfReview = await page.request.post(`${API}/v8/organizations/org_default/projects/${project.project_id}/scenario-drafts/${submitted.draft_id}/review`, {
    headers: { 'X-CSRF-Token': csrf }, data: { decision: 'approve', comment: 'must fail' },
  })
  expect(selfReview.status()).toBe(403)

  await page.request.post(`${API}/v3/auth/logout`, { headers: { 'X-CSRF-Token': csrf } })
  csrf = await login(page.request, 'e2e-reviewer', 'e2e reviewer secure secret')
  await page.reload()
  await page.getByTestId('compiler-step-review').click()
  await page.getByTestId('compiler-approve-draft').click()
  await expect(compiler).toContainText('approved')

  await page.request.post(`${API}/v3/auth/logout`, { headers: { 'X-CSRF-Token': csrf } })
  await login(page.request, 'e2e-admin', 'e2e administrator secret')
  await page.reload()
  await page.getByTestId('compiler-step-run').click()
  await page.getByTestId('compiler-engine-mode').selectOption('negotiation')
  await page.getByTestId('compiler-create-run').click()
  await expect(compiler).toContainText('运行已进入生命周期队列')
  await expect(compiler.locator('.run-created code')).toHaveText(/^(run_|job_)/)
  // Drain the run created by this test so the next serial SQLite test cannot claim it.
  await execFileAsync('python', ['-m', 'app.workers.run_worker', '--once'], {
    cwd: path.resolve(process.cwd(), '..'),
    env: { ...process.env, WORLDPULSE_DB_PATH: process.env.WORLDPULSE_E2E_DB },
  })
  expect(errors).toEqual([])
})
