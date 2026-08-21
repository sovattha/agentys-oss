import { describe, test, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ContactAutocomplete } from './ContactAutocomplete'

vi.mock('../../services/api', () => ({
  apiClient: {
    searchContacts: vi.fn(() => Promise.resolve([])),
  },
}))

const mockContacts = [
  { name: 'John Doe', email: 'john@example.com' },
  { name: 'Jane Smith', email: 'jane@example.com' },
  { name: 'Bob Johnson', email: 'bob@example.com' },
  { name: 'Alice Williams', email: 'alice@example.com' },
  { name: 'Charlie Brown', email: 'charlie@example.com' },
  { name: 'Diana Prince', email: 'diana@example.com' },
]

// TODO: update for new architecture — autocomplete now uses portal-based suggestions list
describe.skip('ContactAutocomplete', () => {
  const defaultProps = {
    value: '',
    onChange: vi.fn(),
    contacts: mockContacts,
    disabled: false,
  }

  test('renders input field', () => {
    render(<ContactAutocomplete {...defaultProps} />)

    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  test('shows suggestions when typing matches name', async () => {
    const user = userEvent.setup()
    render(<ContactAutocomplete {...defaultProps} />)

    await user.type(screen.getByRole('combobox'), 'john')

    await waitFor(() => {
      expect(screen.getByText(/John Doe/)).toBeInTheDocument()
      expect(screen.getByText(/john@example\.com/)).toBeInTheDocument()
    })
  })

  test('shows suggestions when typing matches email', async () => {
    const user = userEvent.setup()
    render(<ContactAutocomplete {...defaultProps} />)

    await user.type(screen.getByRole('combobox'), 'jane@')

    await waitFor(() => {
      expect(screen.getByText(/Jane Smith/)).toBeInTheDocument()
    })
  })

  test('limits suggestions to 5 results', async () => {
    const user = userEvent.setup()
    render(<ContactAutocomplete {...defaultProps} />)

    await user.type(screen.getByRole('combobox'), 'e')

    await waitFor(() => {
      const suggestions = screen.getAllByRole('option')
      expect(suggestions.length).toBeLessThanOrEqual(5)
    })
  })

  test('selects contact on click', async () => {
    const user = userEvent.setup()
    const handleChange = vi.fn()
    render(<ContactAutocomplete {...defaultProps} onChange={handleChange} />)

    await user.type(screen.getByRole('combobox'), 'john')
    await waitFor(() => {
      expect(screen.getByText(/John Doe/)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('option', { name: /John Doe/ }))

    expect(handleChange).toHaveBeenCalledWith('john@example.com')
  })

  test('displays contact in format: Name <email>', async () => {
    const user = userEvent.setup()
    render(<ContactAutocomplete {...defaultProps} />)

    await user.type(screen.getByRole('combobox'), 'john')

    await waitFor(() => {
      expect(screen.getByText(/John Doe <john@example\.com>/)).toBeInTheDocument()
    })
  })

  test('hides suggestions when input is empty', async () => {
    const user = userEvent.setup()
    render(<ContactAutocomplete {...defaultProps} />)

    const input = screen.getByRole('combobox')
    await user.type(input, 'john')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    })

    await user.clear(input)

    await waitFor(() => {
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })
  })

  test('allows manual email entry', async () => {
    const user = userEvent.setup()
    const handleChange = vi.fn()
    render(<ContactAutocomplete {...defaultProps} onChange={handleChange} />)

    const input = screen.getByRole('combobox')
    await user.type(input, 'new@example.com')

    expect(handleChange).toHaveBeenLastCalledWith('new@example.com')
  })

  test('is disabled when disabled prop is true', () => {
    render(<ContactAutocomplete {...defaultProps} disabled={true} />)

    expect(screen.getByRole('combobox')).toBeDisabled()
  })

  test('performs fuzzy search on name and email', async () => {
    const user = userEvent.setup()
    render(<ContactAutocomplete {...defaultProps} />)

    await user.type(screen.getByRole('combobox'), 'smith')

    await waitFor(() => {
      expect(screen.getByText(/Jane Smith/)).toBeInTheDocument()
    })
  })
})


// ──────────────────────────────────────────────────────────────────────────────
// Regression: chip drag-and-drop bubble for cross-field moves
//
// The chip's onDrop used to call e.preventDefault() + e.stopPropagation()
// unconditionally and return early when the dragged email wasn't a member of
// the local chip list. That short-circuited cross-field drops whenever the
// cursor happened to land on a chip in the target field — handleFieldDrop
// (the parent .gmail-field handler) never saw the event, and the chip
// "vanished" or refused to move. Post-fix the chip's onDrop bails WITHOUT
// stopPropagation when localDragEmailRef is null, so the parent receives
// the bubbled event and processes the cross-field move.
// ──────────────────────────────────────────────────────────────────────────────
describe('ContactAutocomplete — cross-field drop bubbles to parent (Audit 2026-05-17)', () => {
  test('closes the portal suggestions immediately on outside pointer down', async () => {
    const user = userEvent.setup()

    render(
      <>
        <ContactAutocomplete
          value=""
          onChange={() => {}}
          contacts={mockContacts}
          fieldId="to"
        />
        <button type="button">AI action</button>
      </>,
    )

    await user.type(screen.getByRole('combobox'), 'alice')
    await screen.findByRole('option', { name: /Alice Williams/i })
    expect(screen.getByRole('listbox')).toBeInTheDocument()

    fireEvent.mouseDown(screen.getByRole('button', { name: 'AI action' }))

    await waitFor(() => {
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })
  })

  test('chip onDrop does NOT stop propagation when drag originated in another field', () => {
    const parentDropSpy = vi.fn()

    render(
      <div onDrop={parentDropSpy}>
        <ContactAutocomplete
          value="alice@example.com"
          onChange={() => {}}
          fieldId="cc"
          multi
        />
      </div>,
    )

    const chip = document.querySelector('.ca-chip')
    expect(chip).toBeTruthy()

    // Simulate a cross-field drop: no prior dragstart on this chip means
    // localDragEmailRef stays null. Fire a synthetic drop event on the chip;
    // the bubbled event must reach the parent's onDrop handler.
    const dropEvent = new Event('drop', { bubbles: true, cancelable: true })
    // jsdom doesn't implement DataTransfer, but the chip handler reads from
    // a module-level ref, not from dataTransfer, so this is fine.
    fireEvent(chip!, dropEvent)

    expect(parentDropSpy).toHaveBeenCalledTimes(1)
  })

  test('chip is marked draggable when fieldId is provided', () => {
    render(
      <ContactAutocomplete
        value="bob@example.com"
        onChange={() => {}}
        fieldId="to"
        multi
      />,
    )

    const chip = document.querySelector('.ca-chip') as HTMLElement
    expect(chip).toBeTruthy()
    expect(chip.getAttribute('draggable')).toBe('true')
    expect(chip.classList.contains('ca-chip-draggable')).toBe(true)
  })

  test('chip has a title hint when draggable', () => {
    render(
      <ContactAutocomplete
        value="carol@example.com"
        onChange={() => {}}
        fieldId="to"
        multi
      />,
    )

    const chip = document.querySelector('.ca-chip') as HTMLElement
    const title = chip.getAttribute('title') || ''
    // Title should at minimum surface the email; i18n fallback is the full
    // hint string. Either way, the email substring must be present.
    expect(title).toContain('carol@example.com')
  })
})
