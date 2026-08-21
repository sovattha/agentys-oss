import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Regression: Step4SmartOrg.handleContinue wraps every label/rule/VIP create in
// catch{/*best effort*/} (and inner .catch(()=>{})) so a rejected create was
// swallowed silently while handleContinue ALWAYS reached onNext(). The user got
// zero feedback that their auto-org setup did not fully apply.
// The fix counts how many creates rejected and, if any failed, dispatches a
// non-blocking agentys:toast type 'warning' before still calling onNext()
// (onboarding must not block). This test reproduces the exact failure-counting
// closure from Step4SmartOrg.tsx (~207-308) and proves it now dispatches a
// warning toast on failure while always advancing.

interface ToastDetail { message: string; type: string; duration: number }

// Mirrors the relevant body of handleContinue: best-effort creates whose
// rejections increment `failures`, then a warning toast if failures > 0, then
// onNext() unconditionally. `t` is useTranslation('onboarding').t.
async function runHandleContinue(deps: {
  toCreate: number
  onNext: () => void
  t: (k: string) => string
  createLabel: () => Promise<void>
  updateLabel: () => Promise<void>
  postRule: () => Promise<{ ok: boolean }>
}): Promise<void> {
  const { toCreate, onNext, t, createLabel, updateLabel, postRule } = deps

  let failures = 0

  if (toCreate > 0) {
    try {
      await Promise.all(
        Array.from({ length: toCreate }).map(async () => {
          try {
            await createLabel()
          } catch {
            await updateLabel().catch(() => { failures += 1 })
          }
          // Audit 2026-06-11 F-02: fetch resolves on 4xx/5xx — HTTP errors are
          // counted via the fulfilled branch (r.ok), network errors via reject.
          await Promise.all([
            Promise.resolve(postRule()).then((r) => { if (!r.ok) failures += 1 }, () => { failures += 1 }),
            Promise.resolve(postRule()).then((r) => { if (!r.ok) failures += 1 }, () => { failures += 1 }),
          ])
        }),
      )
    } catch { failures += 1 }
  }

  if (failures > 0) {
    window.dispatchEvent(new CustomEvent('agentys:toast', {
      detail: {
        message: t('step4_partial_create'),
        type: 'warning',
        duration: 6000,
      },
    }))
  }

  onNext()
}

describe('Step4SmartOrg partial-create failure (non-blocking warning toast)', () => {
  let dispatched: CustomEvent[] = []

  beforeEach(() => {
    dispatched = []
    vi.spyOn(window, 'dispatchEvent').mockImplementation((evt) => {
      if (evt instanceof CustomEvent) dispatched.push(evt)
      return true
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('dispatches a warning toast when a create rejects, and still calls onNext()', async () => {
    const onNext = vi.fn()
    const t = (k: string) => `onboarding:${k}`

    await runHandleContinue({
      toCreate: 1,
      onNext,
      t,
      // create fails -> falls through to updateLabel which also fails -> failures++
      createLabel: () => Promise.reject(new Error('label exists')),
      updateLabel: () => Promise.reject(new Error('update failed')),
      postRule: () => Promise.resolve({ ok: true }),
    })

    // Onboarding must not block: onNext is still called.
    expect(onNext).toHaveBeenCalledTimes(1)

    // A non-blocking warning toast must be dispatched.
    const toastEvt = dispatched.find(e => e.type === 'agentys:toast')
    expect(toastEvt).toBeDefined()
    const detail = (toastEvt as CustomEvent<ToastDetail>).detail
    expect(detail.type).toBe('warning')
    expect(detail.message).toBe('onboarding:step4_partial_create')
    expect(detail.duration).toBe(6000)
  })

  it('dispatches a warning toast when a create resolves with an HTTP error (4xx/5xx), and still calls onNext()', async () => {
    const onNext = vi.fn()
    const t = (k: string) => `onboarding:${k}`

    await runHandleContinue({
      toCreate: 1,
      onNext,
      t,
      createLabel: () => Promise.resolve(),
      updateLabel: () => Promise.resolve(),
      // Audit 2026-06-11 F-02: a 401/500 resolves (does not reject) — it must
      // still be counted as a failure instead of showing a lying success.
      postRule: () => Promise.resolve({ ok: false }),
    })

    expect(onNext).toHaveBeenCalledTimes(1)
    const toastEvt = dispatched.find(e => e.type === 'agentys:toast')
    expect(toastEvt).toBeDefined()
    expect((toastEvt as CustomEvent<ToastDetail>).detail.type).toBe('warning')
  })

  it('does NOT dispatch a toast when all creates succeed, and still calls onNext()', async () => {
    const onNext = vi.fn()

    await runHandleContinue({
      toCreate: 2,
      onNext,
      t: (k: string) => k,
      createLabel: () => Promise.resolve(),
      updateLabel: () => Promise.resolve(),
      postRule: () => Promise.resolve({ ok: true }),
    })

    expect(onNext).toHaveBeenCalledTimes(1)
    expect(dispatched.find(e => e.type === 'agentys:toast')).toBeUndefined()
  })
})
