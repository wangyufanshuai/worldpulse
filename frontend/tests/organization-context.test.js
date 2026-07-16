import { describe, expect, it } from 'vitest'
import { resolveOrganization } from '../src/composables/useOrganizationContext'

const organizations = [
  { organization_id: 'org_default', name: '默认组织' },
  { organization_id: 'org_team', name: '研判团队' },
]

describe('organization context projection', () => {
  it('restores an accessible preferred organization', () => {
    expect(resolveOrganization(organizations, 'org_team').organization_id).toBe('org_team')
  })

  it('fails closed to the default organization for a stale selection', () => {
    expect(resolveOrganization(organizations, 'org_removed').organization_id).toBe('org_default')
  })

  it('handles an account without organization membership', () => {
    expect(resolveOrganization([], 'org_removed')).toBeNull()
  })
})
