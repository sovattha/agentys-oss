import { render, screen, fireEvent, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from 'i18next'

// Review F08 : useConnectionHealth capture un event Sentry quand le bandeau
// s'affiche — mocker le SDK pour ne pas traverser du code Sentry réel en test.
vi.mock('@sentry/react', () => ({ captureMessage: vi.fn() }))

import { ConnectionBanner } from './ConnectionBanner'

// Y001 regression: the backend can go briefly unreachable (502 burst / restart)
// while /api/health stays green, leaving silent empty views. ConnectionBanner +
// useConnectionHealth surface a debounced "reconnecting" strip from the
// api:connection-lost / api:connection-restored window events emitted by api.ts.

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

afterEach(() => {
  vi.useRealTimers()
})

function emitLost() {
  act(() => {
    window.dispatchEvent(new Event('api:connection-lost'))
  })
}

function emitRestored() {
  act(() => {
    window.dispatchEvent(new Event('api:connection-restored'))
  })
}

describe('ConnectionBanner (Y001)', () => {
  it('renders nothing while the backend is reachable', () => {
    render(<ConnectionBanner />)
    expect(screen.queryByTestId('connection-banner')).toBeNull()
  })

  it('does not flash on a single blip, but shows after 2 consecutive failures', () => {
    render(<ConnectionBanner />)
    emitLost()
    // One failure: still hidden (api.ts already absorbs single blips via retry).
    expect(screen.queryByTestId('connection-banner')).toBeNull()
    emitLost()
    expect(screen.queryByTestId('connection-banner')).not.toBeNull()
    expect(screen.queryByText('Connection lost — reconnecting…')).not.toBeNull()
  })

  it('shows a single sustained failure once the 3s grace window elapses', () => {
    vi.useFakeTimers()
    render(<ConnectionBanner />)
    emitLost()
    expect(screen.queryByTestId('connection-banner')).toBeNull()
    act(() => {
      vi.advanceTimersByTime(3000)
    })
    expect(screen.queryByTestId('connection-banner')).not.toBeNull()
  })

  it('auto-hides when the backend is restored', () => {
    render(<ConnectionBanner />)
    emitLost()
    emitLost()
    expect(screen.queryByTestId('connection-banner')).not.toBeNull()
    emitRestored()
    expect(screen.queryByTestId('connection-banner')).toBeNull()
  })

  it('calls onRetry and optimistically hides when Retry is clicked', () => {
    const onRetry = vi.fn()
    render(<ConnectionBanner onRetry={onRetry} />)
    emitLost()
    emitLost()
    fireEvent.click(screen.getByTestId('connection-banner-retry'))
    expect(onRetry).toHaveBeenCalledTimes(1)
    expect(screen.queryByTestId('connection-banner')).toBeNull()
  })
})

// Audit connectivité 2026-06-13 : quand c'est le poste de l'utilisateur qui a
// perdu le réseau (navigator.onLine === false), le bandeau doit le dire
// explicitement au lieu d'accuser le backend — et masquer Retry (re-prober un
// backend sans réseau client est inutile).
describe('ConnectionBanner — client offline', () => {
  function setNavigatorOnLine(value: boolean) {
    Object.defineProperty(window.navigator, 'onLine', {
      configurable: true,
      value,
    })
  }

  afterEach(() => {
    setNavigatorOnLine(true)
  })

  it('shows the offline message without Retry when the client loses network', () => {
    // Review F07 : monter EN LIGNE puis basculer — ce test couvre le chemin
    // listener window:offline (le cas "monté déjà hors ligne" est couvert par
    // useConnectionHealth.test.tsx).
    render(<ConnectionBanner />)
    expect(screen.queryByTestId('connection-banner')).toBeNull()
    setNavigatorOnLine(false)
    act(() => {
      window.dispatchEvent(new Event('offline'))
    })
    expect(screen.queryByTestId('connection-banner')).not.toBeNull()
    expect(screen.queryByText(/You('|')re offline/)).not.toBeNull()
    expect(screen.queryByTestId('connection-banner-retry')).toBeNull()
  })

  it('prioritizes the client-offline message over the backend-down one', () => {
    render(<ConnectionBanner />)
    emitLost()
    emitLost()
    expect(screen.queryByText('Connection lost — reconnecting…')).not.toBeNull()
    setNavigatorOnLine(false)
    act(() => {
      window.dispatchEvent(new Event('offline'))
    })
    expect(screen.queryByText(/You('|')re offline/)).not.toBeNull()
    expect(screen.queryByText('Connection lost — reconnecting…')).toBeNull()
  })

  it('reverts to the normal state when the network returns', () => {
    setNavigatorOnLine(false)
    render(<ConnectionBanner />)
    act(() => {
      window.dispatchEvent(new Event('offline'))
    })
    expect(screen.queryByTestId('connection-banner')).not.toBeNull()
    setNavigatorOnLine(true)
    act(() => {
      window.dispatchEvent(new Event('online'))
    })
    expect(screen.queryByTestId('connection-banner')).toBeNull()
  })
})
