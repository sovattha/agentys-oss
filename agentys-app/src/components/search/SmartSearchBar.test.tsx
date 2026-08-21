/**
 * SmartSearchBar unit tests
 *
 * Covers:
 *  1. Operator section renders in 2-column grid structure
 *  2. Group headers (Personnes, Contenu, Date) are shown
 *  3. Active filter highlighting: from-chip → De: item has is-active class
 *  4. Clicking operator opens inline panel (not textQuery change)
 *  5. Inline input is visible and accepts typing
 *  6. Enter in inline input with text creates filter chip + calls onSearch
 *  7. Escape in inline input closes panel without creating chip
 *  8. Cancel button (×) in inline panel closes without chip
 *  9. Après operator: date presets grid shown, no text input
 * 10. Date preset click creates after: chip
 * 11. Backspace on empty input removes last chip (regression)
 * 12. Type "from:" directly → existing prefix flow still works (regression)
 */

import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import i18n from 'i18next'
import { SmartSearchBar } from './SmartSearchBar'

// Mock the api client
vi.mock('../../services/api', () => ({
  apiClient: {
    searchContacts: vi.fn().mockResolvedValue([]),
    getSearchSuggestions: vi.fn().mockResolvedValue({ senders: [], subjects: [], labels: [] }),
  },
}))

// Mock useSavedSearches hook
vi.mock('../../hooks/useSavedSearches', () => ({
  useSavedSearches: () => ({
    searches: [],
    saveSearch: vi.fn(),
    deleteSearch: vi.fn(),
  }),
}))

function renderSearchBar(onSearch = vi.fn()) {
  return render(<SmartSearchBar onSearch={onSearch} />)
}

beforeEach(async () => {
  await i18n.changeLanguage('fr')
})

describe('SmartSearchBar — Operator grid layout', () => {
  it('renders .search-operators-grid when dropdown is open', async () => {
    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })
    const grid = document.querySelector('.search-operators-grid')
    expect(grid).toBeInTheDocument()
  })

  it('renders group headers: Personnes, Contenu, Date', async () => {
    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })
    expect(screen.getByText('Personnes')).toBeInTheDocument()
    // 'Contenu' appears as both a group title and an operator item label
    expect(screen.getAllByText('Contenu').length).toBeGreaterThan(0)
    expect(screen.getByText('Date')).toBeInTheDocument()
  })

  it('renders operator labels in English when the UI language is English', async () => {
    await act(async () => { await i18n.changeLanguage('en') })
    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')

    await act(async () => { input.focus() })

    expect(screen.getByText('People')).toBeInTheDocument()
    expect(screen.getAllByText('Content').length).toBeGreaterThan(0)
    expect(screen.getByText('Folder')).toBeInTheDocument()
    expect(screen.getByText('Sent to')).toBeInTheDocument()
    expect(screen.getByText('Attachments')).toBeInTheDocument()
    expect(screen.queryByText('Personnes')).not.toBeInTheDocument()
    expect(screen.queryByText('Envoyé à')).not.toBeInTheDocument()
    expect(screen.queryByText('Pièces jointes')).not.toBeInTheDocument()
  })

  it('renders operator items within group grid', async () => {
    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })
    const peopleGroup = document.querySelector('[data-testid="operator-group-people"]')
    expect(peopleGroup).toBeInTheDocument()
    expect(peopleGroup?.querySelector('.search-operators-grid')).toBeInTheDocument()
  })

  it('operator items in grid have .operator-item class', async () => {
    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })
    const operatorItems = document.querySelectorAll('.operator-item')
    expect(operatorItems.length).toBeGreaterThan(0)
  })
})

describe('SmartSearchBar — Active filter highlighting', () => {
  it('adds is-active to De: when from filter is applied', async () => {
    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')

    // Type from: value and press Enter to create chip
    await act(async () => {
      input.focus()
      fireEvent.change(input, { target: { value: 'from:alice@example.com' } })
      fireEvent.keyDown(input, { key: 'Enter' })
    })

    // Re-open dropdown to check active state
    await act(async () => { fireEvent.focus(input) })

    const deItem = document.querySelector('[data-operator-type="from:"]')
    expect(deItem?.classList.contains('is-active')).toBe(true)
  })
})

describe('SmartSearchBar — Inline filter panel', () => {
  it('clicking De: opens inline panel (not inserting from: in main input)', async () => {
    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })

    // Click the "De :" operator item
    const deItem = screen.getByText('De')
    await act(async () => { fireEvent.click(deItem) })

    // Inline panel should be visible
    expect(document.querySelector('.inline-filter-panel')).toBeInTheDocument()
    // Main input should NOT have "from:" value
    expect(input).toHaveValue('')
  })

  it('inline input is focused and accepts typing', async () => {
    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })

    const deItem = screen.getByText('De')
    await act(async () => { fireEvent.click(deItem) })

    const inlineInput = screen.getByTestId('inline-filter-input')
    expect(inlineInput).toBeInTheDocument()

    await act(async () => {
      fireEvent.change(inlineInput, { target: { value: 'john' } })
    })
    expect(inlineInput).toHaveValue('john')
  })

  it('pressing Enter in inline input creates chip and calls onSearch', async () => {
    const onSearch = vi.fn()
    render(<SmartSearchBar onSearch={onSearch} />)
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })

    const deItem = screen.getByText('De')
    await act(async () => { fireEvent.click(deItem) })

    const inlineInput = screen.getByTestId('inline-filter-input')
    await act(async () => {
      fireEvent.change(inlineInput, { target: { value: 'alice@example.com' } })
      fireEvent.keyDown(inlineInput, { key: 'Enter' })
    })

    // Panel should close
    await waitFor(() => {
      expect(document.querySelector('.inline-filter-panel')).not.toBeInTheDocument()
    })
    // onSearch called with from:
    expect(onSearch).toHaveBeenCalledWith(expect.stringContaining('from:alice@example.com'))
    // Chip appears
    expect(document.querySelector('.search-chip')).toBeInTheDocument()
  })

  it('pressing Escape in inline input closes panel without chip', async () => {
    const onSearch = vi.fn()
    render(<SmartSearchBar onSearch={onSearch} />)
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })

    const deItem = screen.getByText('De')
    await act(async () => { fireEvent.click(deItem) })

    const inlineInput = screen.getByTestId('inline-filter-input')
    await act(async () => {
      fireEvent.change(inlineInput, { target: { value: 'john' } })
      fireEvent.keyDown(inlineInput, { key: 'Escape' })
    })

    // Panel closed
    await waitFor(() => {
      expect(document.querySelector('.inline-filter-panel')).not.toBeInTheDocument()
    })
    // No chip created
    expect(document.querySelector('.search-chip')).not.toBeInTheDocument()
    // onSearch NOT called with from:
    expect(onSearch).not.toHaveBeenCalledWith(expect.stringContaining('from:'))
  })

  it('cancel button (×) closes inline panel without chip', async () => {
    const onSearch = vi.fn()
    render(<SmartSearchBar onSearch={onSearch} />)
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })

    const deItem = screen.getByText('De')
    await act(async () => { fireEvent.click(deItem) })

    const cancelBtn = screen.getByRole('button', { name: /annuler le filtre/i })
    await act(async () => { fireEvent.click(cancelBtn) })

    await waitFor(() => {
      expect(document.querySelector('.inline-filter-panel')).not.toBeInTheDocument()
    })
    expect(document.querySelector('.search-chip')).not.toBeInTheDocument()
  })
})

describe('SmartSearchBar — Date inline mode (Après/Avant)', () => {
  it('clicking Après shows date picker without standard text input', async () => {
    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })

    const apresItem = screen.getByText('Après')
    await act(async () => { fireEvent.click(apresItem) })

    // Date picker wrap should be visible
    expect(document.querySelector('.inline-date-picker-wrap')).toBeInTheDocument()
    // The date input (yyyy/mm/dd) should be present
    expect(screen.getByTestId('inline-date-picker')).toBeInTheDocument()
    // No standard filter text input (date mode replaces it with date picker)
    expect(document.querySelector('.inline-filter-input')).not.toBeInTheDocument()
  })

  it('typing a date in the date picker creates after: chip', async () => {
    const onSearch = vi.fn()
    render(<SmartSearchBar onSearch={onSearch} />)
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })

    const apresItem = screen.getByText('Après')
    await act(async () => { fireEvent.click(apresItem) })

    // Type a valid date in the date picker and press Enter
    const datePicker = screen.getByTestId('inline-date-picker')
    await act(async () => {
      fireEvent.change(datePicker, { target: { value: '2026/01/15' } })
      fireEvent.keyDown(datePicker, { key: 'Enter' })
    })

    // Panel should close
    await waitFor(() => {
      expect(document.querySelector('.inline-filter-panel')).not.toBeInTheDocument()
    })
    // onSearch called with after:
    expect(onSearch).toHaveBeenCalledWith(expect.stringMatching(/after:\d{4}-\d{2}-\d{2}/))
  })
})

describe('SmartSearchBar — Regressions', () => {
  it('Backspace on empty input removes last chip', async () => {
    const onSearch = vi.fn()
    render(<SmartSearchBar onSearch={onSearch} />)
    const input = screen.getByTestId('smart-search-input')

    // Create a chip via type-based flow
    await act(async () => {
      input.focus()
      fireEvent.change(input, { target: { value: 'from:alice@example.com' } })
      fireEvent.keyDown(input, { key: 'Enter' })
    })

    // Verify chip was created
    expect(document.querySelector('.search-chip')).toBeInTheDocument()

    // Press Backspace on empty input
    await act(async () => {
      fireEvent.change(input, { target: { value: '' } })
      fireEvent.keyDown(input, { key: 'Backspace' })
    })

    // Chip should be removed
    await waitFor(() => {
      expect(document.querySelector('.search-chip')).not.toBeInTheDocument()
    })
  })

  it('typing from: directly in main input still works (type-based flow) — inline panel NOT triggered', async () => {
    const { apiClient } = await import('../../services/api')
    vi.mocked(apiClient.searchContacts).mockResolvedValueOnce([
      { name: 'John Doe', email: 'john@example.com' },
    ])

    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })

    // Type prefix directly
    await act(async () => {
      fireEvent.change(input, { target: { value: 'from:jo' } })
    })

    // Main input has the typed value (type-based flow active)
    expect(input).toHaveValue('from:jo')
    // Inline panel must NOT be triggered by typing (only click triggers it)
    expect(document.querySelector('.inline-filter-panel')).not.toBeInTheDocument()
    // isDropdownOpen is true (set by handleInputChange) — dropdown would show if contacts arrive
    // We verify this by waiting for contacts to load
    await waitFor(async () => {
      // After contacts resolve, dropdown renders with contact suggestions
      // Either dropdown is visible with contacts, or it's null (empty results both are valid)
      // Key assertion: NO inline panel
      expect(document.querySelector('.inline-filter-panel')).not.toBeInTheDocument()
    })
  })

  it('typing after: directly in main input shows date presets (type-based flow)', async () => {
    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')
    await act(async () => { input.focus() })

    await act(async () => {
      fireEvent.change(input, { target: { value: 'after:' } })
    })

    // Inline panel NOT open
    expect(document.querySelector('.inline-filter-panel')).not.toBeInTheDocument()
    // Regular dropdown open with date suggestions
    expect(document.querySelector('.search-suggestions-dropdown')).toBeInTheDocument()
    // "Cette semaine" should appear in dropdown
    expect(screen.getByText('Cette semaine')).toBeInTheDocument()
  })
})

describe('SmartSearchBar — BUG-I002 regression: no autofocus on mount', () => {
  // Session I (2026-04-26) bug: clicking a label tab caused the search
  // dropdown to open. Root cause: EmailList early-returns a loading
  // skeleton during a label switch, which unmounts the SmartSearchBar.
  // When emails arrive, the bar remounts and used to call inputRef.focus()
  // in a useEffect — stealing focus from the page and showing the
  // "RECHERCHES RÉCENTES" dropdown unexpectedly. The user's next keystroke
  // (e.g. `E` to archive) then landed in the search input as text.
  //
  // Fix: the autofocus useEffect was removed. Parent toggles
  // (toggleSearchFromShortcut, toggleSearchBar) explicitly focus the
  // input when the user opens the bar via `/` or the header icon.
  it('does NOT auto-focus the input on mount', async () => {
    // Put a sibling element that holds focus so we can prove SmartSearchBar
    // doesn't steal it.
    const { container } = render(
      <div>
        <button data-testid="outsider">outsider</button>
        <SmartSearchBar onSearch={vi.fn()} />
      </div>
    )
    const outsider = screen.getByTestId('outsider')
    outsider.focus()

    // Wait two frames to let any deferred autofocus fire.
    await act(async () => {
      await new Promise<void>(r => requestAnimationFrame(() => requestAnimationFrame(() => r())))
    })

    // Outsider must STILL be the active element.
    expect(document.activeElement).toBe(outsider)

    // The dropdown must NOT have opened on mount.
    expect(container.querySelector('.search-suggestions-dropdown')).not.toBeInTheDocument()
  })

  it('still focuses normally when the user explicitly clicks the input', async () => {
    renderSearchBar()
    const input = screen.getByTestId('smart-search-input')

    // User-initiated focus path — the dropdown should still open.
    await act(async () => { input.focus() })
    expect(document.activeElement).toBe(input)
    expect(document.querySelector('.search-operators-grid')).toBeInTheDocument()
  })
})
