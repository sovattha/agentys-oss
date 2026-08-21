import { render, act } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { useRef, useEffect } from 'react';
import { useFocusTrap } from '../hooks/useFocusTrap';

/**
 * Regression test for the ImageAnnotator text-input bug.
 *
 * Bug: ImageAnnotator portals to document.body and its text input gets focus
 * stolen by any parent modal's useFocusTrap (EmailDetailModal, NewMessageModal),
 * triggering onBlur → commitText which clears the pending text state before
 * a single keystroke can land.
 *
 * Fix: Add role="dialog" to the annotator overlay — useFocusTrap opt-outs on
 * that selector (see useFocusTrap.ts:73 handleFocusIn).
 *
 * This test sets up a focus-trapped container and a sibling dialog (simulating
 * the portal). useFocusTrap gates on `container.contains(target)`, so a sibling
 * behaves the same as a portal for the focus-stealing logic.
 */

function TrappedContainer() {
  const trapRef = useFocusTrap(true);
  return (
    <div ref={trapRef} data-testid="trap">
      <button data-testid="trap-button">Inside trap</button>
    </div>
  );
}

function Dialog({
  role,
  onInputBlur,
}: {
  role?: string;
  onInputBlur: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    requestAnimationFrame(() => inputRef.current?.focus());
  }, []);
  return (
    <div role={role} aria-modal={role === 'dialog' ? 'true' : undefined} data-testid="dialog">
      <input ref={inputRef} data-testid="dialog-input" onBlur={onInputBlur} />
    </div>
  );
}

function Harness({ role, onInputBlur }: { role?: string; onInputBlur: () => void }) {
  return (
    <div>
      <TrappedContainer />
      <Dialog role={role} onInputBlur={onInputBlur} />
    </div>
  );
}

async function flushRaf() {
  await act(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => resolve());
        });
      })
  );
}

describe('useFocusTrap opt-out for ImageAnnotator (role="dialog")', () => {
  it('steals focus from a sibling without role="dialog" (reproduces the bug)', async () => {
    let blurCount = 0;
    render(<Harness onInputBlur={() => blurCount++} />);
    await flushRaf();

    const input = document.querySelector<HTMLInputElement>('[data-testid="dialog-input"]');
    expect(input).not.toBeNull();
    // Focus trap yanked focus back → input blurred at least once
    expect(document.activeElement).not.toBe(input);
    expect(blurCount).toBeGreaterThan(0);
  });

  it('leaves focus alone when sibling has role="dialog" (verifies the fix)', async () => {
    let blurCount = 0;
    render(<Harness role="dialog" onInputBlur={() => blurCount++} />);
    await flushRaf();

    const input = document.querySelector<HTMLInputElement>('[data-testid="dialog-input"]');
    expect(input).not.toBeNull();
    expect(document.activeElement).toBe(input);
    expect(blurCount).toBe(0);
  });
});
