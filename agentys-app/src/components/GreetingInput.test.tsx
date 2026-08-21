import { render, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import i18n from 'i18next'
import { GreetingInput } from './GreetingInput'

// setup.ts initialises i18n to `fr` and bundles every locale eagerly, so
// `i18n.changeLanguage('en')` yields real English strings. Restore `fr` after
// each test so we never leak a language switch into sibling suites.
afterEach(async () => {
  await i18n.changeLanguage('fr')
})

// The mode toggle (`.gi-mode-btn`) opens a 2-item menu; item[1] is the
// "civility + last name" mode. Picking it from an EMPTY field forces the
// component to synthesise a greeting from its localized default word.
function switchEmptyToTitleMode(container: HTMLElement) {
  fireEvent.click(container.querySelector('.gi-mode-btn') as HTMLButtonElement)
  const items = container.querySelectorAll('.gi-menu-item')
  fireEvent.click(items[1])
}

describe('GreetingInput — locale-aware default greeting word', () => {
  it('synthesises "Bonjour …" from an empty field in the fr locale', () => {
    const onCommit = vi.fn()
    const { container } = render(<GreetingInput value="" onCommit={onCommit} ariaLabel="greeting" />)
    switchEmptyToTitleMode(container)
    expect(onCommit).toHaveBeenCalledWith('Bonjour {civility} {last_name},')
  })

  it('synthesises "Hello …" in the en locale — no French "Bonjour" leak', async () => {
    await i18n.changeLanguage('en')
    const onCommit = vi.fn()
    const { container } = render(<GreetingInput value="" onCommit={onCommit} ariaLabel="greeting" />)
    switchEmptyToTitleMode(container)
    expect(onCommit).toHaveBeenCalledWith('Hello {civility} {last_name},')
  })

  it('keeps the user-typed greeting word when one exists (default is only a fallback)', () => {
    const onCommit = vi.fn()
    const { container } = render(
      <GreetingInput value="Coucou {first_name}," onCommit={onCommit} ariaLabel="greeting" />,
    )
    switchEmptyToTitleMode(container)
    // "Coucou" survives; the default word never clobbers an explicit greeting.
    expect(onCommit).toHaveBeenCalledWith('Coucou {civility} {last_name},')
  })
})
