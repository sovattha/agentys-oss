import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ContactGroupsManager } from './ContactGroupsManager';

// i18n: return the key verbatim so we can assert on stable identifiers.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// The component reads groups from a hook and project labels from the API.
// Stub both so it renders the create-form + project-label dropdown offline.
vi.mock('../../hooks/useContactGroups', () => ({
  useContactGroups: () => ({
    groups: [],
    loading: false,
    createGroup: vi.fn(),
    updateGroup: vi.fn(),
    deleteGroup: vi.fn(),
  }),
}));

vi.mock('../../api/labels', () => ({
  fetchLabels: () => Promise.resolve({ labels: [] }),
}));

/**
 * Regression (escape-bubble audit 2026-05-30 — the worst case = data loss):
 * with the group form open, pressing Escape to dismiss the project-label
 * dropdown used to fall through to the component's own document Escape handler,
 * which called resetForm() and wiped the in-progress name/members/label. The
 * dropdown's Escape must dismiss ONLY the dropdown — same contract as the
 * LocalePickers fix. These tests pin that the form survives, while preserving
 * the normal "Escape with nothing open resets the form" behaviour.
 */
describe('ContactGroupsManager — Escape on the label dropdown does not reset the form', () => {
  let onClose: Mock<() => void>;

  beforeEach(() => {
    onClose = vi.fn<() => void>();
  });

  // The project-label trigger is the button carrying aria-haspopup="listbox".
  // It exists only while the create/edit form is open.
  const getLabelTrigger = () =>
    screen.queryAllByRole('button').find(b => b.getAttribute('aria-haspopup') === 'listbox') || null;

  async function openForm() {
    render(<ContactGroupsManager onClose={onClose} />);
    // GhostAddRow opens the create form (aria-label = the i18n key).
    fireEvent.click(screen.getByRole('button', { name: 'groups_new_group' }));
    await waitFor(() => expect(getLabelTrigger()).not.toBeNull());
  }

  it('closes only the dropdown, keeps the form open, never calls onClose', async () => {
    await openForm();

    const trigger = getLabelTrigger()!;
    fireEvent.click(trigger);
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('listbox')).toBeTruthy();

    // Escape reaches the component's document keydown handler (it has no
    // INPUT-skip and no stopPropagation upstream) — the exact bug path.
    fireEvent.keyDown(document, { key: 'Escape' });

    // Dropdown collapsed…
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('listbox')).toBeNull();
    // …the form is STILL open (the label trigger only renders inside the form)…
    expect(getLabelTrigger()).not.toBeNull();
    // …and the whole manager was NOT closed.
    expect(onClose).not.toHaveBeenCalled();
  });

  it('Escape with no dropdown open still resets the form (host behaviour preserved)', async () => {
    await openForm();

    // No dropdown open → Escape should fall through to resetForm().
    fireEvent.keyDown(document, { key: 'Escape' });

    // Form closed: the label trigger is gone and the list-view add row is back.
    await waitFor(() => expect(getLabelTrigger()).toBeNull());
    expect(screen.getByRole('button', { name: 'groups_new_group' })).toBeTruthy();
    // resetForm() does not call onClose (only the list-level Escape would).
    expect(onClose).not.toHaveBeenCalled();
  });
});
