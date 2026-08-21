import { describe, it, expect } from 'vitest'
import { buildTokenChipHtml, chipsToTokens } from '../placeholderChips'

describe('buildTokenChipHtml', () => {
  it('wraps the label in a data-ar-token chip', () => {
    const html = buildTokenChipHtml('sender.firstname', 'Prénom expéditeur')
    expect(html).toContain('data-ar-token="sender.firstname"')
    expect(html).toContain('contenteditable="false"')
    expect(html).toContain('>Prénom expéditeur<')
  })

  it('escapes HTML in the label', () => {
    const html = buildTokenChipHtml('x', '<b>&"')
    expect(html).toContain('&lt;b&gt;&amp;&quot;')
    expect(html).not.toContain('<b>')
  })
})

describe('chipsToTokens', () => {
  it('converts a chip span back to its plain {token}', () => {
    const chip = buildTokenChipHtml('first_name', 'Prénom')
    expect(chipsToTokens(`Bonjour ${chip}`)).toBe('Bonjour {first_name}&nbsp;')
  })

  it('handles dotted tokens and multiple chips', () => {
    const a = buildTokenChipHtml('sender.firstname', 'Prénom expéditeur')
    const b = buildTokenChipHtml('subject', 'Sujet')
    expect(chipsToTokens(`${a}/ ${b}`)).toBe('{sender.firstname}&nbsp;/ {subject}&nbsp;')
  })

  it('is a no-op when there are no chips', () => {
    expect(chipsToTokens('plain {first_name} text')).toBe('plain {first_name} text')
    expect(chipsToTokens('')).toBe('')
  })
})
