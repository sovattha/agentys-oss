/**
 * FAQ Import Persistence — Regression test for bug 2026-04-16
 *
 * Bug: FAQs extracted from a website via PillarSavoir's "Import FAQ" modal
 * were added to local React state but never persisted to the backend.
 * When the user reloaded or navigated away, the entries silently vanished.
 * Separately, FAQs persisted by the onboarding StepFaqImport
 * (/api/knowledge/entries) were invisible in the Training page because
 * PillarSavoir reads `data.savoir` from memoire.md only.
 *
 * Fix:
 *   1. TrainingPage.importFaq persists each entry immediately via
 *      createKnowledgeEntry().
 *   2. TrainingPage.fetchMemory merges FAQ entries from
 *      /api/knowledge/entries?category=FAQ into data.savoir.
 *   3. syncSavoirToKnowledgeEntries deletes FAQ orphans regardless of source
 *      so user deletes actually stick.
 *
 * This test hits the real backend on localhost:5050 — no mocks.
 */

import { test, expect } from '@playwright/test'

const API = 'http://127.0.0.1:5050'

async function clearFaq(request: Parameters<Parameters<typeof test>[1]>[0]['request']) {
  const resp = await request.get(`${API}/api/knowledge/entries?category=FAQ`)
  if (!resp.ok()) return
  const entries = await resp.json() as Array<{ id: string }>
  for (const e of entries) await request.delete(`${API}/api/knowledge/entries/${e.id}`)
}

test.describe.configure({ mode: 'serial' })

test.describe('FAQ import persistence', () => {
  test.beforeEach(async ({ request }) => { await clearFaq(request) })
  test.afterAll(async ({ request }) => { await clearFaq(request) })

  test('POST /api/knowledge/entries persists a FAQ and GET returns it', async ({ request }) => {
    const create = await request.post(`${API}/api/knowledge/entries`, {
      data: { title: 'Comment résilier mon abonnement ?', content: 'Paramètres > Compte > Résilier.', category: 'FAQ' },
    })
    expect(create.ok()).toBeTruthy()

    const list = await request.get(`${API}/api/knowledge/entries?category=FAQ`)
    const entries = await list.json() as Array<{ title: string; category: string; source: string }>
    expect(entries).toHaveLength(1)
    expect(entries[0].title).toBe('Comment résilier mon abonnement ?')
    expect(entries[0].category).toBe('FAQ')
  })

  test('FAQs persisted by onboarding live in knowledge_entries but NOT in memoire.md', async ({ request }) => {
    // This is the pre-condition that causes the visibility bug: the two stores
    // are independent. The frontend fix is to read from BOTH on load.
    const title = 'Quels sont les délais de livraison ?'
    await request.post(`${API}/api/knowledge/entries`, {
      data: { title, content: '3-5 jours ouvrés.', category: 'FAQ' },
    })

    const mem = await request.get(`${API}/api/memory`)
    const memJson = await mem.json()
    expect(memJson.content || '').not.toContain(title)

    const list = await request.get(`${API}/api/knowledge/entries?category=FAQ`)
    const titles = (await list.json() as Array<{ title: string }>).map(e => e.title)
    expect(titles).toContain(title)
  })

  test('Multiple POSTs accumulate — mimics the fixed importFaq loop', async ({ request }) => {
    const titles = [
      'Comment contacter le support ?',
      'Puis-je changer de formule à tout moment ?',
      'Y a-t-il un essai gratuit ?',
    ]
    for (const title of titles) {
      const r = await request.post(`${API}/api/knowledge/entries`, {
        data: { title, content: `Réponse pour: ${title}`, category: 'FAQ' },
      })
      expect(r.ok()).toBeTruthy()
    }

    const list = await request.get(`${API}/api/knowledge/entries?category=FAQ`)
    const got = (await list.json() as Array<{ title: string }>).map(e => e.title)
    for (const title of titles) expect(got).toContain(title)
  })

  test('DELETE removes a FAQ — mimics the orphan cleanup path in syncSavoirToKnowledgeEntries', async ({ request }) => {
    const post = await request.post(`${API}/api/knowledge/entries`, {
      data: { title: 'Will be deleted', content: 'body', category: 'FAQ' },
    })
    const { id } = await post.json() as { id: string }

    const del = await request.delete(`${API}/api/knowledge/entries/${id}`)
    expect(del.ok()).toBeTruthy()

    const list = await request.get(`${API}/api/knowledge/entries?category=FAQ`)
    const got = (await list.json() as Array<{ id: string }>).map(e => e.id)
    expect(got).not.toContain(id)
  })
})
