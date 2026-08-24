/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

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
