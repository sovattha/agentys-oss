import { render, screen, waitFor, within, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { PendingDraft } from '../services/api';
import type { SavedDraft } from '../services/draftStorage';

// Mutable pin set + togglePin spy shared with the usePinned mock (hoisted so
// the vi.mock factory can close over them).
const h = vi.hoisted(() => ({ pinnedIds: new Set<string>(), togglePin: vi.fn() }));

vi.mock('../hooks/usePinned', () => ({
  usePinned: () => ({ pinnedIds: h.pinnedIds, togglePin: h.togglePin, addPin: vi.fn() }),
}));
vi.mock('../hooks/useBulkActionCount', () => ({
  useBulkActionCount: () => ({ count: null }),
}));
vi.mock('../services/websocket', () => ({
  getWebSocketClient: () => ({ subscribe: () => () => {} }),
}));

const listPendingDrafts = vi.fn();
vi.mock('../services/api', () => ({
  apiClient: {
    listPendingDrafts: (...args: unknown[]) => listPendingDrafts(...args),
    purgeAllDrafts: vi.fn(),
  },
}));

import { PendingDraftList } from './PendingDraftList';

function makeDraft(over: Partial<PendingDraft>): PendingDraft {
  return {
    id: 'd', email_id: 't', email_sender: 'alex@acme.com', email_subject: 'Sujet',
    email_body: '', draft_subject: 'Sujet', draft_body: 'corps', draft_v1: '',
    critique: '', classification: 'general', priority: 0, confidence: 0,
    created_at: new Date().toISOString(),
    ...over,
  } as PendingDraft;
}

const FOLLOWUP = makeDraft({
  id: 'd-fu', email_id: 'thread-9', routing_tier: 'followup',
  draft_subject: 'Relance Acme', email_subject: 'Relance Acme',
});
const NORMAL = makeDraft({
  id: 'd-1', email_id: 'other-thread', draft_subject: 'Brouillon normal',
  email_subject: 'Brouillon normal',
});
const SAVED: SavedDraft = {
  type: 'reply', id: 'saved-1', emailId: 'thread-x',
  emailSubject: 'Brouillon local', emailSender: 'bob@acme.com',
  body: 'corps local', savedAt: new Date().toISOString(),
};

describe('PendingDraftList — pinned follow-up section', () => {
  beforeEach(() => {
    localStorage.clear();
    h.pinnedIds = new Set<string>();
    h.togglePin = vi.fn();
    listPendingDrafts.mockReset();
    listPendingDrafts.mockResolvedValue({ drafts: [FOLLOWUP, NORMAL], pending_count: 2 });
  });

  it('renders a "Épinglé" section with the pinned follow-up draft on top', async () => {
    h.pinnedIds = new Set(['thread-9']); // the follow-up thread is pinned
    render(<PendingDraftList />);

    // Both drafts load.
    await waitFor(() => expect(screen.getAllByTestId('draft-item')).toHaveLength(2));

    // The "Épinglé" header is present (fr default in the test i18n setup).
    expect(screen.getByText('Épinglé')).toBeInTheDocument();

    // The pinned follow-up renders before the normal draft.
    const items = screen.getAllByTestId('draft-item');
    expect(within(items[0]).getByText('Relance Acme')).toBeInTheDocument();
    expect(within(items[1]).getByText('Brouillon normal')).toBeInTheDocument();
  });

  it('marks the pinned follow-up row with the "pinned" class (red bar parity with inbox)', async () => {
    h.pinnedIds = new Set(['thread-9']); // the follow-up thread is pinned
    render(<PendingDraftList />);

    await waitFor(() => expect(screen.getAllByTestId('draft-item')).toHaveLength(2));

    const items = screen.getAllByTestId('draft-item');
    // Pinned follow-up (rendered first) carries `pinned`; the normal draft does not.
    expect(items[0]).toHaveClass('pinned');
    expect(items[1]).not.toHaveClass('pinned');
  });

  it('right-clicking an AI draft opens a menu that pins its thread', async () => {
    h.pinnedIds = new Set<string>(); // nothing pinned yet
    render(<PendingDraftList />);

    await waitFor(() => expect(screen.getAllByTestId('draft-item')).toHaveLength(2));

    // Right-click the follow-up draft (email_id 'thread-9').
    const items = screen.getAllByTestId('draft-item');
    const followupRow = items.find((el) => within(el).queryByText('Relance Acme'));
    fireEvent.contextMenu(followupRow!);

    // Unpinned → menu offers "Épingler" (fr default); clicking pins thread-9.
    const pinBtn = await screen.findByRole('menuitem', { name: 'Épingler' });
    fireEvent.click(pinBtn);
    expect(h.togglePin).toHaveBeenCalledWith('thread-9');
  });

  it('offers "Désépingler" when right-clicking an already-pinned draft', async () => {
    h.pinnedIds = new Set(['thread-9']); // the follow-up thread is pinned
    render(<PendingDraftList />);

    await waitFor(() => expect(screen.getAllByTestId('draft-item')).toHaveLength(2));

    const items = screen.getAllByTestId('draft-item');
    const followupRow = items.find((el) => within(el).queryByText('Relance Acme'));
    fireEvent.contextMenu(followupRow!);

    expect(await screen.findByRole('menuitem', { name: 'Désépingler' })).toBeInTheDocument();
  });

  it('renders no "Épinglé" header when nothing is pinned', async () => {
    h.pinnedIds = new Set<string>(); // nothing pinned
    render(<PendingDraftList />);

    await waitFor(() => expect(screen.getAllByTestId('draft-item')).toHaveLength(2));
    expect(screen.queryByText('Épinglé')).not.toBeInTheDocument();
  });

  it('pins a saved (local) draft via right-click → floats it to "Épinglé"', async () => {
    listPendingDrafts.mockResolvedValue({ drafts: [], pending_count: 0 });
    render(<PendingDraftList savedDrafts={[SAVED]} />);

    // The single saved draft renders; nothing pinned yet.
    await waitFor(() => expect(screen.getAllByTestId('draft-item')).toHaveLength(1));
    expect(screen.queryByText('Épinglé')).not.toBeInTheDocument();

    // Right-click → Pin (local). The browser's native menu is suppressed.
    fireEvent.contextMenu(screen.getByTestId('draft-item'));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Épingler' }));

    // Now pinned locally: "Épinglé" header appears and the row carries `pinned`.
    expect(screen.getByText('Épinglé')).toBeInTheDocument();
    expect(screen.getByTestId('draft-item')).toHaveClass('pinned');
  });
});
