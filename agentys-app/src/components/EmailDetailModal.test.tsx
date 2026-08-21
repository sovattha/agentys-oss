import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  EmailDetailModal,
  ThreadMessageCard,
  getIncomingReplyScope,
  reconcileConversationMessages,
  shouldReplaceEmailDetail,
  type EmailDetail,
} from './EmailDetailModal';

// Mock the config
vi.mock('../config', () => ({
  API_URL: 'http://localhost:5050',
}));

// Mock fetch globally
const mockFetch = vi.fn();

(globalThis as any).fetch = mockFetch;

const mockEmailData = {
  data: {
    id: 'email-123',
    message_id: 'msg-123',
    thread_id: 'thread-123',
    sender: 'John Doe <john@example.com>',
    sender_name: 'John Doe',
    sender_email: 'john@example.com',
    recipient: 'me@example.com',
    subject: 'Meeting Tomorrow',
    body: 'Hi,\n\nLet us meet tomorrow at 2pm to discuss the project.\n\nBest,\nJohn',
    received_at: '2026-01-19T10:30:00Z',
  },
};

describe('shouldReplaceEmailDetail (monotonic body guard)', () => {
  // Only `id` and `body` matter to the guard; cast minimal objects.
  const mk = (id: string, body: string) => ({ id, body }) as Parameters<typeof shouldReplaceEmailDetail>[1];

  it('applies the first load (prev is null)', () => {
    expect(shouldReplaceEmailDetail(null, mk('e1', ''))).toBe(true);
    expect(shouldReplaceEmailDetail(null, mk('e1', '<p>hi</p>'))).toBe(true);
  });

  it('always applies when the email id changes (switching emails)', () => {
    expect(shouldReplaceEmailDetail(mk('e1', '<p>old</p>'), mk('e2', ''))).toBe(true);
  });

  it('REGRESSION (2026-05-20): a later empty response must NOT blank a populated body', () => {
    const withBody = mk('e1', '<p>les patetes sont bonnes</p>');
    const empty = mk('e1', '');
    expect(shouldReplaceEmailDetail(withBody, empty)).toBe(false);
  });

  it('upgrades an empty body to a populated one (normal lazy-load path)', () => {
    expect(shouldReplaceEmailDetail(mk('e1', ''), mk('e1', '<p>body</p>'))).toBe(true);
  });

  it('applies a refreshed body, and treats whitespace-only incoming as empty', () => {
    expect(shouldReplaceEmailDetail(mk('e1', '<p>v1</p>'), mk('e1', '<p>v2</p>'))).toBe(true);
    expect(shouldReplaceEmailDetail(mk('e1', '<p>real</p>'), mk('e1', '   '))).toBe(false);
  });
});

describe('getIncomingReplyScope', () => {
  it('marque une réponse entrante comme adressée à moi seul quand le compte est le seul destinataire visible', () => {
    expect(getIncomingReplyScope({
      sender: 'Marco <marco@example.com>',
      senderEmail: 'marco@example.com',
      to: ['Nathan Roy <me@example.com>'],
      cc: [],
    }, 'me@example.com')).toEqual({
      kind: 'me',
      recipients: ['Nathan Roy <me@example.com>'],
    });
  });

  it('marque une réponse entrante comme adressée à tous quand un autre destinataire est en copie', () => {
    expect(getIncomingReplyScope({
      sender: 'Marco <marco@example.com>',
      senderEmail: 'marco@example.com',
      to: ['ME@example.com'],
      cc: ['club@example.com'],
    }, 'me@example.com')).toEqual({
      kind: 'all',
      recipients: ['ME@example.com', 'club@example.com'],
    });
  });

  it('normalise les adresses avec nom affiché et ignore les messages envoyés par moi', () => {
    expect(getIncomingReplyScope({
      sender: 'Me <me@example.com>',
      senderEmail: 'Me <me@example.com>',
      to: ['Marco <marco@example.com>'],
      cc: [],
    }, 'me@example.com')).toBeNull();
  });

  it('retourne null quand les destinataires visibles sont absents', () => {
    expect(getIncomingReplyScope({
      sender: 'Marco <marco@example.com>',
      senderEmail: 'marco@example.com',
      to: [],
      cc: [],
    }, 'me@example.com')).toBeNull();
  });
});

describe('reconcileConversationMessages', () => {
  const sentMessage = (overrides: Partial<EmailDetail>): EmailDetail => ({
    id: 'sent:19e496dff618f314',
    messageId: '19e496dff618f314',
    threadId: '19e47a4cbf2b92bf',
    sender: 'nathanroy@gmail.com',
    senderName: 'Nathan Roy',
    senderEmail: 'nathanroy@gmail.com',
    recipient: 'cours.universite@gmail.com',
    to: ['cours.universite@gmail.com'],
    cc: [],
    subject: 'Re: Tests application quotidiens',
    body: 'Salut Crypto,\n\nÇa marche, moi aussi je ferai de même.',
    receivedAt: '2026-05-21T07:26:46Z',
    isSent: true,
    attachments: [],
    ...overrides,
  });

  it('retire le placeholder reply-* quand Gmail renvoie le vrai message envoyé', () => {
    const original = sentMessage({
      id: '19e47a4cbf2b92bf',
      messageId: '19e47a4cbf2b92bf',
      sender: 'Cryptoformation Université <cours.universite@gmail.com>',
      senderName: 'Cryptoformation Université',
      senderEmail: 'cours.universite@gmail.com',
      recipient: 'nathanroy@gmail.com',
      to: ['nathanroy@gmail.com'],
      subject: 'Tests application quotidiens',
      body: 'Salut Nathan',
      receivedAt: '2026-05-20T23:07:21Z',
      isSent: false,
    });
    const optimisticReply = sentMessage({
      id: 'sent:reply-1779348406',
      messageId: 'reply-1779348406',
      receivedAt: '2026-05-21T07:26:46Z',
    });
    const realReply = sentMessage({
      id: 'sent:19e496dff618f314',
      messageId: '19e496dff618f314',
      receivedAt: '2026-05-21T07:26:47Z',
    });

    const reconciled = reconcileConversationMessages([original, optimisticReply, realReply]);

    expect(reconciled.map(message => message.id)).toEqual([
      '19e47a4cbf2b92bf',
      'sent:19e496dff618f314',
    ]);
  });

  it('conserve le placeholder tant que le vrai message envoyé n’est pas encore disponible', () => {
    const optimisticReply = sentMessage({
      id: 'sent:reply-1779348406',
      messageId: 'reply-1779348406',
    });

    expect(reconcileConversationMessages([optimisticReply])).toEqual([optimisticReply]);
  });
});

// TODO: update for new architecture — component now fetches email detail and has new dependencies
describe.skip('EmailDetailModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockEmailData),
    });
  });

  it('renders nothing when closed', () => {
    const { container } = render(
      <EmailDetailModal
        emailId="email-123"
        isOpen={false}
        onClose={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders modal when open', async () => {
    render(
      <EmailDetailModal
        emailId="email-123"
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('displays email content when loaded', async () => {
    render(
      <EmailDetailModal
        emailId="email-123"
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Meeting Tomorrow')).toBeInTheDocument();
    });

    expect(screen.getByText(/John Doe/)).toBeInTheDocument();
    expect(screen.getByText(/Let us meet tomorrow/)).toBeInTheDocument();
  });

  it('shows loading state while fetching', async () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));

    render(
      <EmailDetailModal
        emailId="email-123"
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('Chargement...')).toBeInTheDocument();
  });

  it('shows error state when fetch fails', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ error: 'Email not found' }),
    });

    render(
      <EmailDetailModal
        emailId="email-123"
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(/Erreur/)).toBeInTheDocument();
    });
  });

  it('calls onClose when close button is clicked', async () => {
    const onClose = vi.fn();

    render(
      <EmailDetailModal
        emailId="email-123"
        isOpen={true}
        onClose={onClose}
      />
    );

    const closeButton = screen.getByLabelText('Fermer');
    fireEvent.click(closeButton);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when backdrop is clicked', async () => {
    const onClose = vi.fn();

    render(
      <EmailDetailModal
        emailId="email-123"
        isOpen={true}
        onClose={onClose}
      />
    );

    const backdrop = document.querySelector('.email-detail-backdrop');
    if (backdrop) {
      fireEvent.click(backdrop);
    }

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when Escape key is pressed', async () => {
    const onClose = vi.fn();

    render(
      <EmailDetailModal
        emailId="email-123"
        isOpen={true}
        onClose={onClose}
      />
    );

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('fetches email with correct emailId', async () => {
    render(
      <EmailDetailModal
        emailId="email-456"
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalled();
    });

    const fetchUrl = mockFetch.mock.calls[0][0];
    expect(fetchUrl).toContain('/api/emails/email-456');
  });

  it('displays formatted date', async () => {
    render(
      <EmailDetailModal
        emailId="email-123"
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    await waitFor(() => {
      // Date should be formatted in French locale
      expect(screen.getByText(/19 janv\./)).toBeInTheDocument();
    });
  });
});

// ─── Export PDF button ────────────────────────────────────────────────────────
vi.mock('../api/emails', () => ({
  getCachedEmailDetail: vi.fn(() => null),
  updateCachedEmailDetail: vi.fn(),
}));
vi.mock('../services/draftStorage', () => ({
  getReplyDraftForEmail: vi.fn(() => null),
}));
vi.mock('../services/api', () => ({
  apiClient: {
    request: vi.fn(),
    // EmailDetailModal mounts → fetch pending draft for the email. Without
    // this stub the component crashes on `apiClient.getPendingDraftByEmailId is not a function`.
    getPendingDraftByEmailId: vi.fn(() => Promise.resolve(null)),
  },
  blockSender: vi.fn(),
}));
vi.mock('../services/websocket', () => ({
  getWebSocketClient: vi.fn(() => ({ subscribe: vi.fn(() => vi.fn()), on: vi.fn(), off: vi.fn() })),
}));
vi.mock('../hooks/useContactAvatar', () => ({
  useContactAvatar: vi.fn(() => null),
}));

const okJson = (data: unknown) => ({
  ok: true,
  json: () => Promise.resolve(data),
});

const flushPromises = () => act(async () => {
  await Promise.resolve();
  await Promise.resolve();
});

describe('EmailDetailModal — body pending backend fetch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockReset();
    (globalThis as unknown as { fetch: typeof mockFetch }).fetch = mockFetch;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('garde le chargement tant que body_fetch_pending vaut true', async () => {
    vi.useFakeTimers();

    const pendingEmail = {
      id: 'email-pending',
      message_id: 'msg-pending',
      thread_id: '',
      sender: 'Sender <sender@example.com>',
      sender_name: 'Sender',
      sender_email: 'sender@example.com',
      recipient: 'me@example.com',
      subject: 'Email sans body immédiat',
      body: '',
      body_html: null,
      body_fetch_pending: true,
      has_attachments: false,
      attachments: [],
      received_at: '2026-05-19T10:30:00Z',
    };
    const readyEmail = {
      ...pendingEmail,
      body: 'Le contenu est prêt.',
      body_fetch_pending: false,
    };

    mockFetch
      .mockResolvedValueOnce(okJson(pendingEmail))
      .mockResolvedValueOnce(okJson(pendingEmail))
      .mockResolvedValueOnce(okJson(pendingEmail))
      .mockResolvedValueOnce(okJson(readyEmail));

    render(
      <EmailDetailModal
        emailId="email-pending"
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    await flushPromises();
    expect(screen.getByText('Email sans body immédiat')).toBeInTheDocument();
    expect(screen.getByText(/Chargement|Loading/i)).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    await flushPromises();
    expect(mockFetch).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(7000);
    });
    await flushPromises();
    expect(mockFetch).toHaveBeenCalledTimes(3);

    expect(screen.queryByText(/contenu.*chargé|content could not be loaded/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Chargement|Loading/i)).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(14000);
    });
    await flushPromises();

    expect(screen.getByText(/Le contenu est prêt/)).toBeInTheDocument();
  });
});

describe('EmailDetailModal — contrôles de conversation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockReset();
    (globalThis as unknown as { fetch: typeof mockFetch }).fetch = mockFetch;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const currentEmail = {
    id: 'email-current',
    message_id: 'msg-current',
    thread_id: 'thread-two',
    sender: 'Me <me@example.com>',
    sender_name: 'Me',
    sender_email: 'me@example.com',
    recipient: 'alex@example.com',
    to: ['alex@example.com'],
    cc: [],
    subject: 'Re: Projet',
    body: 'Ma réponse.',
    body_fetch_pending: false,
    has_attachments: false,
    attachments: [],
    received_at: '2026-05-21T10:00:00Z',
    is_sent: true,
  };
  const previousEmail = {
    id: 'email-previous',
    message_id: 'msg-previous',
    thread_id: 'thread-two',
    sender: 'Alex <alex@example.com>',
    sender_name: 'Alex',
    sender_email: 'alex@example.com',
    recipient: 'me@example.com',
    to: ['me@example.com'],
    cc: [],
    subject: 'Projet',
    body: 'Message initial.',
    body_fetch_pending: false,
    has_attachments: false,
    attachments: [],
    received_at: '2026-05-21T09:00:00Z',
    is_sent: false,
  };

  const mockTwoMessageThread = () => {
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/thread')) {
        return Promise.resolve(okJson({ emails: [previousEmail] }));
      }
      return Promise.resolve(okJson(currentEmail));
    });
  };

  it('affiche un toggle unique qui alterne Tout développer / Tout réduire', async () => {
    mockTwoMessageThread();

    render(
      <EmailDetailModal
        emailId="email-current"
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    // Initial state: latest auto-expanded, older collapsed → label offers "expand all".
    const toggle = await screen.findByRole(
      'button', { name: /tout développer|expand all/i }, { timeout: 5000 },
    );
    // Single toggle: the old second button is gone.
    expect(screen.queryByRole('button', { name: /tout réduire|collapse all/i })).not.toBeInTheDocument();

    // Click → everything expanded → same button now offers "collapse all".
    fireEvent.click(toggle);
    expect(await screen.findByRole('button', { name: /tout réduire|collapse all/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /tout développer|expand all/i })).not.toBeInTheDocument();

    // Click again → everything collapsed → back to "expand all".
    fireEvent.click(screen.getByRole('button', { name: /tout réduire|collapse all/i }));
    expect(await screen.findByRole('button', { name: /tout développer|expand all/i })).toBeInTheDocument();
  });

  it('ré-expand le dernier message quand le composer s\'ouvre avec tout replié', async () => {
    mockTwoMessageThread();

    const { rerender, container } = render(
      <EmailDetailModal
        emailId="email-current"
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    // Latest message auto-expanded on load (the collapsed sibling shows only
    // a snippet — the body text also appears there, so assert on the card
    // class, not on the text).
    await waitFor(() => {
      expect(container.querySelector('.thread-card-expanded')).not.toBeNull();
    }, { timeout: 5000 });

    // User collapses everything: click the expanded card's header to fold it.
    fireEvent.click(container.querySelector('.thread-card-expanded .thread-card-header')!);
    await waitFor(() => {
      expect(container.querySelector('.thread-card-expanded')).toBeNull();
    });

    // Opening the reply composer must restore the context: the latest
    // message re-expands so the user sees what they are replying to.
    rerender(
      <EmailDetailModal
        emailId="email-current"
        isOpen={true}
        onClose={vi.fn()}
        triggerReplyType="reply"
        onTriggerReplyHandled={vi.fn()}
      />
    );
    await waitFor(() => {
      expect(container.querySelector('.thread-card-expanded')).not.toBeNull();
    }, { timeout: 5000 });
  });

  it('affiche Réessayer et relance le callback quand le body d’un message du thread manque', () => {
    const onRetryBody = vi.fn();
    const emptyThreadMessage: EmailDetail = {
      id: 'email-empty',
      messageId: 'msg-empty',
      threadId: 'thread-retry',
      sender: 'Alex <alex@example.com>',
      senderName: 'Alex',
      senderEmail: 'alex@example.com',
      recipient: 'me@example.com',
      to: ['me@example.com'],
      cc: [],
      subject: 'Body manquant',
      body: '',
      receivedAt: '2026-05-21T09:00:00Z',
      isSent: false,
      attachments: [],
    };

    render(
      <ThreadMessageCard
        message={emptyThreadMessage}
        isExpanded={true}
        isLatest={false}
        isLoadingBody={false}
        onToggle={vi.fn()}
        onRetryBody={onRetryBody}
        userEmail="me@example.com"
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /réessayer|retry/i }));

    expect(onRetryBody).toHaveBeenCalledTimes(1);
  });

  it('affiche une action de reconnexion quand le provider demande une réauth', () => {
    const onRetryBody = vi.fn();
    const authExpiredMessage: EmailDetail = {
      id: 'email-auth-expired',
      messageId: 'msg-auth-expired',
      threadId: 'thread-auth-expired',
      sender: 'Alex <alex@example.com>',
      senderName: 'Alex',
      senderEmail: 'alex@example.com',
      recipient: 'me@example.com',
      to: ['me@example.com'],
      cc: [],
      subject: 'Body indisponible',
      body: '',
      bodyFetchPending: true,
      providerUnavailable: true,
      needsReauth: true,
      receivedAt: '2026-05-21T09:00:00Z',
      isSent: false,
      attachments: [],
    };

    render(
      <ThreadMessageCard
        message={authExpiredMessage}
        isExpanded={true}
        isLatest={false}
        isLoadingBody={true}
        onToggle={vi.fn()}
        onRetryBody={onRetryBody}
        userEmail="me@example.com"
      />
    );

    expect(screen.getByText(/Reconnectez|Reconnect this account|Vuelve a conectar/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /paramètres|settings|ajustes/i })).toBeInTheDocument();
    expect(screen.queryByText(/Chargement|Loading|Cargando/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /réessayer|retry|reintentar/i })).not.toBeInTheDocument();
    expect(onRetryBody).not.toHaveBeenCalled();
  });
});

describe('EmailDetailModal — export PDF via menu contextuel uniquement', () => {
  it('n\'affiche pas de bouton impression dans le header', () => {
    (globalThis as unknown as { fetch: ReturnType<typeof vi.fn> }).fetch = vi.fn(() => new Promise(() => {}));
    render(
      <EmailDetailModal
        emailId="email-123"
        isOpen={true}
        onClose={vi.fn()}
      />
    );
    expect(screen.queryByTitle('Exporter en PDF (Ctrl+P)')).not.toBeInTheDocument();
  });
});
