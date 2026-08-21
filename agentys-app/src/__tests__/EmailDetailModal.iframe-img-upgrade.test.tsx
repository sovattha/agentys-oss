import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'

// HTML emails render through HtmlEmailIframe (srcDoc), which inherits the
// parent page CSP (img-src https: only). http:// images must be upgraded in
// processedHtml or they show as broken placeholders — the Shuffle OTP bug.

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => `T:${k}` }),
}))

// jsdom fires the iframe onLoad but has no ResizeObserver — stub it so the
// resize wiring in handleLoad doesn't throw as an unhandled error.
vi.stubGlobal('ResizeObserver', class {
  observe() {}
  unobserve() {}
  disconnect() {}
})

import { HtmlEmailIframe } from '../components/EmailDetailModal'

function renderSrcDoc(body: string): string {
  const { container } = render(<HtmlEmailIframe body={body} />)
  const iframe = container.querySelector('iframe')
  expect(iframe).not.toBeNull()
  return iframe!.getAttribute('srcdoc') || ''
}

describe('HtmlEmailIframe http→https image upgrade', () => {
  it('upgrades http:// img sources in the iframe srcdoc', () => {
    const srcdoc = renderSrcDoc(
      '<div><img src="http://cdn.mcauto-images-production.sendgrid.net/abc/550x254.png" width="550" height="254" alt="banner"></div>'
    )
    expect(srcdoc).toContain('src="https://cdn.mcauto-images-production.sendgrid.net/abc/550x254.png"')
    expect(srcdoc).not.toContain('src="http://')
  })

  it('leaves https images and http anchors untouched', () => {
    const srcdoc = renderSrcDoc(
      '<div><img src="https://example.com/logo.png" alt="logo"><a href="http://example.com/unsub">Unsub</a></div>'
    )
    expect(srcdoc).toContain('src="https://example.com/logo.png"')
    expect(srcdoc).toContain('href="http://example.com/unsub"')
  })

  it('still strips tracking pixels instead of upgrading them', () => {
    const srcdoc = renderSrcDoc(
      '<div><p>Hello</p><img src="http://url6421.shuffle.click/wf/open?upn=abc" width="1" height="1"></div>'
    )
    expect(srcdoc).not.toContain('shuffle.click/wf/open')
  })
})
