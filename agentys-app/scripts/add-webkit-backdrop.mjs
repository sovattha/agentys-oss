/**
 * Mass-adds `-webkit-backdrop-filter` before every unprefixed `backdrop-filter`
 * declaration so Safari <17.4 (still ~3% of users in 2026) renders blur effects
 * instead of opaque blocks.
 *
 * Run once: `node scripts/add-webkit-backdrop.mjs`
 *
 * Idempotent: skips lines already preceded by `-webkit-backdrop-filter:`.
 * Skipped intentionally: HTML preview files in src/themes/ (templates, not
 * shipped CSS).
 */

import { readFileSync, writeFileSync } from 'fs'
import { execSync } from 'child_process'

const list = execSync(
  'grep -rln "backdrop-filter" src/ --include="*.css"',
  { encoding: 'utf8' },
).split('\n').filter(Boolean)

let totalAdded = 0

for (const file of list) {
  const original = readFileSync(file, 'utf8')
  const lines = original.split('\n')
  const out = []
  let added = 0

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    // Match `  backdrop-filter: <value>;` lines (any indentation, with or
    // without trailing semicolon — though all existing usages have one).
    const m = line.match(/^(\s*)backdrop-filter:\s*(.+?);\s*$/)
    if (m) {
      const [, indent, value] = m
      // Look back for an existing -webkit-backdrop-filter line — could be
      // immediately above, or a few lines back if other declarations sit
      // between (rare).
      let alreadyPrefixed = false
      for (let j = i - 1; j >= Math.max(0, i - 3); j--) {
        if (/^\s*-webkit-backdrop-filter:/.test(lines[j])) {
          alreadyPrefixed = true
          break
        }
        // Stop scanning once we hit a non-prefix declaration or rule break.
        if (lines[j].includes('{') || lines[j].includes('}')) break
      }
      if (!alreadyPrefixed) {
        out.push(`${indent}-webkit-backdrop-filter: ${value};`)
        added++
      }
    }
    out.push(line)
  }

  if (added > 0) {
    writeFileSync(file, out.join('\n'))
    totalAdded += added
    console.log(`[+${added}] ${file}`)
  }
}

console.log(`\nTotal -webkit-backdrop-filter lines added: ${totalAdded}`)
