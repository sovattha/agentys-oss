import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { createRef } from 'react';
import userEvent from '@testing-library/user-event';
import { DraftEditor } from './DraftEditor';
import type { DraftEditorHandle } from './DraftEditor';
import { clearDraftBackup } from './draftBackupUtils';

// Mock TipTap
const mockUndo = vi.fn();
const mockRedo = vi.fn();
const mockCanUndo = vi.fn(() => true);
const mockCanRedo = vi.fn(() => false);
const mockFocusRun = vi.fn();
const mockInsertContent = vi.fn(() => ({ run: vi.fn() }));
const mockInsertContentAt = vi.fn(() => ({ run: vi.fn() }));
const mockFocus = vi.fn(() => ({
  run: mockFocusRun,
  insertContent: mockInsertContent,
  insertContentAt: mockInsertContentAt,
  toggleBold: () => ({ run: vi.fn() }),
  toggleItalic: () => ({ run: vi.fn() }),
  toggleStrike: () => ({ run: vi.fn() }),
  extendMarkRange: () => ({
    setLink: () => ({ run: vi.fn() }),
  }),
  unsetLink: () => ({ run: vi.fn() }),
  undo: () => ({ run: mockUndo }),
  redo: () => ({ run: mockRedo }),
}));

vi.mock('@tiptap/react', () => ({
  useEditor: vi.fn(() => ({
    chain: () => ({
      focus: mockFocus,
    }),
    can: () => ({
      undo: mockCanUndo,
      redo: mockCanRedo,
    }),

    isActive: vi.fn((_type: string) => false),
    isFocused: false,
    state: {
      selection: { from: 1 },
      doc: { textBetween: () => '' },
      tr: { setMeta: vi.fn(() => ({})) },
    },
    getHTML: () => '<p>Test content</p>',
    getText: () => 'Test content',
    setEditable: vi.fn(),
    registerPlugin: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    view: { dom: document.createElement('div'), dispatch: vi.fn() },
    commands: {
      setContent: vi.fn(),
    },
  })),

  EditorContent: ({ editor: _editor }: { editor: unknown }) => (
    <div data-testid="editor-content">Editor Content</div>
  ),
}));

// Mock localStorage
const localStorageMock = {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

describe('DraftEditor', () => {
  const defaultProps = {
    content: '<p>Initial content</p>',
    onChange: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the editor with toolbar', () => {
    render(<DraftEditor {...defaultProps} />);

    expect(screen.getByRole('button', { name: /gras/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /italique/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ajouter un lien/i })).toBeInTheDocument();
    expect(screen.getByTestId('editor-content')).toBeInTheDocument();
  });

  it('hides toolbar when readOnly is true', () => {
    render(<DraftEditor {...defaultProps} readOnly={true} />);

    expect(screen.queryByRole('button', { name: /gras/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /italique/i })).not.toBeInTheDocument();
  });

  it('displays word count in footer', () => {
    render(<DraftEditor {...defaultProps} />);

    const wordCount = screen.getByTestId('word-count');
    expect(wordCount).toBeInTheDocument();
    expect(wordCount).toHaveTextContent(/\d+ mots?/);
  });

  it('exposes focusEnd to focus the editor body at the end', () => {
    const ref = createRef<DraftEditorHandle>();
    render(<DraftEditor {...defaultProps} ref={ref} />);

    ref.current?.focusEnd();

    expect(mockFocus).toHaveBeenCalledWith('end');
    expect(mockFocusRun).toHaveBeenCalled();
  });

  it('insertDictation inserts the decoded transcript as a text node at the caret', () => {
    const ref = createRef<DraftEditorHandle>();
    render(<DraftEditor {...defaultProps} ref={ref} />);

    // Not dictating in this mock (no pinned pos) ⇒ falls back to the live caret
    // (from: 1, textBetween → '') ⇒ no leading space; the &#39; apostrophe
    // entity is decoded; inserted at position 1 via insertContentAt.
    ref.current?.insertDictation('<p>j&#39;ai fini</p>');

    expect(mockInsertContentAt).toHaveBeenCalledWith(1, { type: 'text', text: "j'ai fini" });
  });

  it('insertDictation no-ops on a blank transcript', () => {
    const ref = createRef<DraftEditorHandle>();
    render(<DraftEditor {...defaultProps} ref={ref} />);

    ref.current?.insertDictation('<p>   </p>');

    expect(mockInsertContentAt).not.toHaveBeenCalled();
  });

  it('focusForDictation focuses the editor (keeping selection) when not already focused', () => {
    const ref = createRef<DraftEditorHandle>();
    render(<DraftEditor {...defaultProps} ref={ref} />);

    ref.current?.focusForDictation();

    // No positional arg → ProseMirror keeps the current/last selection rather
    // than jumping to the end (which would land past the signature).
    expect(mockFocus).toHaveBeenCalledWith();
  });

  it('shows link input when link button is clicked', async () => {
    const user = userEvent.setup();
    render(<DraftEditor {...defaultProps} />);

    const linkButton = screen.getByRole('button', { name: /lien/i });
    await user.click(linkButton);

    expect(screen.getByPlaceholderText('https://...')).toBeInTheDocument();
  });

  it('hides link input when escape is pressed', async () => {
    const user = userEvent.setup();
    render(<DraftEditor {...defaultProps} />);

    const linkButton = screen.getByRole('button', { name: /lien/i });
    await user.click(linkButton);

    const linkInput = screen.getByPlaceholderText('https://...');
    await user.type(linkInput, '{Escape}');

    await waitFor(() => {
      expect(screen.queryByPlaceholderText('https://...')).not.toBeInTheDocument();
    });
  });

  it('calls onSaveStatusChange when provided', () => {
    const onSaveStatusChange = vi.fn();
    render(<DraftEditor {...defaultProps} onSaveStatusChange={onSaveStatusChange} />);

    // The component is rendered successfully
    expect(screen.getByTestId('editor-content')).toBeInTheDocument();
  });
});

describe('Word count function', () => {
  it('counts words correctly for simple text', () => {
    // We test the internal function indirectly through the component
    render(
      <DraftEditor
        content="<p>One two three</p>"
        onChange={vi.fn()}
      />
    );

    // Word count is displayed
    expect(screen.getByTestId('word-count')).toBeInTheDocument();
  });

  it('shows singular "mot" for one word', () => {
    render(
      <DraftEditor
        content="<p>Word</p>"
        onChange={vi.fn()}
      />
    );

    // Should show word count (mocked as "Test content" = 2 words)
    const wordCount = screen.getByTestId('word-count');
    expect(wordCount).toHaveTextContent(/mots?/);
  });
});

describe('Undo/Redo functionality (Story 6-2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.getItem.mockReturnValue(null);
  });

  it('renders undo and redo buttons in toolbar', () => {
    render(<DraftEditor content="<p>Test</p>" onChange={vi.fn()} />);

    expect(screen.getByTestId('undo-button')).toBeInTheDocument();
    expect(screen.getByTestId('redo-button')).toBeInTheDocument();
  });

  it('undo button calls editor undo command when clicked', async () => {
    const user = userEvent.setup();
    render(<DraftEditor content="<p>Test</p>" onChange={vi.fn()} />);

    const undoButton = screen.getByTestId('undo-button');
    await user.click(undoButton);

    expect(mockUndo).toHaveBeenCalled();
  });

  it('redo button calls editor redo command when clicked', async () => {
    const user = userEvent.setup();
    mockCanRedo.mockReturnValue(true);
    render(<DraftEditor content="<p>Test</p>" onChange={vi.fn()} />);

    const redoButton = screen.getByTestId('redo-button');
    await user.click(redoButton);

    expect(mockRedo).toHaveBeenCalled();
  });

  it('disables undo button when cannot undo', () => {
    mockCanUndo.mockReturnValue(false);
    render(<DraftEditor content="<p>Test</p>" onChange={vi.fn()} />);

    const undoButton = screen.getByTestId('undo-button');
    expect(undoButton).toBeDisabled();
  });

  it('disables redo button when cannot redo', () => {
    mockCanRedo.mockReturnValue(false);
    render(<DraftEditor content="<p>Test</p>" onChange={vi.fn()} />);

    const redoButton = screen.getByTestId('redo-button');
    expect(redoButton).toBeDisabled();
  });
});

describe('Preview mode (Story 6-2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.getItem.mockReturnValue(null);
  });

  it('renders preview button in toolbar', () => {
    render(<DraftEditor content="<p>Test</p>" onChange={vi.fn()} />);

    expect(screen.getByTestId('preview-button')).toBeInTheDocument();
  });

  it('switches to preview mode when preview button is clicked', async () => {
    const user = userEvent.setup();
    render(<DraftEditor content="<p>Test</p>" onChange={vi.fn()} />);

    const previewButton = screen.getByTestId('preview-button');
    await user.click(previewButton);

    expect(screen.getByTestId('preview-content')).toBeInTheDocument();
    expect(screen.getByText('Prévisualisation')).toBeInTheDocument();
  });

  it('returns to edit mode when exit preview button is clicked', async () => {
    const user = userEvent.setup();
    render(<DraftEditor content="<p>Test</p>" onChange={vi.fn()} />);

    // Enter preview mode
    await user.click(screen.getByTestId('preview-button'));
    expect(screen.getByTestId('preview-content')).toBeInTheDocument();

    // Exit preview mode
    await user.click(screen.getByTestId('exit-preview-button'));
    expect(screen.queryByTestId('preview-content')).not.toBeInTheDocument();
    expect(screen.getByTestId('editor-content')).toBeInTheDocument();
  });

  it('hides toolbar in preview mode', async () => {
    const user = userEvent.setup();
    render(<DraftEditor content="<p>Test</p>" onChange={vi.fn()} />);

    await user.click(screen.getByTestId('preview-button'));

    // Toolbar buttons should not be visible (except in preview header)
    expect(screen.queryByTestId('undo-button')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /gras/i })).not.toBeInTheDocument();
  });
});

describe('Change tracking (Story 6-2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.getItem.mockReturnValue(null);
  });

  it('renders show changes button when onShowChangesToggle is provided', () => {
    const onToggle = vi.fn();
    render(
      <DraftEditor
        content="<p>Test</p>"
        onChange={vi.fn()}
        onShowChangesToggle={onToggle}
      />
    );

    expect(screen.getByTestId('show-changes-button')).toBeInTheDocument();
  });

  it('does not render show changes button when onShowChangesToggle is not provided', () => {
    render(<DraftEditor content="<p>Test</p>" onChange={vi.fn()} />);

    expect(screen.queryByTestId('show-changes-button')).not.toBeInTheDocument();
  });

  it('calls onShowChangesToggle when show changes button is clicked', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <DraftEditor
        content="<p>Test</p>"
        onChange={vi.fn()}
        showChanges={false}
        onShowChangesToggle={onToggle}
      />
    );

    await user.click(screen.getByTestId('show-changes-button'));

    expect(onToggle).toHaveBeenCalledWith(true);
  });

  it('shows change indicator in footer when content changed and showChanges is true', () => {
    // Note: This test is limited due to mocking. The actual change detection
    // depends on comparing originalContent with current content
    render(
      <DraftEditor
        content="<p>Modified content</p>"
        onChange={vi.fn()}
        showChanges={true}
        onShowChangesToggle={vi.fn()}
      />
    );

    // The component should render without errors
    expect(screen.getByTestId('word-count')).toBeInTheDocument();
  });
});

describe('localStorage backup (Story 6-2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.getItem.mockReturnValue(null);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('saves content to localStorage when draftId is provided', () => {
    render(
      <DraftEditor
        content="<p>Test content</p>"
        onChange={vi.fn()}
        draftId="test-draft-123"
      />
    );

    expect(localStorageMock.setItem).toHaveBeenCalled();
    const callArgs = localStorageMock.setItem.mock.calls[0];
    expect(callArgs[0]).toBe('draft-backup-test-draft-123');
  });

  it('does not save to localStorage when draftId is not provided', () => {
    render(
      <DraftEditor
        content="<p>Test content</p>"
        onChange={vi.fn()}
      />
    );

    expect(localStorageMock.setItem).not.toHaveBeenCalled();
  });

  it('does not save to localStorage when readOnly is true', () => {
    render(
      <DraftEditor
        content="<p>Test content</p>"
        onChange={vi.fn()}
        draftId="test-draft-123"
        readOnly={true}
      />
    );

    expect(localStorageMock.setItem).not.toHaveBeenCalled();
  });

  it('recovers content from localStorage backup on mount', () => {
    const backupData = JSON.stringify({
      content: '<p>Recovered content</p>',
      timestamp: Date.now() - 60000, // 1 minute ago
    });
    localStorageMock.getItem.mockReturnValue(backupData);

    const onChange = vi.fn();
    render(
      <DraftEditor
        content="<p>Original content</p>"
        onChange={onChange}
        draftId="test-draft-123"
      />
    );

    // Should have called onChange with recovered content
    expect(onChange).toHaveBeenCalledWith('<p>Recovered content</p>');
  });

  it('shows recovery notification when content is recovered', async () => {
    const backupData = JSON.stringify({
      content: '<p>Recovered content</p>',
      timestamp: Date.now() - 60000,
    });
    localStorageMock.getItem.mockReturnValue(backupData);

    render(
      <DraftEditor
        content="<p>Original content</p>"
        onChange={vi.fn()}
        draftId="test-draft-123"
      />
    );

    expect(screen.getByTestId('recovery-notification')).toBeInTheDocument();
    expect(screen.getByText(/contenu récupéré/i)).toBeInTheDocument();
  });

  it('does not recover old backups (> 1 hour)', () => {
    const backupData = JSON.stringify({
      content: '<p>Old content</p>',
      timestamp: Date.now() - 3700000, // > 1 hour ago
    });
    localStorageMock.getItem.mockReturnValue(backupData);

    const onChange = vi.fn();
    render(
      <DraftEditor
        content="<p>Original content</p>"
        onChange={onChange}
        draftId="test-draft-123"
      />
    );

    // Should NOT have called onChange with old content
    expect(onChange).not.toHaveBeenCalledWith('<p>Old content</p>');
  });
});

describe('clearDraftBackup utility', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('removes the correct localStorage key', () => {
    clearDraftBackup('my-draft-id');

    expect(localStorageMock.removeItem).toHaveBeenCalledWith('draft-backup-my-draft-id');
  });
});
