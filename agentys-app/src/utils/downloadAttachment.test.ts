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

import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../services/authToken', () => ({
  getAuthHeaders: () => ({
    Authorization: 'Bearer test-token',
    'X-Account-Id': 'acc-1',
  }),
}))

import { downloadAttachment } from './downloadAttachment'

describe('downloadAttachment', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:attachment'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  })

  it('downloads through the authenticated API path', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob(['pdf'], { type: 'application/pdf' })),
    })
    vi.stubGlobal('fetch', fetchMock)

    await downloadAttachment('https://api.agentys.io/api/emails/msg/attachments/att/download', 'fiche.pdf')

    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.agentys.io/api/emails/msg/attachments/att/download',
      {
        headers: {
          Authorization: 'Bearer test-token',
          'X-Account-Id': 'acc-1',
        },
      },
    )
  })

  it('appends the anchor before clicking, removes it after, and defers revoke', async () => {
    vi.useFakeTimers()
    try {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        blob: () => Promise.resolve(new Blob(['pdf'], { type: 'application/pdf' })),
      }))

      const order: string[] = []
      const appendSpy = vi
        .spyOn(document.body, 'appendChild')
        .mockImplementation(((node: Node) => { order.push('append'); return node }) as typeof document.body.appendChild)
      vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => { order.push('click') })
      vi.spyOn(HTMLAnchorElement.prototype, 'remove').mockImplementation(() => { order.push('remove') })

      await downloadAttachment('https://api.agentys.io/api/d', 'fiche.pdf')

      // anchor must be attached at click time and removed after
      expect(order).toEqual(['append', 'click', 'remove'])
      // revoking synchronously can abort an in-flight blob download
      expect(URL.revokeObjectURL).not.toHaveBeenCalled()

      vi.advanceTimersByTime(1000)
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:attachment')

      appendSpy.mockRestore()
    } finally {
      vi.useRealTimers()
    }
  })
})
