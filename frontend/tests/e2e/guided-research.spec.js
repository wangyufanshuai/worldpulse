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
  await expect(page.getByTestId('guided-governance-context')).toContainText('候选治理上下文')
  await expect(page.getByTestId('guided-governance-context')).toContainText('抽取候选不是已批准 Evidence')
  await expect(page.getByTestId('guided-evidence-governance')).toContainText('暂无 Evidence')
  await expect(page.getByTestId('guided-evidence-gates')).toContainText('尚无受治理 Evidence 快照或声明')
  await expect(page.getByTestId('guided-scenario-state-rail')).toContainText('候选')
  await expect(page.getByTestId('guided-scenario-state-rail')).toContainText('草稿')
  await expect(page.getByTestId('guided-scenario-state-rail').locator('li').nth(0)).toContainText('当前')
  await expect(page.getByTestId('guided-scenario-state-rail').locator('li').nth(1)).toContainText('待处理')
  await expect(page.getByTestId('guided-scenario-gates')).toContainText('尚无受治理 Scenario Draft')
  await expect(page.getByTestId('guided-scenario-diff-unavailable')).toContainText('尚未选择 Scenario Draft detail')
  await expect(page.getByTestId('guided-experiment-matrix')).toBeVisible()
  await expect(page.getByTestId('guided-experiment-matrix-gates')).toContainText('approved/frozen Scenario Draft')
  await expect(page.getByTestId('guided-experiment-row')).toHaveCount(0)
  await expect(page.getByTestId('guided-experiment-matrix').getByRole('button')).toHaveCount(0)

  await page.getByTestId('guided-run-action').click()
  await expect(page.getByTestId('guided-stage-evidence-world-model')).toContainText('被阻塞', { timeout: 20_000 })
  await expect(page.getByTestId('guided-stage-evidence-world-model')).toContainText('尚无受治理 Evidence 快照或声明')
  await page.getByTestId('guided-evidence-sync').click()
  await expect(page.getByTestId('guided-stage-evidence-world-model')).toContainText('已完成', { timeout: 20_000 })
  await expect(page.getByTestId('guided-evidence-governance')).toContainText('已校验')
  await expect(page.getByTestId('guided-stage-scenario-matrix')).toContainText('可继续')
  await expect(page.getByTestId('guided-stage-scenario-matrix')).toContainText('尚无受治理 Scenario Draft')
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

test('Guided Research renders only six rows from the existing fixed V10 project experiment', async ({ page }) => {
  const loggedIn = await page.request.post(`${API}/v3/auth/login`, {
    data: { username: 'e2e-admin', password: 'e2e administrator secret' },
  })
  expect(loggedIn.ok()).toBeTruthy()
  const csrf = (await loggedIn.json()).csrf_token
  const created = await page.request.post(`${API}/projects`, {
    headers: { 'X-CSRF-Token': csrf },
    data: { title: 'Guided Matrix E2E', question: '有限实验矩阵的 lineage 是否完整？', mode: 'research' },
  })
  expect(created.ok()).toBeTruthy()
  const project = await created.json()
  const draftHash = 'd'.repeat(64)
  const packHash = 'p'.repeat(64)
  const approvedDraft = {
    draft_id: 'draft-e2e-approved', organization_id: 'org_default', project_id: project.project_id,
    parent_draft_id: null, version: 1, status: 'approved', name: 'E2E approved scenario',
    scenario: { duration_days: 30 }, manual_assumptions: {}, compiler_version: 'scenario-compiler.v1',
    evidence_pack_id: 'pack-e2e', evidence_pack_hash: packHash, draft_hash: draftHash,
    created_by_user_id: 'e2e-admin', candidate_ids: [], reviews: [], created_at: '2026-08-10T00:00:00Z',
  }
  const evaluationBatch = {
    batch_id: 'eval-e2e', organization_id: 'org_default', project_id: project.project_id,
    scenario_draft_id: approvedDraft.draft_id, scenario_draft_hash: draftHash,
    evidence_pack_hash: packHash, suite_id: 'project-experiment.v1', suite_hash: 's'.repeat(64),
    rule_pack_id: 'rules-e2e', rule_pack_hash: 'r'.repeat(64), runtime_profile: {},
    runtime_profile_hash: 't'.repeat(64), provider_mode: 'mock', source_type: 'project', status: 'queued',
    total_members: 7, completed_members: 0, failed_members: 0, safety_status: 'pending',
    quality_status: 'pending', metrics: {}, gate_manifest_hash: 'g'.repeat(64), root_batch_id: 'eval-e2e',
    created_at: '2026-08-10T00:00:00Z',
    updated_at: '2026-08-10T00:00:00Z', evaluation_track: 'project_experiment',
  }
  const memberSpecs = [
    ['deterministic', 1], ['hybrid', 11], ['hybrid', 29], ['hybrid', 47],
    ['negotiation', 11], ['negotiation', 29], ['negotiation', 47],
  ]
  const members = memberSpecs.map(([engineMode, seed], index) => ({
    member_id: `member-e2e-${index}`, batch_id: evaluationBatch.batch_id, case_id: 'case-e2e',
    engine_mode: engineMode, seed, run_id: null, status: 'pending', metrics: {}, artifact_refs: [],
    created_at: '2026-08-10T00:00:00Z', updated_at: '2026-08-10T00:00:00Z',
    input_hash: String.fromCharCode(97 + index).repeat(64), verification_status: 'pending',
  }))

  await page.route('**/api/v8/organizations/*/projects/*/scenario-drafts*', async route => {
    const url = new URL(route.request().url())
    await route.fulfill({ json: url.pathname.endsWith('/scenario-drafts') ? [approvedDraft] : approvedDraft })
  })
  await page.route('**/api/v8/organizations/*/projects/*/scenario-drafts/draft-e2e-approved', route => route.fulfill({
    json: approvedDraft,
  }))
  await page.route('**/api/v4/evidence/packs/pack-e2e', route => route.fulfill({
    json: { pack_id: 'pack-e2e', project_id: project.project_id, manifest_hash: packHash },
  }))
  await page.route(`**/api/v4/projects/${project.project_id}/evidence-summary`, route => route.fulfill({
    json: {
      project_id: project.project_id, source_count: 1, snapshot_count: 1, claim_count: 1,
      linked_claim_count: 1, pack_count: 1, coverage: 1, integrity_status: 'verified',
      cutoff_safe: true, sources: [], recent_snapshots: [], recent_claims: [],
      generated_at: '2026-08-10T00:00:00Z',
    },
  }))
  await page.route('**/api/v10/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/members')) return route.fulfill({ json: members })
    if (path.endsWith('/metrics')) return route.fulfill({ json: [] })
    if (path.includes('/organizations/')) return route.fulfill({ json: [evaluationBatch] })
    return route.fulfill({ json: evaluationBatch })
  })

  await page.goto(`projects/${project.project_id}`)
  const matrix = page.getByTestId('guided-experiment-matrix')
  await expect(matrix).toBeVisible()
  await expect(matrix.getByTestId('guided-experiment-row')).toHaveCount(6)
  await expect(matrix.getByTestId('guided-experiment-row-budget')).toContainText('另有 1 行')
  await expect(matrix.getByTestId('guided-experiment-role-unavailable')).toHaveCount(6)
  await expect(matrix.getByTestId('guided-experiment-role-unavailable').first()).toContainText('未存储，不推断')
  await expect(matrix.getByTestId('guided-experiment-row').first()).toContainText('aaaaaaaaaaaa')
  await expect(matrix.getByTestId('guided-experiment-row').first()).toContainText('不可比较')
  await expect(matrix.getByTestId('guided-experiment-run-diff')).toHaveCount(0)
  await expect(matrix.getByRole('button')).toHaveCount(0)
})
