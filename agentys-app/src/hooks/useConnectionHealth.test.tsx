import { renderHook, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Audit connectivité 2026-06-13 :
//  - chaque épisode "backend down" (bandeau affiché) émet UN event Sentry
//    taggé avec la cause (gateway / timeout / network) pour quantifier les
//    épisodes et les corréler aux deploys Railway ;
//  - quand c'est le poste de l'utilisateur qui est hors ligne
//    (navigator.onLine === false), le hook expose clientOffline et n'envoie
//    RIEN à Sentry (ce n'est pas un incident backend).

const captureMessage = vi.fn()
vi.mock('@sentry/react', () => ({
  captureMessage: (...args: unknown[]) => captureMessage(...args),
}))

import { useConnectionHealth } from './useConnectionHealth'

function emitLost(cause?: string) {
  act(() => {
    window.dispatchEvent(
      new CustomEvent('api:connection-lost', cause ? { detail: { cause } } : undefined)
    )
  })
}

function emitRestored() {
  act(() => {
    window.dispatchEvent(new CustomEvent('api:connection-restored'))
  })
}

function setNavigatorOnLine(value: boolean) {
  Object.defineProperty(window.navigator, 'onLine', {
    configurable: true,
    value,
  })
}

beforeEach(() => {
  captureMessage.mockClear()
  setNavigatorOnLine(true)
})

afterEach(() => {
  vi.useRealTimers()
  setNavigatorOnLine(true)
})

describe('useConnectionHealth — Sentry episode reporting', () => {
  it('captures one warning event tagged with the cause when the banner trips', () => {
    renderHook(() => useConnectionHealth())
    emitLost('gateway')
    expect(captureMessage).not.toHaveBeenCalled()
    emitLost('gateway')
    expect(captureMessage).toHaveBeenCalledTimes(1)
    expect(captureMessage).toHaveBeenCalledWith(
      'connection_lost',
      expect.objectContaining({
        level: 'warning',
        tags: expect.objectContaining({ cause: 'gateway' }),
      })
    )
  })

  it('does not re-capture while the same episode continues', () => {
    renderHook(() => useConnectionHealth())
    emitLost('timeout')
    emitLost('timeout')
    emitLost('timeout')
    emitLost('timeout')
    expect(captureMessage).toHaveBeenCalledTimes(1)
  })

  it('captures again for a new episode after restoration', () => {
    renderHook(() => useConnectionHealth())
    emitLost('network')
    emitLost('network')
    emitRestored()
    emitLost('gateway')
    emitLost('gateway')
    expect(captureMessage).toHaveBeenCalledTimes(2)
  })

  it('tags cause=unknown when the lost event has no detail (legacy emitters)', () => {
    renderHook(() => useConnectionHealth())
    emitLost()
    emitLost()
    expect(captureMessage).toHaveBeenCalledWith(
      'connection_lost',
      expect.objectContaining({ tags: expect.objectContaining({ cause: 'unknown' }) })
    )
  })
})

describe('useConnectionHealth — client offline detection', () => {
  it('reports clientOffline from navigator.onLine and the offline/online events', () => {
    const { result } = renderHook(() => useConnectionHealth())
    expect(result.current.clientOffline).toBe(false)

    setNavigatorOnLine(false)
    act(() => {
      window.dispatchEvent(new Event('offline'))
    })
    expect(result.current.clientOffline).toBe(true)

    setNavigatorOnLine(true)
    act(() => {
      window.dispatchEvent(new Event('online'))
    })
    expect(result.current.clientOffline).toBe(false)
  })

  it('starts clientOffline=true when mounted without network', () => {
    setNavigatorOnLine(false)
    const { result } = renderHook(() => useConnectionHealth())
    expect(result.current.clientOffline).toBe(true)
  })

  it('never reports a Sentry episode while the client itself is offline', () => {
    setNavigatorOnLine(false)
    renderHook(() => useConnectionHealth())
    act(() => {
      window.dispatchEvent(new Event('offline'))
    })
    emitLost('network')
    emitLost('network')
    expect(captureMessage).not.toHaveBeenCalled()
  })
})
