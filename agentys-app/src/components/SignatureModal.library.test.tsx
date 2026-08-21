import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SignatureModal } from './SignatureModal';
import {
  listSignatures,
  createSignature,
  updateSignatureEntry,
  deleteSignatureEntry,
  setDefaultSignature,
} from '../api/accounts';
import { setAccountSignatureCache } from '../hooks/useAccountSignature';

// Réseau mocké : un compte + une bibliothèque de 2 signatures (Pro = défaut).
vi.mock('../api/accounts', () => ({
  fetchAccounts: vi.fn().mockResolvedValue({
    accounts: [{ id: 'acc1', email: 'me@example.com', provider: 'gmail', signature: 'Pro sig', signature_html: '<div>Pro sig</div>' }],
    current_account_id: 'acc1',
  }),
  updateAccountSignature: vi.fn().mockResolvedValue({}),
  syncSignature: vi.fn(),
  uploadSignatureImage: vi.fn(),
  listSignatures: vi.fn(),
  createSignature: vi.fn(),
  updateSignatureEntry: vi.fn(),
  deleteSignatureEntry: vi.fn().mockResolvedValue({ success: true }),
  setDefaultSignature: vi.fn(),
}));
vi.mock('../hooks/useAccountSignature', () => ({
  setAccountSignatureCache: vi.fn(),
}));

const ENTRIES = [
  { id: 'sig_a', name: 'Pro', html: '<div>Pro sig</div>', text: 'Pro sig', is_default: true },
  { id: 'sig_b', name: 'Perso', html: '<div>Perso sig</div>', text: 'Perso sig', is_default: false },
];

function mockLibrary(entries = ENTRIES) {
  vi.mocked(listSignatures).mockResolvedValue({
    signatures: entries.map(e => ({ ...e })),
    default_id: entries.find(e => e.is_default)?.id ?? null,
  });
}

async function renderModal() {
  render(<SignatureModal isOpen onClose={vi.fn()} />);
  await screen.findByTestId('sig-list');
}

describe('SignatureModal — bibliothèque multi-signatures', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLibrary();
  });

  it('affiche la liste des signatures avec le badge défaut', async () => {
    await renderModal();
    expect(screen.getByText('Pro')).toBeInTheDocument();
    expect(screen.getByText('Perso')).toBeInTheDocument();
    const items = screen.getAllByTestId('sig-list-item');
    expect(items).toHaveLength(2);
    // Un seul badge défaut, porté par la ligne "Pro"
    const badges = screen.getAllByTestId('sig-default-badge');
    expect(badges).toHaveLength(1);
    expect(items[0]).toContainElement(badges[0]);
  });

  it('la ligne fantôme "ajouter" ouvre l\'éditeur vide', async () => {
    await renderModal();
    fireEvent.click(screen.getByTestId('sig-add-row'));
    const nameInput = await screen.findByTestId('sig-name-input');
    expect((nameInput as HTMLInputElement).value).toBe('');
    expect(document.querySelector('.sig-editor')).toBeTruthy();
  });

  it('cliquer une signature ouvre l\'éditeur pré-rempli et Save met à jour la bibliothèque', async () => {
    vi.mocked(updateSignatureEntry).mockResolvedValue({
      success: true,
      signature: { ...ENTRIES[1], name: 'Perso 2' },
    });
    await renderModal();
    fireEvent.click(screen.getByText('Perso'));
    const nameInput = await screen.findByTestId('sig-name-input');
    expect((nameInput as HTMLInputElement).value).toBe('Perso');

    fireEvent.change(nameInput, { target: { value: 'Perso 2' } });
    fireEvent.click(screen.getByTestId('sig-save'));

    await waitFor(() => expect(updateSignatureEntry).toHaveBeenCalled());
    const [accountId, sigId, payload] = vi.mocked(updateSignatureEntry).mock.calls[0];
    expect(accountId).toBe('acc1');
    expect(sigId).toBe('sig_b');
    expect(payload.name).toBe('Perso 2');
    expect(payload.html).toContain('Perso sig');
  });

  it('"définir par défaut" (radio) appelle l\'API et met à jour le cache composer', async () => {
    vi.mocked(setDefaultSignature).mockResolvedValue({
      success: true,
      signature: { ...ENTRIES[1], is_default: true },
    });
    await renderModal();
    // Radio group « signature par défaut » : un radio par ligne (choix unique).
    const radios = screen.getAllByTestId('sig-set-default') as HTMLInputElement[];
    expect(radios).toHaveLength(2);
    const perso = radios.find(r => !r.checked)!; // l'entrée non-défaut (Perso)
    fireEvent.click(perso);

    await waitFor(() => expect(setDefaultSignature).toHaveBeenCalledWith('acc1', 'sig_b'));
    await waitFor(() =>
      expect(setAccountSignatureCache).toHaveBeenCalledWith('<div>Perso sig</div>', 'Perso sig', expect.anything())
    );
  });

  it('supprimer une signature appelle l\'API et retire la ligne', async () => {
    await renderModal();
    const deleteButtons = screen.getAllByTestId('sig-delete');
    fireEvent.click(deleteButtons[1]); // supprime "Perso"

    await waitFor(() => expect(deleteSignatureEntry).toHaveBeenCalledWith('acc1', 'sig_b'));
  });

  it('Save depuis la ligne fantôme crée une nouvelle signature', async () => {
    vi.mocked(createSignature).mockResolvedValue({
      success: true,
      signature: { id: 'sig_c', name: 'Nouvelle', html: '<div>x</div>', text: 'x', is_default: false },
    });
    await renderModal();
    fireEvent.click(screen.getByTestId('sig-add-row'));
    const nameInput = await screen.findByTestId('sig-name-input');
    fireEvent.change(nameInput, { target: { value: 'Nouvelle' } });
    const editor = document.querySelector('.sig-editor') as HTMLElement;
    editor.innerHTML = '<div>contenu</div>';
    fireEvent.input(editor);
    fireEvent.click(screen.getByTestId('sig-save'));

    await waitFor(() => expect(createSignature).toHaveBeenCalled());
    const [accountId, payload] = vi.mocked(createSignature).mock.calls[0];
    expect(accountId).toBe('acc1');
    expect(payload.name).toBe('Nouvelle');
    expect(payload.html).toContain('contenu');
  });
});
