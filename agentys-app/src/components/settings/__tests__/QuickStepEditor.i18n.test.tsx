/**
 * QuickStepEditor — seeded-rule i18n overlay (audit 2026-05-21).
 *
 * Seeded starter rules (app/quicksteps/defaults.py) are stored under their
 * canonical ENGLISH name + description. That English name is ALSO the matching
 * key for the Settings discovery surface (Settings.tsx) and the deterministic
 * uuid5 seed id, so a save that didn't touch the name must never rewrite it.
 *
 * These tests pin two behaviours:
 *   1. the editor DISPLAYS the locale-aware (FR) name/description — the card
 *      already overlays it, the editor used to leak raw English;
 *   2. saving WITHOUT editing the name preserves the canonical English name,
 *      and editing it persists the user's value.
 */
import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// FR copy for the seeded rule under test (mirrors locales/fr/settings.json).
const FR_SEEDED: Record<string, string> = {
  quicksteps_seeded_archive_info_emails_once_read_name: 'Archiver les infos lues',
  quicksteps_seeded_archive_info_emails_once_read_desc:
    'Une fois un message étiqueté Info ouvert, archive-le automatiquement — la boîte ne garde que les éléments actionnables.',
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) =>
      FR_SEEDED[key] ?? opts?.defaultValue ?? key,
    i18n: { language: 'fr', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => undefined },
}))

// ConditionsSection fetches labels on mount; keep the editor offline.
vi.mock('../../../api/labels', () => ({ fetchLabels: () => Promise.resolve({ labels: [] }) }))
vi.mock('../../../hooks/useContactGroups', () => ({ useContactGroups: () => ({ groups: [] }) }))

import { QuickStepEditor } from '../QuickStepsManager'
import { normalizeQuickStep } from '../../../types/quickStep'

const EN_NAME = 'Archive info emails once read'
const EN_DESC =
  "Once you've read a message labelled Info, archive it automatically — keeps the inbox to actionable items only."

function seededDraft() {
  return normalizeQuickStep({
    id: '11111111-1111-1111-1111-111111111111',
    name: EN_NAME,
    description: EN_DESC,
    triggers: [{ type: 'is_read', value: 'true' }],
    actions: [{ type: 'archive', payload: {} }],
    firesOn: 'received',
  } as Parameters<typeof normalizeQuickStep>[0])
}

function renderEditor(onSave = vi.fn()) {
  const utils = render(
    <QuickStepEditor draft={seededDraft()} siblings={[]} onCancel={vi.fn()} onSave={onSave} />,
  )
  return { onSave, ...utils }
}

describe('QuickStepEditor — seeded-rule locale overlay', () => {
  it('shows the localized (FR) name and description, not the raw English store', () => {
    renderEditor()
    expect(screen.getByDisplayValue('Archiver les infos lues')).toBeInTheDocument()
    expect(screen.getByDisplayValue(/Une fois un message étiqueté Info ouvert/)).toBeInTheDocument()
    // The raw English string must NOT be what the user sees.
    expect(screen.queryByDisplayValue(EN_NAME)).not.toBeInTheDocument()
  })

  it('preserves the canonical English name when saved without editing it', async () => {
    const { onSave, container } = renderEditor()
    fireEvent.submit(container.querySelector('form')!)
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave.mock.calls[0][0].name).toBe(EN_NAME)
  })

  it('persists the user value once the name is actually edited', async () => {
    const { onSave, container } = renderEditor()
    fireEvent.change(screen.getByDisplayValue('Archiver les infos lues'), {
      target: { value: 'Mon archivage' },
    })
    fireEvent.submit(container.querySelector('form')!)
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave.mock.calls[0][0].name).toBe('Mon archivage')
  })
})
