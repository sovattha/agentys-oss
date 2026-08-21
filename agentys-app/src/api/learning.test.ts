import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../config', () => ({
  API_URL: 'https://api.agentys.io',
}))

vi.mock('../services/authToken', () => ({
  getAuthHeaders: () => ({ Authorization: 'Bearer test-token' }),
}))

import { fetchUserLearningCategories } from './learning'

describe('user learning API', () => {
  beforeEach(() => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        rules: [
          {
            id: 'r1',
            rule_text: 'Répondre court',
            category: 'longueur',
            scope: 'global',
            contact: '',
            confidence: 0.8,
            active: true,
          },
        ],
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('uses the account-scoped learning rules endpoint instead of the admin-only aggregate', async () => {
    const categories = await fetchUserLearningCategories()

    expect(globalThis.fetch).toHaveBeenCalledWith(
      'https://api.agentys.io/api/learning/rules',
      { headers: { Authorization: 'Bearer test-token' } }
    )
    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      expect.stringContaining('/api/learning/all'),
      expect.anything()
    )
    expect(categories).toHaveLength(1)
    expect(categories[0]).toMatchObject({
      id: 'draft-rules',
      count: 1,
    })
  })
})
