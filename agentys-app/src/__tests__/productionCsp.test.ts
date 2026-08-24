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

/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

describe('production CSP', () => {
  it('does not allow localhost backend origins in the web index meta tag', () => {
    const testDir = dirname(fileURLToPath(import.meta.url))
    const indexHtml = readFileSync(resolve(testDir, '../../index.html'), 'utf8')
    const cspMeta = indexHtml.match(/<meta http-equiv="Content-Security-Policy" content="([^"]+)"/)

    expect(cspMeta?.[1]).toBeTruthy()
    expect(cspMeta?.[1]).not.toContain('localhost:5050')
    expect(cspMeta?.[1]).not.toContain('127.0.0.1:5050')
  })
})
