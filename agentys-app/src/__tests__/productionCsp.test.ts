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
