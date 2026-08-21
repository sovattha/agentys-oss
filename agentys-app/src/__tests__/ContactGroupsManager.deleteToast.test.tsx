import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import i18n from 'i18next'
import { ContactGroupsManager } from '../components/settings/ContactGroupsManager'

// deleteGroup rejects so handleDelete's catch runs — the bug: setError only
// renders inside the FORM branch (cg-form-error), but the delete button lives
// in the LIST branch, so the failure was previously invisible. The fix
// dispatches a global agentys:toast error.
const mockDeleteGroup = vi.fn()
const mockGroup = {
  id: 'g-1',
  name: 'My Team',
  emoji: '',
  label_name: null,
  members: [{ name: 'Alice', email: 'alice@example.com' }],
  virtual_meeting: false,
}

vi.mock('../hooks/useContactGroups', () => ({
  useContactGroups: () => ({
    groups: [mockGroup],
    loading: false,
    createGroup: vi.fn(),
    updateGroup: vi.fn(),
    deleteGroup: mockDeleteGroup,
  }),
}))

// fetchLabels runs on mount when projectLabelName is undefined — keep it inert.
vi.mock('../api/labels', () => ({
  fetchLabels: vi.fn().mockResolvedValue({ labels: [] }),
}))

describe('ContactGroupsManager delete failure feedback', () => {
  beforeEach(async () => {
    mockDeleteGroup.mockReset()
    await i18n.changeLanguage('en')
  })

  it('dispatches an agentys:toast error when deleteGroup rejects', async () => {
    mockDeleteGroup.mockRejectedValue(new Error('boom'))
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')

    render(<ContactGroupsManager onClose={vi.fn()} />)

    // First click reveals the inline confirm button (LIST branch).
    fireEvent.click(screen.getByLabelText('Delete'))
    // Confirm triggers handleDelete -> deleteGroup rejects -> catch.
    fireEvent.click(screen.getByText('Confirm deletion'))

    await waitFor(() => {
      const toastCall = dispatchSpy.mock.calls.find(
        ([evt]) => evt instanceof CustomEvent && evt.type === 'agentys:toast',
      )
      expect(toastCall).toBeTruthy()
      const detail = (toastCall![0] as CustomEvent).detail
      expect(detail.type).toBe('error')
    })

    dispatchSpy.mockRestore()
  })
})
