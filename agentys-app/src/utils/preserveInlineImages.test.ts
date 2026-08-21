import { describe, expect, it } from 'vitest'

import { preserveInlineImages } from './preserveInlineImages'

describe('preserveInlineImages', () => {
  it('appends editor-owned inline images when generation drops them', () => {
    const original = '<p>Avant</p><p><img src="data:image/png;base64,abc" alt="logo" width="120"></p>'
    const next = '<p>Texte généré</p>'

    const result = preserveInlineImages(original, next)

    expect(result).toContain(next)
    expect(result).toContain('src="data:image/png;base64,abc"')
    expect(result).toContain('alt="logo"')
    expect(result).toContain('width="120"')
  })

  it('does not preserve remote images from generated content', () => {
    const original = '<p><img src="https://example.com/banner.png" alt="banner"></p>'
    const next = '<p>Texte généré</p>'

    expect(preserveInlineImages(original, next)).toBe(next)
  })
})
