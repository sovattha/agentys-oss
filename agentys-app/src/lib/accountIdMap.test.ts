import { afterEach, describe, expect, it } from 'vitest'
import {
  __resetAccountIdMapForTests,
  resolveToIntString,
  setAccountIdMap,
} from './accountIdMap'

describe('accountIdMap (Audit F-03)', () => {
  afterEach(() => {
    __resetAccountIdMapForTests()
  })

  it('returns null for nullish / empty / default input', () => {
    expect(resolveToIntString(null)).toBeNull()
    expect(resolveToIntString(undefined)).toBeNull()
    expect(resolveToIntString('')).toBeNull()
    expect(resolveToIntString('   ')).toBeNull()
    expect(resolveToIntString('default')).toBeNull()
  })

  it('returns the canonical int form when given an int or int-string', () => {
    expect(resolveToIntString(6)).toBe('6')
    expect(resolveToIntString('6')).toBe('6')
    expect(resolveToIntString('  6  ')).toBe('6')
  })

  // Audit regressions (2026-05-18 batch5) F-02: id=0 is a syntactically
  // valid INT PRIMARY KEY (test seeds, manual SQL, migration backfills).
  // Pre-batch5 the `n !== 0` guard returned null, silently dropping every
  // WS event for that account. The "no account" sentinel is already
  // filtered by the `s === 'default'` check at the call site above.
  it('accepts id 0 (the previous `n !== 0` guard incorrectly rejected it — F-02)', () => {
    expect(resolveToIntString(0)).toBe('0')
    expect(resolveToIntString('0')).toBe('0')
    setAccountIdMap([{ id: 0, hash_id: 'zerohash00000000' }])
    expect(resolveToIntString('zerohash00000000')).toBe('0')
  })

  it('resolves a registered hex hash to its int counterpart', () => {
    setAccountIdMap([
      { id: 6, hash_id: 'ca85336e01d3bc46' },
      { id: 7, hash_id: 'deadbeef12345678' },
    ])
    expect(resolveToIntString('ca85336e01d3bc46')).toBe('6')
    expect(resolveToIntString('deadbeef12345678')).toBe('7')
  })

  it('is case-insensitive on the hex lookup (api/init lowercases, api/accounts may not)', () => {
    setAccountIdMap([{ id: 6, hash_id: 'ca85336e01d3bc46' }])
    expect(resolveToIntString('CA85336E01D3BC46')).toBe('6')
    expect(resolveToIntString('Ca85336E01D3Bc46')).toBe('6')
  })

  it('returns null when the hex is not in the registered map (boot race)', () => {
    setAccountIdMap([{ id: 6, hash_id: 'ca85336e01d3bc46' }])
    expect(resolveToIntString('unknownhex000000')).toBeNull()
  })

  it('drops pairs without a hash_id (defensive against partial /api/init payloads)', () => {
    setAccountIdMap([
      { id: 6, hash_id: 'ca85336e01d3bc46' },
      { id: 7, hash_id: null },
      { id: 8 },
    ])
    expect(resolveToIntString('ca85336e01d3bc46')).toBe('6')
    // Int-string forms still work for ids without hashes.
    expect(resolveToIntString('7')).toBe('7')
    expect(resolveToIntString('8')).toBe('8')
  })

  it('setAccountIdMap replaces (not merges) previous pairs', () => {
    setAccountIdMap([{ id: 6, hash_id: 'aaaaaa' }])
    setAccountIdMap([{ id: 7, hash_id: 'bbbbbb' }])
    expect(resolveToIntString('aaaaaa')).toBeNull() // dropped on replace
    expect(resolveToIntString('bbbbbb')).toBe('7')
  })
})
