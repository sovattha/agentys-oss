import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as Sentry from '@sentry/react'
import { ErrorBoundary } from '../components/ErrorBoundary'

vi.mock('@sentry/react', () => ({
  captureException: vi.fn(),
}))

function BrokenChild(): never {
  throw new Error('render failed')
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    vi.mocked(Sentry.captureException).mockClear()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('reports render errors to Sentry with the component stack', () => {
    render(
      <ErrorBoundary fallback={<div>Fallback</div>}>
        <BrokenChild />
      </ErrorBoundary>,
    )

    expect(screen.getByText('Fallback')).toBeInTheDocument()
    expect(Sentry.captureException).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({
        extra: expect.objectContaining({
          componentStack: expect.any(String),
        }),
      }),
    )
  })

  it('ignores benign ResizeObserver browser errors', () => {
    const consoleError = vi.mocked(console.error)
    render(
      <ErrorBoundary>
        <div>OK</div>
      </ErrorBoundary>,
    )

    window.dispatchEvent(new ErrorEvent('error', {
      message: 'ResizeObserver loop completed with undelivered notifications.',
    }))

    expect(screen.getByText('OK')).toBeInTheDocument()
    expect(consoleError).not.toHaveBeenCalled()
  })
})
