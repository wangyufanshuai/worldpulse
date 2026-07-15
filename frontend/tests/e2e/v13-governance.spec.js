import { expect, test } from '@playwright/test'

const API = 'http://127.0.0.1:8010/api'

async function login(request) {
  const response = await request.post(`${API}/v3/auth/login`, { data: { username: 'e2e-admin', password: 'e2e administrator secret' } })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).csrf_token
}

async function createWarRoom(request, csrf, suffix) {
  const response = await request.post(`${API}/projects`, {
    headers: { 'X-CSRF-Token': csrf },
    data: { title: `V1.3 trust ${suffix}`, question: '可信门槛是否通过？', mode: 'war_room', event_types: ['trade'] },
  })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

test('local login and logout close the session', async ({ page }) => {
  await page.goto('')
  await expect(page.getByTestId('login-screen')).toBeVisible()
  await page.getByTestId('login-username').fill('e2e-admin')
  await page.getByTestId('login-password').fill('e2e administrator secret')
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('session-role')).toContainText('管理员')
  await page.getByTestId('session-logout').click()
  await expect(page.getByTestId('login-screen')).toBeVisible()
})

test('CSRF rejects authenticated writes without the header', async ({ request }) => {
  await login(request)
  const response = await request.post(`${API}/projects`, {
    data: { title: 'No CSRF', question: 'must fail', mode: 'war_room', event_types: ['trade'] },
  })
  expect(response.status()).toBe(403)
})

test('Trust Center exposes fail-closed summary and immutable hash', async ({ page }) => {
  const csrf = await login(page.request)
  const project = await createWarRoom(page.request, csrf, 'summary')
  await page.goto(`projects/${project.project_id}/war-room/trust`)
  await expect(page.getByTestId('war-room-trust-center')).toBeVisible()
  await expect(page.getByTestId('trust-rule-version')).toContainText('1.2.0')
  await expect(page.getByTestId('trust-report-gate')).toContainText(/FAIL CLOSED|REPORT READY/)
})

test('calibration corpus is versioned and contains 30 cases', async ({ request }) => {
  await login(request)
  const response = await request.get(`${API}/v3/calibration/cases`)
  expect(response.ok()).toBeTruthy()
  const cases = await response.json()
  expect(cases).toHaveLength(30)
  expect(new Set(cases.map(item => item.case_hash)).size).toBe(30)
})

test('Rule Pack submit creates a human review case', async ({ request }) => {
  const csrf = await login(request)
  const suffix = Date.now()
  const created = await request.post(`${API}/v3/rule-packs`, {
    headers: { 'X-CSRF-Token': csrf },
    data: {
      name: `E2E candidate ${suffix}`, version: `1.3.0-e2e-${suffix}`,
      war_room_rule_version: 'war-room-rules.v1.1', consistency_rule_version: 'worldpulse-consistency.v1.2',
      action_adapter_version: 'deterministic-action-modifier.v1', scoring_weights_version: 'war-room-scoring.v1',
      evidence_policy_version: 'evidence-policy.v1',
    },
  })
  expect(created.ok()).toBeTruthy()
  const pack = await created.json()
  const submitted = await request.post(`${API}/v3/rule-packs/${pack.rule_pack_id}/submit`, { headers: { 'X-CSRF-Token': csrf } })
  expect(submitted.ok()).toBeTruthy()
  const reviews = await request.get(`${API}/v3/reviews?status=open`)
  expect((await reviews.json()).some(item => item.resource_id === pack.rule_pack_id)).toBeTruthy()
})

test('draft Rule Pack cannot bypass calibration and activate', async ({ request }) => {
  const csrf = await login(request)
  const suffix = `${Date.now()}-blocked`
  const created = await request.post(`${API}/v3/rule-packs`, {
    headers: { 'X-CSRF-Token': csrf },
    data: {
      name: `Blocked ${suffix}`, version: `1.3.0-${suffix}`,
      war_room_rule_version: 'war-room-rules.v1.1', consistency_rule_version: 'worldpulse-consistency.v1.2',
      action_adapter_version: 'deterministic-action-modifier.v1', scoring_weights_version: 'war-room-scoring.v1',
      evidence_policy_version: 'evidence-policy.v1',
    },
  })
  const pack = await created.json()
  const activated = await request.post(`${API}/v3/rule-packs/${pack.rule_pack_id}/activate`, { headers: { 'X-CSRF-Token': csrf } })
  expect(activated.status()).toBe(409)
})

test('Evidence Center syncs a run and exposes immutable provenance', async ({ page }) => {
  const csrf = await login(page.request)
  const project = await createWarRoom(page.request, csrf, 'evidence')
  const run = await page.request.post(`${API}/projects/${project.project_id}/war-room/run`, {
    headers: { 'X-CSRF-Token': csrf },
    data: { scenario_key: 'energy_export_cut', duration_days: 30, intensity: .7, propagation: .45, seed: 42 },
  })
  expect(run.ok()).toBeTruthy()
  const runId = (await run.json()).latest_run.run_id
  const synced = await page.request.post(`${API}/v4/projects/${project.project_id}/evidence/sync?run_id=${runId}`, {
    headers: { 'X-CSRF-Token': csrf },
  })
  expect(synced.ok()).toBeTruthy()

  await page.goto(`projects/${project.project_id}/war-room/evidence`)
  await expect(page.getByTestId('war-room-evidence-center')).toBeVisible()
  await expect(page.getByTestId('evidence-integrity-status')).toContainText('INTEGRITY VERIFIED')
  await expect(page.getByText('Immutable Snapshots')).toBeVisible()
  await page.getByTestId('evidence-search-input').fill('deterministic')
  await page.getByTestId('evidence-search-input').press('Enter')
  await expect(page.getByTestId('evidence-search-results')).toBeVisible()
})
