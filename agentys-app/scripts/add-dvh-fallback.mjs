/**
 * Adds `dvh` (dynamic viewport height) fallback for every height-related
 * `100vh` declaration so mobile Safari/Chrome don't cut content off behind
 * the URL bar.
 *
 * Pattern: declarations using `100vh` are duplicated below with `100vh`
 * replaced by `100dvh`. Older browsers ignore the unknown `dvh` unit and
 * keep the original `vh` value; newer browsers (Safari 15.4+, Chrome 108+,
 * Firefox 101+) override with `dvh`.
 *
 * Skipped intentionally: keyframe `transform: translateY(100vh)` — those are
 * animation distances, not viewport-fitting. Adding `dvh` there changes the
 * animation arc unpredictably.
 *
 * Idempotent: skips lines already followed by a `dvh` duplicate.
 */

import { readFileSync, writeFileSync } from 'fs'
import { execSync } from 'child_process'

const list = execSync(
  'grep -rln "100vh" src/ --include="*.css"',
  { encoding: 'utf8' },
).split('\n').filter(Boolean)

let totalAdded = 0
const HEIGHT_PROPS = /\b(height|min-height|max-height|top|bottom|inset|inset-block|inset-inline|block-size|min-block-size|max-block-size)\b/

for (const file of list) {
  const original = readFileSync(file, 'utf8')
  const lines = original.split('\n')
  const out = []
  let added = 0

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    out.push(line)

    // Only touch lines that look like a single declaration with 100vh in a
    // height-related property (skip transforms, keyframes' translate, etc.).
    if (!line.includes('100vh')) continue
    if (line.includes('translate')) continue // animations
    if (/-webkit-/.test(line)) continue // already a prefix
    if (!HEIGHT_PROPS.test(line)) continue

    // Skip if next line is already the dvh duplicate.
    const next = lines[i + 1] || ''
    const nextDvh = next.replace(/100dvh/g, '100vh')
    if (nextDvh.trim() === line.trim()) continue

    // Build the dvh-equivalent line, preserving exact indentation.
    const dvhLine = line.replace(/100vh/g, '100dvh')
    if (dvhLine === line) continue
    out.push(dvhLine)
    added++
  }

  if (added > 0) {
    writeFileSync(file, out.join('\n'))
    totalAdded += added
    console.log(`[+${added}] ${file}`)
  }
}

console.log(`\nTotal 100dvh fallback lines added: ${totalAdded}`)
