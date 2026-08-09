import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const hostSource = readFileSync(
  new URL('../src/components/research-workspace/GuidedResearchHost.vue', import.meta.url),
  'utf8',
)

function openingTag(testId) {
  const marker = `data-testid="${testId}"`
  const markerIndex = hostSource.indexOf(marker)
  expect(markerIndex, `${testId} must remain in the Guided Research host`).toBeGreaterThan(-1)
  const start = hostSource.lastIndexOf('<', markerIndex)
  const end = hostSource.indexOf('>', markerIndex)
  return hostSource.slice(start, end + 1)
}

function visibilityCondition(testId) {
  const expression = openingTag(testId).match(/v-if="([^"]+)"/)?.[1]
  expect(expression, `${testId} must use a DOM visibility guard`).toBeTruthy()
  return new Function('model', `return Boolean(${expression})`)
}

function permissionModel({ write = false, review = false, status = 'draft' } = {}) {
  return {
    governance: {
      permissions: {
        write: { allowed: write },
        review: { allowed: review },
      },
      scenario: { activeDraft: { status } },
    },
  }
}

describe('Guided Research governance control visibility contract', () => {
  it.each([
    ['guided-evidence-sync', 'write', 'draft'],
    ['guided-draft-submit', 'write', 'draft'],
    ['guided-draft-approve', 'review', 'submitted'],
    ['guided-draft-revision', 'review', 'submitted'],
    ['guided-draft-clone', 'write', 'approved'],
  ])('does not render %s for a no-permission model and preserves it for authorized users', (testId, permission, status) => {
    const isVisible = visibilityCondition(testId)
    expect(isVisible(permissionModel({ status }))).toBe(false)
    expect(isVisible(permissionModel({ [permission]: true, status }))).toBe(true)
  })

  it('keeps explicit backend-authority permission reasons visible outside write/review controls', () => {
    expect(openingTag('guided-write-permission-reason')).not.toContain('v-if=')
    expect(openingTag('guided-review-permission-reason')).not.toContain('v-if=')
    expect(hostSource).toContain('{{ model.governance.permissions.write.reason }}')
    expect(hostSource).toContain('{{ model.governance.permissions.review.reason }}')
  })

  it('keeps root draft detail independent from parent diff and renders all lineage hashes', () => {
    expect(openingTag('guided-scenario-active-detail')).toContain('v-if="model.governance.scenario.activeDraft"')
    expect(openingTag('guided-scenario-active-detail')).not.toContain('scenario.diff.available')
    expect(hostSource).toContain('data-testid="guided-active-draft-hash"')
    expect(hostSource).toContain('data-testid="guided-active-pack-hash"')
    expect(hostSource).toContain('data-testid="guided-parent-draft-hash"')
    expect(hostSource).toContain('data-testid="guided-parent-pack-hash"')
    expect(hostSource).toContain('data-testid="guided-current-draft-hash"')
    expect(hostSource).toContain('data-testid="guided-current-pack-hash"')
  })

  it('disables every authorized mutation control while the shared governance guard is busy', () => {
    for (const testId of [
      'guided-evidence-sync',
      'guided-draft-submit',
      'guided-draft-approve',
      'guided-draft-revision',
      'guided-draft-clone',
    ]) {
      expect(openingTag(testId)).toContain('model.governance.busy')
    }
  })
})
