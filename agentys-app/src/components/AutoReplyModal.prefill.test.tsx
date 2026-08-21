import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Controllable return value for the auto-reply hook. Each test sets
// `hookState.current` before rendering.
const hookState = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));

vi.mock('../hooks/useAutoReplySetting', () => ({
  useAutoReplySetting: () => hookState.current,
}));

// Stub the heavy children — the pre-fill we're testing flows through the hook's
// `setAutoReply`, not through any of these, so trivial renders keep the test
// deterministic (no network, no contenteditable, no date popovers).
vi.mock('./ui/RichTextEditor', () => ({
  RichTextEditor: React.forwardRef(() => React.createElement('div', { 'data-testid': 'rte' })),
}));
vi.mock('./ui/FrenchDatePicker', () => ({ FrenchDatePicker: () => null }));
vi.mock('./compose/ContactAutocomplete', () => ({ ContactAutocomplete: () => null }));
vi.mock('./ui/SignatureFooter', () => ({ SignatureFooter: () => null }));

import { AutoReplyModal } from './AutoReplyModal';

function baseHook(over: Record<string, unknown>) {
  return {
    autoReplyEnabled: false,
    autoReplyMessage: '',
    autoReplyStart: '',
    autoReplyEnd: '',
    autoTransferEnabled: false,
    autoTransferEmail: '',
    calendarSynced: false,
    calendarSyncError: null,
    loaded: false,
    toggleAutoReply: vi.fn(),
    toggleTransfer: vi.fn(),
    setAutoReply: vi.fn(),
    flushPending: vi.fn(),
    ...over,
  };
}

describe('AutoReplyModal — suggested-message pre-fill', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('pre-fills a localized starter when the editor is empty after load', async () => {
    const setAutoReply = vi.fn();
    hookState.current = baseHook({ loaded: true, autoReplyMessage: '', setAutoReply });

    render(<AutoReplyModal onClose={() => {}} />);

    await waitFor(() => expect(setAutoReply).toHaveBeenCalledTimes(1));
    const message = setAutoReply.mock.calls[0][0].message as string;
    // French body (i18n is initialised to `fr` in test setup) …
    expect(message).toContain('Merci pour votre message');
    // … with the absence-period chip embedded (not the raw {{period}} marker,
    // and not HTML-escaped) so it stays in sync with the dates.
    expect(message).toContain('data-ar-token="absence_period"');
    expect(message).not.toContain('{{period}}');
    expect(message).not.toContain('&lt;span');
  });

  it('does NOT overwrite a message the user already has', async () => {
    const setAutoReply = vi.fn();
    hookState.current = baseHook({
      loaded: true,
      autoReplyMessage: '<div>Texte déjà écrit</div>',
      setAutoReply,
    });

    render(<AutoReplyModal onClose={() => {}} />);

    // Give effects a tick to run, then assert nothing was written.
    await waitFor(() => expect(hookState.current.loaded).toBe(true));
    expect(setAutoReply).not.toHaveBeenCalled();
  });

  it('does NOT pre-fill before settings have loaded', async () => {
    const setAutoReply = vi.fn();
    hookState.current = baseHook({ loaded: false, autoReplyMessage: '', setAutoReply });

    render(<AutoReplyModal onClose={() => {}} />);

    await waitFor(() => expect(hookState.current.loaded).toBe(false));
    expect(setAutoReply).not.toHaveBeenCalled();
  });

  // Bug Karine 2026-06-09 : the starter is auto-persisted on first open, so it
  // froze in that day's language — and, for saves made before 4be7990e, with a
  // legacy `&nbsp;` after the chip ("un espace après les variables dynamiques").
  // A saved message that is still a PRISTINE suggestion must be rebuilt in the
  // current app language; anything the user edited must never be touched.
  const EN_PRISTINE_LEGACY_SAVE =
    'Hello,<br><br>Thank you for your message. I am currently away ' +
    '<span class="ar-token" data-ar-token="absence_period" contenteditable="false">your absence dates</span>&nbsp; ' +
    'and will reply when I return.<br><br>Best regards,';

  it('relocalizes a pristine suggestion saved in another language (and drops the legacy nbsp)', async () => {
    const setAutoReply = vi.fn();
    hookState.current = baseHook({
      loaded: true,
      autoReplyMessage: EN_PRISTINE_LEGACY_SAVE,
      setAutoReply,
    });

    render(<AutoReplyModal onClose={() => {}} />);

    // App language is `fr` (test setup) → the EN pristine save is rebuilt in French.
    await waitFor(() => expect(setAutoReply).toHaveBeenCalledTimes(1));
    const message = setAutoReply.mock.calls[0][0].message as string;
    expect(message).toContain('Merci pour votre message');
    expect(message).toContain('data-ar-token="absence_period"');
    expect(message).not.toContain('&nbsp;');
  });

  it('leaves an EDITED suggestion alone even when only one word changed', async () => {
    const setAutoReply = vi.fn();
    hookState.current = baseHook({
      loaded: true,
      autoReplyMessage: EN_PRISTINE_LEGACY_SAVE.replace('Thank you', 'Thanks a lot'),
      setAutoReply,
    });

    render(<AutoReplyModal onClose={() => {}} />);

    await waitFor(() => expect(hookState.current.loaded).toBe(true));
    expect(setAutoReply).not.toHaveBeenCalled();
  });
});
