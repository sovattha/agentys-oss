// Refcounted owner of `document.body.dataset.modalOpen`.
//
// Multiple independent components (App-level modals, shadcn DialogContent,
// Calendar QuickEventPopover, …) need to mark the keyboard as "owned" so
// global shortcuts (Del, E, N, R, U) defer. The previous capture-prev /
// restore-prev pattern raced when two writers' lifecycles overlapped: one
// could restore a stale 'true' after the other had already cleared the flag,
// leaving Del/E/N silently broken until the next full reload.
//
// A simple counter is race-proof: every push increments, every pop
// decrements, the dataset attribute reflects (count > 0).
//
// HMR durability (2026-05-13 fix): the counter is parked on `window` rather
// than module-scope. Vite HMR replaces this module on edit, which would
// reset a module-level counter to 0 mid-flight — push/pop balance survives
// HMR but readers see a stuck `data-modal-open='true'` because nothing
// re-derives the attribute from the freshly-zero count. Storing on `window`
// keeps the counter the same instance across HMR reloads and any other
// module-replacement scenario (Tauri's WebView lifecycle, lazy chunks…).

const COUNT_KEY = '__agentysModalOpenCount';

interface WindowWithModalCount extends Window {
  [COUNT_KEY]?: number;
}

function getCount(): number {
  return (window as WindowWithModalCount)[COUNT_KEY] ?? 0;
}

function setCount(n: number): void {
  (window as WindowWithModalCount)[COUNT_KEY] = n;
}

export function pushModalOpen(): void {
  setCount(getCount() + 1);
  document.body.dataset.modalOpen = 'true';
}

export function popModalOpen(): void {
  const next = Math.max(0, getCount() - 1);
  setCount(next);
  if (next === 0) delete document.body.dataset.modalOpen;
}

/**
 * Hard reset — clears both the counter and the dataset attribute. Exposed
 * for App.tsx's mount-time self-heal: if a prior session left the
 * attribute stuck while no modal is currently open, calling this from
 * the App's mount effect restores a sane baseline. Also handy from the
 * devtools console when debugging: `__agentysResetModalOpen()`.
 */
export function resetModalOpen(): void {
  setCount(0);
  delete document.body.dataset.modalOpen;
}

if (typeof window !== 'undefined') {
  (window as WindowWithModalCount & { __agentysResetModalOpen?: () => void })
    .__agentysResetModalOpen = resetModalOpen;
}
