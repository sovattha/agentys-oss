/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

/**
 * Regression tests — Portal fixes + recent changes (2026-04-11)
 *
 * Covers:
 * 1. AICommandMenu portal rendering (escapes overflow:hidden)
 * 2. AICommandMenu open/close/command interactions
 * 3. i18n key completeness (ai_process across locales)
 * 4. Slash commands data integrity
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { AICommandMenu } from '../components/compose/AICommandMenu';
import {
  savedCmdsKey,
  loadSaved,
  persistSaved,
  _resetAccountIdCacheForTests,
} from '../components/compose/aiCommandStorage';

// Stub fetchAccounts so AICommandMenu's mount-time fetch doesn't hit the network
vi.mock('../api/accounts', () => ({
  fetchAccounts: vi.fn().mockResolvedValue({ accounts: [], current_account_id: null, count: 0 }),
}));
import { SLASH_COMMANDS, isBinaryQuestion } from '../utils/slash-commands';

// i18n locale imports for key verification
import frDrafts from '../i18n/locales/fr/drafts.json';
import enDrafts from '../i18n/locales/en/drafts.json';
import esDrafts from '../i18n/locales/es/drafts.json';
import frCompose from '../i18n/locales/fr/compose.json';
import enCompose from '../i18n/locales/en/compose.json';
import esCompose from '../i18n/locales/es/compose.json';

// ── Helpers ────────────────────────────────────────────────────────────────────

function cleanPortals() {
  document.body.querySelectorAll('.ai-cmd-popover').forEach(el => el.remove());
}

/** Render AICommandMenu and open the popover; returns the portal element */
async function renderAndOpen(props: Partial<Parameters<typeof AICommandMenu>[0]> = {}) {
  const defaultProps = {
    commands: SLASH_COMMANDS,
    onCommandSelect: vi.fn(),
    onCustomSubmit: vi.fn(),
    onDictate: vi.fn(),
    isRecording: false,
    isTranscribing: false,
    onStopRecording: vi.fn(),
    showDictateOption: false,
    transcriptionError: null,
    ...props,
  };

  const result = render(<AICommandMenu {...defaultProps} />);
  fireEvent.click(screen.getByTestId('ai-command-trigger'));

  await waitFor(() => {
    expect(document.body.querySelector('.ai-cmd-popover--portal')).toBeTruthy();
  });

  return { ...result, props: defaultProps };
}

// ============================================================================
// 1. AICommandMenu — Portal rendering & interactions
// ============================================================================

describe('AICommandMenu', () => {
  const defaultProps = {
    commands: SLASH_COMMANDS,
    onCommandSelect: vi.fn(),
    onCustomSubmit: vi.fn(),
    onDictate: vi.fn(),
    isRecording: false,
    isTranscribing: false,
    onStopRecording: vi.fn(),
    showDictateOption: false,
    transcriptionError: null,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    // Suppress the first-open default-seed (aiCommandStorage.loadSaved) so
    // these tests assert on user-driven storage behavior, not on the four
    // built-in chips. Seeding has its own dedicated coverage below.
    localStorage.setItem('ai-cmd-seeded:', '1');
    cleanPortals();
    _resetAccountIdCacheForTests();
  });

  afterEach(() => {
    cleanup();
    cleanPortals();
  });

  it('renders trigger button', () => {
    render(<AICommandMenu {...defaultProps} />);
    expect(screen.getByTestId('ai-command-trigger')).toBeInTheDocument();
  });

  it('trigger button has correct aria attributes when closed', () => {
    render(<AICommandMenu {...defaultProps} />);
    const btn = screen.getByTestId('ai-command-trigger');
    expect(btn).toHaveAttribute('aria-haspopup', 'menu');
    expect(btn).toHaveAttribute('aria-expanded', 'false');
  });

  it('opens popover via portal on click (renders in document.body, NOT inside overflow container)', async () => {
    render(
      <div style={{ overflow: 'hidden', height: '100px' }} data-testid="overflow-parent">
        <AICommandMenu {...defaultProps} />
      </div>
    );

    fireEvent.click(screen.getByTestId('ai-command-trigger'));

    await waitFor(() => {
      const popover = document.body.querySelector('.ai-cmd-popover--portal');
      expect(popover).toBeTruthy();
      // Popover must NOT be inside the overflow:hidden parent
      expect(popover!.closest('[data-testid="overflow-parent"]')).toBeNull();
    });
  });

  it('popover has position-related inline styles (bottom + left)', async () => {
    await renderAndOpen();
    const popover = document.body.querySelector('.ai-cmd-popover--portal') as HTMLElement;
    // Portal variant sets bottom/left via inline style from getBoundingClientRect
    expect(popover.style.bottom).toBeTruthy();
    expect(popover.style.left).toBeTruthy();
  });

  it('clamps the portal popover inside the viewport when opened near the right edge', async () => {
    const originalWidth = window.innerWidth;
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 });
    const rectSpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.dataset.testid === 'ai-command-trigger') {
        return {
          x: 360,
          y: 520,
          left: 360,
          right: 384,
          top: 520,
          bottom: 544,
          width: 24,
          height: 24,
          toJSON: () => ({}),
        } as DOMRect;
      }
      return {
        x: 0,
        y: 0,
        left: 0,
        right: 0,
        top: 0,
        bottom: 0,
        width: 0,
        height: 0,
        toJSON: () => ({}),
      } as DOMRect;
    });

    try {
      await renderAndOpen();
      const popover = document.body.querySelector('.ai-cmd-popover--portal') as HTMLElement;
      const left = Number.parseFloat(popover.style.left);
      const width = Number.parseFloat(popover.style.width);
      expect(left).toBeGreaterThanOrEqual(16);
      expect(left + width).toBeLessThanOrEqual(390 - 16);
    } finally {
      rectSpy.mockRestore();
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth });
    }
  });

  it('sets aria-expanded to true when open', async () => {
    await renderAndOpen();
    expect(screen.getByTestId('ai-command-trigger')).toHaveAttribute('aria-expanded', 'true');
  });

  it('displays all SLASH_COMMANDS as menu items', async () => {
    await renderAndOpen();
    const menuitems = document.body.querySelectorAll('.ai-cmd-popover--portal [role="menuitem"]');
    expect(menuitems.length).toBeGreaterThanOrEqual(SLASH_COMMANDS.length);
  });

  it('shows dictate option when showDictateOption is true (first click = dictate)', () => {
    render(<AICommandMenu {...defaultProps} showDictateOption />);
    // When showDictateOption=true AND menu not open, first click triggers dictation
    fireEvent.click(screen.getByTestId('ai-command-trigger'));
    expect(defaultProps.onDictate).toHaveBeenCalledOnce();
  });

  it('disables the mic trigger when dictation access is not allowed', () => {
    const onDictate = vi.fn();
    render(<AICommandMenu {...defaultProps} showDictateOption dictationEnabled={false} onDictate={onDictate} />);

    const trigger = screen.getByTestId('ai-command-trigger');
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);
    expect(onDictate).not.toHaveBeenCalled();
  });

  it('disables the inline mic without blocking the command menu', async () => {
    const { props } = await renderAndOpen({ dictationEnabled: false });

    const inlineMic = document.body.querySelector('.ai-cmd-inline-mic') as HTMLButtonElement;
    expect(inlineMic).toBeDisabled();
    fireEvent.click(inlineMic);
    expect(props.onDictate).not.toHaveBeenCalled();
  });

  it('calls onCommandSelect and closes menu when command clicked', async () => {
    const { props } = await renderAndOpen();

    const menuItems = document.body.querySelectorAll('.ai-cmd-popover--portal .ai-cmd-row');
    expect(menuItems.length).toBeGreaterThan(0);
    fireEvent.click(menuItems[0]);

    expect(props.onCommandSelect).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(document.body.querySelector('.ai-cmd-popover--portal')).toBeNull();
    });
  });

  it('custom prompt input submits on Enter', async () => {
    const { props } = await renderAndOpen();

    const input = document.body.querySelector('.ai-cmd-input') as HTMLInputElement;
    expect(input).toBeTruthy();
    fireEvent.change(input, { target: { value: 'Test prompt' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(props.onCustomSubmit).toHaveBeenCalledWith('Test prompt');
  });

  it('does NOT submit empty prompt', async () => {
    const { props } = await renderAndOpen();

    const input = document.body.querySelector('.ai-cmd-input') as HTMLInputElement;
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(props.onCustomSubmit).not.toHaveBeenCalled();
  });

  it('closes menu on Escape key', async () => {
    await renderAndOpen();

    fireEvent.keyDown(document, { key: 'Escape' });

    await waitFor(() => {
      expect(document.body.querySelector('.ai-cmd-popover--portal')).toBeNull();
    });
  });

  it('closes menu on outside click (mousedown on document.body)', async () => {
    await renderAndOpen();

    // Create a separate element to click on (outside the portal)
    const outsideEl = document.createElement('div');
    document.body.appendChild(outsideEl);
    fireEvent.mouseDown(outsideEl);
    outsideEl.remove();

    await waitFor(() => {
      expect(document.body.querySelector('.ai-cmd-popover--portal')).toBeNull();
    });
  });

  it('does NOT close when clicking inside popover', async () => {
    await renderAndOpen();

    const popover = document.body.querySelector('.ai-cmd-popover--portal')!;
    fireEvent.mouseDown(popover);

    // Popover should still be visible
    expect(document.body.querySelector('.ai-cmd-popover--portal')).toBeTruthy();
  });

  it('disables trigger when disabled prop is true', () => {
    render(<AICommandMenu {...defaultProps} disabled />);
    expect(screen.getByTestId('ai-command-trigger')).toBeDisabled();
  });

  it('disables trigger when isTranscribing is true', () => {
    // showDictateOption requis pour que isTranscribing impacte le bouton
    // (cf. AICommandMenu.tsx:421 — disabled = isTranscribing && showDictateOption)
    render(<AICommandMenu {...defaultProps} isTranscribing showDictateOption />);
    expect(screen.getByTestId('ai-command-trigger')).toBeDisabled();
  });

  it('shows spinner when transcribing', () => {
    render(<AICommandMenu {...defaultProps} isTranscribing showDictateOption />);
    expect(document.querySelector('.ai-cmd-spinner')).toBeTruthy();
  });

  it('shows recording state class when recording', () => {
    // showDictateOption requis pour que la classe ai-cmd-recording soit appliquée
    // (cf. AICommandMenu.tsx:419)
    render(<AICommandMenu {...defaultProps} isRecording showDictateOption />);
    expect(screen.getByTestId('ai-command-trigger')).toHaveClass('ai-cmd-recording');
  });

  it('calls onStopRecording when clicking during recording', () => {
    render(<AICommandMenu {...defaultProps} isRecording />);
    fireEvent.click(screen.getByTestId('ai-command-trigger'));
    expect(defaultProps.onStopRecording).toHaveBeenCalledOnce();
  });

  it('does NOT open popover when recording', () => {
    render(<AICommandMenu {...defaultProps} isRecording />);
    fireEvent.click(screen.getByTestId('ai-command-trigger'));
    expect(document.body.querySelector('.ai-cmd-popover--portal')).toBeNull();
  });

  it('shows transcription error when present', () => {
    render(<AICommandMenu {...defaultProps} transcriptionError="Micro non détecté" />);
    expect(screen.getByText('Micro non détecté')).toBeInTheDocument();
  });

  // Saved commands (localStorage)
  describe('saved commands', () => {
    it('saves custom prompt via pin → save-as flow (Enter to confirm default name)', async () => {
      await renderAndOpen();

      const input = document.body.querySelector('.ai-cmd-input') as HTMLInputElement;
      fireEvent.change(input, { target: { value: 'Mon prompt favori' } });

      const pinBtn = document.body.querySelector('.ai-cmd-pin-btn') as HTMLButtonElement;
      fireEvent.click(pinBtn);

      // Save-as row appears — instruction is NOT yet persisted
      const saveAsRow = document.body.querySelector('[data-testid="ai-cmd-saveas-row"]');
      expect(saveAsRow).toBeTruthy();
      expect(JSON.parse(localStorage.getItem('ai-cmd-saved') || '[]')).toHaveLength(0);

      // Enter on the save-as input commits with the suggested label
      const renameInput = document.body.querySelector('.ai-cmd-saveas-input') as HTMLInputElement;
      fireEvent.keyDown(renameInput, { key: 'Enter' });

      const saved = JSON.parse(localStorage.getItem('ai-cmd-saved') || '[]');
      expect(saved).toHaveLength(1);
      expect(saved[0].instruction).toBe('Mon prompt favori');
      // Default label is the first 3 words of the (filler-stripped) instruction.
      expect(saved[0].label).toBe('Mon prompt favori');
    });

    it('cancelling save-as keeps the instruction in the input and persists nothing', async () => {
      await renderAndOpen();

      const input = document.body.querySelector('.ai-cmd-input') as HTMLInputElement;
      fireEvent.change(input, { target: { value: 'à jeter' } });

      fireEvent.click(document.body.querySelector('.ai-cmd-pin-btn') as HTMLButtonElement);

      const renameInput = document.body.querySelector('.ai-cmd-saveas-input') as HTMLInputElement;
      fireEvent.keyDown(renameInput, { key: 'Escape' });

      expect(document.body.querySelector('[data-testid="ai-cmd-saveas-row"]')).toBeNull();
      expect(JSON.parse(localStorage.getItem('ai-cmd-saved') || '[]')).toHaveLength(0);
      // Instruction stays in the main input so the user can keep editing.
      expect((document.body.querySelector('.ai-cmd-input') as HTMLInputElement).value).toBe('à jeter');
    });

    it('loads saved commands from localStorage on mount', async () => {
      localStorage.setItem('ai-cmd-saved', JSON.stringify([
        { id: 1, label: 'Test cmd', instruction: 'do something' },
      ]));

      await renderAndOpen();

      const savedItems = document.body.querySelectorAll('.ai-cmd-row-label-saved');
      expect(savedItems.length).toBe(1);
      expect(savedItems[0].textContent).toBe('Test cmd');
    });

    it('deletes saved command via delete button', async () => {
      localStorage.setItem('ai-cmd-saved', JSON.stringify([
        { id: 1, label: 'To delete', instruction: 'delete me' },
      ]));

      await renderAndOpen();

      const delBtn = document.body.querySelector('.ai-cmd-row-del');
      expect(delBtn).toBeTruthy();
      fireEvent.click(delBtn!);

      const saved = JSON.parse(localStorage.getItem('ai-cmd-saved') || '[]');
      expect(saved).toHaveLength(0);
    });
  });

  // Keyboard navigation
  describe('keyboard navigation', () => {
    it('ArrowDown from input focuses first menu item', async () => {
      await renderAndOpen();

      const input = document.body.querySelector('.ai-cmd-input')!;
      fireEvent.keyDown(input, { key: 'ArrowDown' });

      // Some menu item should be focused
      expect(document.activeElement?.classList.contains('ai-cmd-row')).toBe(true);
    });

    it('Escape in input closes menu', async () => {
      await renderAndOpen();

      const input = document.body.querySelector('.ai-cmd-input')!;
      fireEvent.keyDown(input, { key: 'Escape' });

      await waitFor(() => {
        expect(document.body.querySelector('.ai-cmd-popover--portal')).toBeNull();
      });
    });
  });
});


// ============================================================================
// 2. Slash commands data integrity
// ============================================================================

describe('Slash commands integrity', () => {
  it('SLASH_COMMANDS has /expand featured (sole entry after Correct/Shorter removal)', () => {
    expect(SLASH_COMMANDS).toHaveLength(1);
    const cmds = Object.fromEntries(SLASH_COMMANDS.map(c => [c.command, c]));
    expect(cmds['/expand']).toMatchObject({ featured: true, expand: true });
    // /correct and /shorter were removed at user request — they triggered
    // unwanted full-body rewrites; surgical edits via SurgicalEditBar are
    // the canonical path now.
    expect(cmds['/correct']).toBeUndefined();
    expect(cmds['/shorter']).toBeUndefined();
  });

  it('all commands have required fields', () => {
    for (const cmd of SLASH_COMMANDS) {
      expect(cmd.command).toMatch(/^\//);
      expect(cmd.label).toBeTruthy();
      expect(cmd.instruction).toBeTruthy();
      expect(cmd.group).toBeTruthy();
    }
  });

  it('isBinaryQuestion returns true for binary question', () => {
    expect(isBinaryQuestion('Peux-tu venir demain ?')).toBe(true);
  });

  it('isBinaryQuestion returns false for open-ended question', () => {
    expect(isBinaryQuestion('Comment vas-tu ?')).toBe(false);
  });

  it('isBinaryQuestion returns false for long body (>2000 chars)', () => {
    expect(isBinaryQuestion('a'.repeat(2001))).toBe(false);
  });

  it('isBinaryQuestion returns false for empty body', () => {
    expect(isBinaryQuestion('')).toBe(false);
  });
});


// ============================================================================
// 3. AI command menu — saved instructions are isolated per account
// ============================================================================

describe('AICommandMenu saved instructions — per-account isolation', () => {
  beforeEach(() => {
    // Wipe any leftover keys from previous tests (incl. the legacy global key
    // and any account-scoped namespaces we are about to write).
    localStorage.removeItem('ai-cmd-saved');
    localStorage.removeItem('ai-cmd-saved:acc-alice');
    localStorage.removeItem('ai-cmd-saved:acc-bob');
    localStorage.removeItem('ai-cmd-saved:acc-carol');
    // Suppress first-open default-seed (aiCommandStorage.loadSaved) for the
    // accounts these tests touch — we're asserting the storage layer's
    // namespacing, not the seeding affordance.
    localStorage.setItem('ai-cmd-seeded:acc-alice', '1');
    localStorage.setItem('ai-cmd-seeded:acc-bob', '1');
    localStorage.setItem('ai-cmd-seeded:acc-carol', '1');
  });

  it('savedCmdsKey scopes the localStorage key by accountId', () => {
    expect(savedCmdsKey('acc-alice')).toBe('ai-cmd-saved:acc-alice');
    expect(savedCmdsKey('acc-bob')).toBe('ai-cmd-saved:acc-bob');
  });

  it('savedCmdsKey falls back to the legacy global key when accountId is null', () => {
    // Backward-compat: keeps reading the old global key for users who haven't
    // yet had their accountId resolved (first paint before fetchAccounts resolves).
    expect(savedCmdsKey(null)).toBe('ai-cmd-saved');
  });

  it('persistSaved writes under the right account namespace', () => {
    persistSaved('acc-alice', [{ id: 1, label: 'A1', instruction: 'alice one' }]);

    // Direct read of the underlying storage to bypass loadSaved
    const raw = localStorage.getItem('ai-cmd-saved:acc-alice');
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw!)).toEqual([{ id: 1, label: 'A1', instruction: 'alice one' }]);

    // No leakage to other namespaces
    expect(localStorage.getItem('ai-cmd-saved:acc-bob')).toBeNull();
    expect(localStorage.getItem('ai-cmd-saved')).toBeNull();
  });

  it('loadSaved reads only from the requested account namespace', () => {
    persistSaved('acc-alice', [{ id: 10, label: 'AliceCmd', instruction: 'A' }]);
    persistSaved('acc-bob',   [{ id: 20, label: 'BobCmd',   instruction: 'B' }]);

    expect(loadSaved('acc-alice')).toEqual([{ id: 10, label: 'AliceCmd', instruction: 'A' }]);
    expect(loadSaved('acc-bob')).toEqual([{ id: 20, label: 'BobCmd', instruction: 'B' }]);
  });

  it('two accounts on the same device cannot see each other commands', () => {
    persistSaved('acc-alice', [
      { id: 1, label: 'rule for client X', instruction: 'always confirm in 1 sentence' },
      { id: 2, label: 'sign off', instruction: 'sign off in french' },
    ]);
    persistSaved('acc-bob', [
      { id: 99, label: 'translate to ES', instruction: 'translate to spanish' },
    ]);

    const alice = loadSaved('acc-alice');
    const bob = loadSaved('acc-bob');

    expect(alice).toHaveLength(2);
    expect(bob).toHaveLength(1);
    expect(alice.find(c => c.id === 99)).toBeUndefined();
    expect(bob.find(c => c.id === 1)).toBeUndefined();
    expect(bob.find(c => c.id === 2)).toBeUndefined();
  });

  it('loadSaved returns [] for an account that has never saved anything', () => {
    persistSaved('acc-alice', [{ id: 1, label: 'X', instruction: 'X' }]);
    expect(loadSaved('acc-carol')).toEqual([]);
  });

  it('loadSaved tolerates corrupted JSON without throwing', () => {
    localStorage.setItem('ai-cmd-saved:acc-alice', '{not valid json');
    expect(() => loadSaved('acc-alice')).not.toThrow();
    expect(loadSaved('acc-alice')).toEqual([]);
  });
});




// ============================================================================
// 3. i18n key completeness — ai_process across all locales
// ============================================================================

describe('i18n regression — ai_process key', () => {
  const locales = [
    { name: 'fr', drafts: frDrafts, compose: frCompose },
    { name: 'en', drafts: enDrafts, compose: enCompose },
    { name: 'es', drafts: esDrafts, compose: esCompose },
  ];

  // The drafts/compose locale objects now contain nested groups (e.g. the
  // `wake_toast` object added with the DraftWakeToast feature), so a direct
  // `as Record<string, string>` cast is no longer a subset relation. The
  // tests only read leaf string keys, so we route through `unknown` to keep
  // the assertion shape without weakening TS elsewhere.
  for (const locale of locales) {
    it(`${locale.name}/drafts.json has "ai_process" key`, () => {
      expect((locale.drafts as unknown as Record<string, string>).ai_process).toBeTruthy();
    });

    it(`${locale.name}/compose.json has "ai_process" key`, () => {
      expect((locale.compose as unknown as Record<string, string>).ai_process).toBeTruthy();
    });
  }

  it('fr drafts ai_process = "Processus IA"', () => {
    expect((frDrafts as unknown as Record<string, string>).ai_process).toBe('Processus IA');
  });

  it('en drafts ai_process = "AI Process"', () => {
    expect((enDrafts as unknown as Record<string, string>).ai_process).toBe('AI Process');
  });
});


// ============================================================================
// 4. i18n key completeness — critical compose & drafts keys
// ============================================================================

describe('i18n regression — critical keys', () => {
  const requiredComposeKeys = [
    'send', 'reply', 'reply_all', 'forward_send',
    'sent_excl', 'sending', 'attach_file', 'snippets',
    'schedule_reminder', 'bullet_list', 'insert_image',
    'tier_simple', 'tier_standard', 'tier_complex',
    'badge_approved', 'badge_rejected',
    'ai_process',
  ];

  for (const key of requiredComposeKeys) {
    it(`fr/compose.json has "${key}"`, () => {
      expect((frCompose as Record<string, string>)[key]).toBeTruthy();
    });
  }

  const requiredDraftsKeys = [
    'regenerate', 'approved', 'rejected', 'ai_process',
  ];

  for (const key of requiredDraftsKeys) {
    it(`fr/drafts.json has "${key}"`, () => {
      expect((frDrafts as unknown as Record<string, string>)[key]).toBeTruthy();
    });
  }

  // Cross-locale consistency: all locales must have the same keys
  const criticalKeys = ['ai_process', 'regenerate', 'approved', 'rejected'];
  const allDrafts = [
    { name: 'en', data: enDrafts },
    { name: 'es', data: esDrafts },
  ];

  for (const locale of allDrafts) {
    for (const key of criticalKeys) {
      it(`${locale.name}/drafts.json has "${key}"`, () => {
        expect((locale.data as unknown as Record<string, string>)[key]).toBeTruthy();
      });
    }
  }
});
