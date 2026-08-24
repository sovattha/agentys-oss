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

import { describe, expect, it } from 'vitest'
import appSource from '../App.tsx?raw'
import specialtiesSource from '../services/specialties.ts?raw'
import bookingUrlSource from '../hooks/useBookingUrlSetting.ts?raw'
import batchScheduleSource from '../hooks/useBatchScheduleSetting.ts?raw'
import deepWorkSource from '../hooks/useDeepWorkSetting.ts?raw'
import themeSource from '../hooks/useTheme.ts?raw'
import uiSoundsSource from '../hooks/useUISounds.ts?raw'
import autoReplySource from '../hooks/useAutoReplySetting.ts?raw'
import createSettingHookSource from '../hooks/createSettingHook.ts?raw'

type SettingsPatchBlock = {
  block: string
  before: string
}

function settingsPatchBlocks(source: string): SettingsPatchBlock[] {
  const blocks: SettingsPatchBlock[] = []
  const settingsFetch = /fetch\(\s*`[^`]*\/settings`/g
  let match: RegExpExecArray | null

  while ((match = settingsFetch.exec(source)) !== null) {
    const block = source.slice(match.index, match.index + 900)
    if (/method:\s*["']PATCH["']/.test(block)) {
      blocks.push({
        block,
        before: source.slice(Math.max(0, match.index - 350), match.index),
      })
    }
  }

  return blocks
}

function hasAuthHeaders({ block, before }: SettingsPatchBlock): boolean {
  if (/getAuthHeaders\(\)|authJson\(\)/.test(block)) {
    return true
  }

  return /headers\s*,/.test(block) && /getAuthHeaders\(\)|authJson\(\)/.test(before)
}

describe('settings PATCH auth contract', () => {
  it('settings hooks send Authorization headers on PATCH', () => {
    const sources = {
      'App.tsx': appSource,
      'services/specialties.ts': specialtiesSource,
      'useBookingUrlSetting.ts': bookingUrlSource,
      'useBatchScheduleSetting.ts': batchScheduleSource,
      'useDeepWorkSetting.ts': deepWorkSource,
      'useTheme.ts': themeSource,
      'useUISounds.ts': uiSoundsSource,
      'useAutoReplySetting.ts': autoReplySource,
      'createSettingHook.ts': createSettingHookSource,
    }

    const offenders: string[] = []
    for (const [name, source] of Object.entries(sources)) {
      const blocks = settingsPatchBlocks(source)
      blocks.forEach((block, index) => {
        if (!hasAuthHeaders(block)) {
          offenders.push(`${name}#${index + 1}`)
        }
      })
    }

    expect(offenders).toEqual([])
  })
})
