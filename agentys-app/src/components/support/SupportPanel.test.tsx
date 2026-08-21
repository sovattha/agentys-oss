import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SupportPanel } from './SupportPanel'

// Stub the api client so the panel doesn't try to fire a real WS / fetch.
vi.mock('../../services/api', () => ({
  apiClient: {
    sendNewEmail: vi.fn().mockResolvedValue({ ok: true }),
  },
}))

describe('SupportPanel — welcome screen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  function open() {
    return render(
      <SupportPanel
        isOpen
        onClose={vi.fn()}
        accountEmail="alex@example.com"
      />,
    )
  }

  it('does not leak the old hardcoded FR card labels (regression: 2026-05-15 audit)', () => {
    open()

    // Old hardcoded FR card labels — must not appear in any locale rendering.
    expect(screen.queryByText('Brouillons IA')).toBeNull()
    expect(screen.queryByText('Style IA')).toBeNull()
    expect(screen.queryByText('Productivité')).toBeNull()
    expect(screen.queryByText('Un problème')).toBeNull()
    expect(screen.queryByText('Suggérer une amélioration')).toBeNull()
  })

  it('does not show the older verbose "Je suis l\'assistant" pitch', () => {
    open()

    expect(
      screen.queryByText(/Je suis l'assistant Agentys\. Que puis-je faire pour vous/i),
    ).toBeNull()
  })

  it('renders exactly four welcome cards and three popular guides', () => {
    const { container } = open()

    expect(container.querySelectorAll('.sp-welcome-card').length).toBe(4)
    expect(container.querySelectorAll('.sp-welcome-article').length).toBe(3)
  })

  it('renders two secondary action links (idea / bug)', () => {
    const { container } = open()

    // "Browse help" was removed from the welcome footer (the FAQ stays
    // reachable via the Popular guides + fallback), leaving idea + bug.
    expect(container.querySelectorAll('.sp-welcome-link').length).toBe(2)
  })

  it('renders the intro block with greeting (no avatar/dot — they live in the panel header)', () => {
    const { container } = open()

    expect(container.querySelector('.sp-welcome-intro')).not.toBeNull()
    expect(container.querySelector('.sp-welcome-text')).not.toBeNull()
    // The welcome avatar + green status dot were removed — Agentys mark lives in the panel header.
    expect(container.querySelector('.sp-welcome-avatar')).toBeNull()
    expect(container.querySelector('.sp-welcome-online-dot')).toBeNull()
  })
})
