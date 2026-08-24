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

import { describe, it, expect } from 'vitest'
import wsSource from './websocket.ts?raw'
import hookSource from '../hooks/useLearningProgress.ts?raw'

// Regression guard for the bug fixed in commit 9e0bc11a:
// `onboarding:waiting_for_sync` was emitted by the backend but not
// registered as a `socket.on(...)` listener in websocket.ts, so the event
// was silently dropped and the UI froze at "Loading... 0%".
//
// This test asserts that every event type the `useLearningProgress` hook
// handles ALSO has a matching registration in the `onboardingEvents`
// array of websocket.ts. A handler without a listener = silent drop.
//
// Cf. tasks/lessons.md — "[Architecture] Un handler d'événement sans
// socket.on(...) est un event-name qui n'existe pas".

function extractOnboardingListeners(wsSource: string): Set<string> {
  // Match the `onboardingEvents = [ ... ]` block.
  const block = wsSource.match(/const onboardingEvents\s*=\s*\[([\s\S]*?)\]\s*as const/)
  if (!block) throw new Error('Could not find onboardingEvents array in websocket.ts')
  const listeners = new Set<string>()
  for (const m of block[1].matchAll(/['"](onboarding:[a-z_]+)['"]/g)) {
    listeners.add(m[1])
  }
  return listeners
}

function extractHandledEventTypes(hookSource: string): Set<string> {
  // Match `eventType === 'onboarding:XXX'` conditions in the handler chain.
  const handled = new Set<string>()
  for (const m of hookSource.matchAll(/eventType === ['"](onboarding:[a-z_]+)['"]/g)) {
    handled.add(m[1])
  }
  return handled
}

describe('WebSocket listener ↔ handler contract', () => {
  it('every onboarding event handled in useLearningProgress is registered as a socket.on listener', () => {
    const listeners = extractOnboardingListeners(wsSource)
    const handlers = extractHandledEventTypes(hookSource)

    // Every handler branch must have a corresponding socket.on registration —
    // otherwise the backend emit never reaches the hook handler.
    const orphanHandlers: string[] = []
    for (const eventName of handlers) {
      if (!listeners.has(eventName)) orphanHandlers.push(eventName)
    }

    expect(
      orphanHandlers,
      `Handlers without socket.on listener (silent drop): ${orphanHandlers.join(', ')}\n` +
      `Add them to the onboardingEvents array in services/websocket.ts.`,
    ).toEqual([])
  })

  it('no dead onboarding listeners (every registered socket.on has a handler)', () => {
    const listeners = extractOnboardingListeners(wsSource)
    const handlers = extractHandledEventTypes(hookSource)

    const deadListeners: string[] = []
    for (const eventName of listeners) {
      // learning_started is read in the handler (eventType check) — allow
      // listeners that funnel payload via generic notifyHandlers without
      // a dedicated eventType branch, as long as they're used by SOME
      // subscriber. For now the hook handles all of them, so any registered
      // listener without a matching handler is dead code.
      if (!handlers.has(eventName)) deadListeners.push(eventName)
    }

    expect(
      deadListeners,
      `Dead listeners (registered but no handler): ${deadListeners.join(', ')}\n` +
      `Either add a handler in useLearningProgress.ts or remove from onboardingEvents.`,
    ).toEqual([])
  })
})
