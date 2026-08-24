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

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { createPortal } from 'react-dom'
import { apiClient } from '../../services/api'
import type { ContactGroup } from '../../hooks/useContactGroups'
import { copyToClipboard } from '../../utils/clipboard'
import { CloseIcon, CheckIcon } from '../icons/ActionIcons'
import { generateColorFromString, getInitials } from '../Avatar'
import './ContactAutocomplete.css'

export interface Contact {
  name: string
  email: string
}

interface GroupSuggestion {
  type: 'group'
  group: ContactGroup
}

type SuggestionEntry = Contact | GroupSuggestion

function isGroupSuggestion(s: SuggestionEntry): s is GroupSuggestion {
  return 'type' in s && s.type === 'group'
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const SUGGESTIONS_MAX_HEIGHT = 280
const SUGGESTIONS_MIN_HEIGHT = 96

/** Highlight matching substring in text */
function highlightMatch(text: string, query: string) {
  if (!query || query.length < 1) return text
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx === -1) return text
  return (
    <>
      {text.slice(0, idx)}
      <strong className="contact-match">{text.slice(idx, idx + query.length)}</strong>
      {text.slice(idx + query.length)}
    </>
  )
}

interface ContactAutocompleteProps {
  value: string
  onChange: (value: string) => void
  contacts?: Contact[]
  contactGroups?: ContactGroup[]
  accountId?: string
  disabled?: boolean
  placeholder?: string
  className?: string
  inputRef?: React.RefObject<HTMLInputElement | null>
  autoFocus?: boolean
  onGroupUsed?: (groupId: string) => void
  /** Enable multi-chip mode (Gmail-style tags) — default true */
  multi?: boolean
  /** Field identifier for drag-and-drop between fields */
  fieldId?: 'to' | 'cc' | 'bcc'
  /** Called when user starts dragging a chip out of this field */
  onChipDragStart?: (email: string, fieldId: string) => void
  /** Called when drag ends (drop or cancel) */
  onChipDragEnd?: () => void
  /** True when a cross-field drag is in progress (highlights this field as drop zone) */
  isDragActive?: boolean
  /** Called when user clicks the hide button on a suggestion */
  onHideContact?: (email: string) => void
  /** Called with full contact info when a suggestion is selected (single mode) */
  onContactSelect?: (contact: { name: string; email: string }) => void
  /** Opt out of sent_only filter — include senders as well as recipients.
   *  Default: suggestions are limited to people the user has actually emailed
   *  (cleaner, less spam). Set to true for cases like per-contact style rules
   *  where senders are valid targets. */
  includeAllContacts?: boolean
  /** Include the user's OTHER multi-account emails in suggestions.
   *  Default: false — compose recipient pickers don't suggest self-sends.
   *  Set to true for pickers where forwarding/sending to one's own other
   *  account is a normal intent: auto-reply forward address, Quick Step
   *  forward action recipient, calendar attendees, contact-group members,
   *  per-contact style rules. The active account's own email is ALWAYS
   *  stripped regardless of this flag. */
  includeSelf?: boolean
}

function searchContactsLocal(query: string, contacts: Contact[]): Contact[] {
  if (!query.trim()) {
    return []
  }

  const lowerQuery = query.toLowerCase()
  return contacts
    .filter(
      (c) =>
        c.name.toLowerCase().includes(lowerQuery) ||
        c.email.toLowerCase().includes(lowerQuery)
    )
    .slice(0, 10)
}

/** Parse comma-separated value into chip entries */
function parseChips(value: string): string[] {
  return value
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
}

/** Get display label for an email (name part or local part) */
function getChipLabel(email: string): string {
  // "Name <email>" format
  const match = email.match(/^(.+?)\s*<(.+?)>$/)
  if (match) return match[1].trim()
  // Plain email — show local part capitalized
  const local = email.split('@')[0]
  if (!local) return email
  return local.charAt(0).toUpperCase() + local.slice(1)
}

// Initiales : déléguées au canon getInitials (Avatar.tsx) — règle unique
// app-wide « toujours 2 lettres comme AS » (2026-06-09).

/** Extract the raw email address from a chip entry */
function getChipEmail(chip: string): string {
  const match = chip.match(/^.+?\s*<(.+?)>$/)
  return match ? match[1] : chip
}

export function ContactAutocomplete({
  value,
  onChange,
  contacts,
  contactGroups,
  accountId,
  disabled = false,
  placeholder = 'email@example.com',
  className,
  inputRef: externalRef,
  autoFocus,
  onGroupUsed,
  multi = true,
  fieldId,
  onChipDragStart,
  onChipDragEnd,
  onHideContact,
  onContactSelect,
  includeAllContacts = false,
  includeSelf = false,
}: ContactAutocompleteProps) {
  const { t } = useTranslation('common')
  // In multi mode, chips are the confirmed entries; query is what user is typing
  const chips = useMemo(() => multi ? parseChips(value) : [], [value, multi])
  // QA 2026-06-10: chips seeded programmatically (reply prefill, drafts) are
  // often bare addresses. Without a name lookup the chip rendered a
  // capitalized local-part ("Nathansok") while the rest of the UI shows the
  // contact's real name ("Nathan Roy"). Bump this counter whenever the
  // async resolver below fills nameMapRef so the chips re-render.
  const [, setNameMapVersion] = useState(0)
  const resolvedChipAddrsRef = useRef<Set<string>>(new Set())
  const [query, setQuery] = useState(multi ? '' : value)
  const [suggestions, setSuggestions] = useState<SuggestionEntry[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null)
  const internalRef = useRef<HTMLInputElement>(null)
  const inputRef = externalRef || internalRef
  const listRef = useRef<HTMLUListElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isFocusedRef = useRef(false)
  const suppressNextFocusRef = useRef(false)
  const searchSeqRef = useRef(0)
  // Map email→name from API results for chip display
  const nameMapRef = useRef<Record<string, string>>({})
  // Index of the chip being hovered during same-field reorder drag
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  // Email being dragged within this field (for same-field reorder)
  const localDragEmailRef = useRef<string | null>(null)
  // Chip email popover state
  const [activeChipPopover, setActiveChipPopover] = useState(-1)
  const [chipCopied, setChipCopied] = useState(false)
  const mouseDownPosRef = useRef<{ x: number; y: number } | null>(null)
  // Audit 2026-06-11 U-03 : entrée invalide (Enter/Tab/blur) refusée sans
  // aucun feedback — l'utilisateur voyait juste un bouton Send grisé.
  const [invalidEntry, setInvalidEntry] = useState<string | null>(null)

  // Single mode: sync inputValue from parent
  useEffect(() => {
    if (!multi) {
      setQuery(value)
    }
  }, [value, multi])

  // QA 2026-06-10: resolve display names for bare-address chips. nameMapRef
  // was only populated while the user typed (search results), so chips seeded
  // programmatically (reply prefill) never got a name. One contacts lookup
  // per unique address, deduped for the component's lifetime.
  useEffect(() => {
    if (!multi || chips.length === 0) return
    const pending = chips
      .filter(chip => !chip.includes('<')) // "Name <addr>" chips already carry a name
      .map(chip => getChipEmail(chip).trim().toLowerCase())
      .filter(addr =>
        addr.includes('@') &&
        !nameMapRef.current[addr] &&
        !resolvedChipAddrsRef.current.has(addr)
      )
    if (pending.length === 0) return
    pending.forEach(addr => resolvedChipAddrsRef.current.add(addr))
    let cancelled = false
    void (async () => {
      for (const addr of pending) {
        try {
          const results = await apiClient.searchContacts(addr, accountId, {
            sentOnly: false,
            includeSelf: true,
          })
          const hit = results.find(
            (r) => !isGroupSuggestion(r) && r.email?.toLowerCase() === addr && r.name,
          )
          if (hit && !cancelled) {
            nameMapRef.current[addr] = hit.name
            setNameMapVersion(v => v + 1)
          }
        } catch {
          // Lookup failed — chip keeps the local-part fallback label.
        }
      }
    })()
    return () => { cancelled = true }
  }, [multi, chips, accountId])

  // P3-22 (2026-05-17): NewMessageModal dispatches this event when the user
  // toggles Cc/Bcc — close any open suggestion popover synchronously so it
  // can't briefly overlap the Subject row while the layout reflows. Listening
  // here (rather than passing a controlled-open prop) keeps the change
  // contained to the two components touched by the bug.
  useEffect(() => {
    const close = () => setIsOpen(false)
    window.addEventListener('agentys:close-contact-suggestions', close)
    return () => window.removeEventListener('agentys:close-contact-suggestions', close)
  }, [])

  // Close in capture phase before an outside click can hit an overlapping
  // portal suggestion. This keeps toolbar/AI buttons clickable even when the
  // contact menu is open.
  useEffect(() => {
    if (!isOpen) return

    const handlePointerDown = (e: PointerEvent | MouseEvent) => {
      const target = e.target as Node | null
      if (!target) return
      if (containerRef.current?.contains(target)) return
      if (listRef.current?.contains(target)) return
      setIsOpen(false)
    }

    document.addEventListener('pointerdown', handlePointerDown, { capture: true })
    document.addEventListener('mousedown', handlePointerDown, { capture: true })
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, { capture: true })
      document.removeEventListener('mousedown', handlePointerDown, { capture: true })
    }
  }, [isOpen])

  /** Compute dropdown position synchronously — avoids 1-frame gap where isOpen=true but pos=null */
  const updateDropdownPos = useCallback(() => {
    if (!containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const root = containerRef.current.closest('.new-message-modal, .reply-composer, .pending-draft-detail')
    const footer = root?.querySelector<HTMLElement>('.gmail-footer, .rc-action-bar')
    const viewportBottom = window.innerHeight - 8
    const footerTop = footer?.getBoundingClientRect().top
    const bottomLimit = typeof footerTop === 'number' ? Math.min(viewportBottom, footerTop - 8) : viewportBottom
    const maxHeight = Math.max(
      SUGGESTIONS_MIN_HEIGHT,
      Math.min(SUGGESTIONS_MAX_HEIGHT, bottomLimit - rect.bottom - 2),
    )
    setDropdownPos({ top: rect.bottom + 2, left: rect.left, width: rect.width, maxHeight })
  }, [])

  const searchAPI = useCallback(async (q: string) => {
    const seq = ++searchSeqRef.current
    try {
      // sent_only=true par défaut → suggestions basées uniquement sur les gens à qui l'utilisateur
      // a écrit (exclut spam, senders non-réciproques, automated). Appliqué partout : compose,
      // reply, calendar, onboarding, deep work. Opt-out via prop `includeAllContacts` pour les
      // cas où on veut aussi les senders (ex : ContactStyleEditor, règles par contact).
      const results = await apiClient.searchContacts(q, accountId, {
        sentOnly: !includeAllContacts,
        includeSelf,
      })
      // Ignore stale responses (newer search already fired)
      if (seq !== searchSeqRef.current) return
      // Cache name mappings
      for (const r of results) {
        if (!isGroupSuggestion(r) && r.name) {
          nameMapRef.current[r.email.toLowerCase()] = r.name
        }
      }
      // If query is a valid email not already in results, add a synthetic
      // "use this address" suggestion so the user can click it instead of
      // having to press Enter manually.
      const finalResults: SuggestionEntry[] = [...results]
      const qLower = q.trim().toLowerCase()
      if (
        EMAIL_RE.test(qLower) &&
        !results.some((r) => !isGroupSuggestion(r) && r.email.toLowerCase() === qLower)
      ) {
        finalResults.push({ name: q.trim(), email: q.trim() })
      }
      // Don't gate on isFocusedRef — if the user typed enough chars to trigger the API,
      // the input was focused. Gating here caused dropdowns to silently swallow when
      // a transient blur/focus race happened during the 300ms debounce window.
      setSuggestions(finalResults)
      updateDropdownPos()
      // Always open the dropdown when a search runs — closes the F-07
      // audit follow-up. Previously hid entirely when both query and
      // results were empty (handleFocus + zero contacts in DB), leaving
      // users guessing whether autocomplete was even wired up. The empty
      // <li>{no_contact_found}</li> branch in the JSX now gives a clear
      // signal in that case.
      setIsOpen(true)
      setHighlightedIndex(-1)
    } catch (_err) {
      if (seq !== searchSeqRef.current) return
      // F-07 audit follow-up: surface the failure via the same empty-state
      // row instead of silently closing the dropdown. Log for ops.
      console.warn('[ContactAutocomplete] suggest call failed:', _err)
      setSuggestions([])
      updateDropdownPos()
      setIsOpen(true)
    }
  }, [accountId, includeAllContacts, includeSelf, updateDropdownPos])

  /** Add one or more emails as chips. Drops anything that doesn't match
   *  EMAIL_RE — keeps the query in place so the user can fix their input
   *  instead of losing it silently. */
  const addChips = useCallback((emails: string[]) => {
    const existing = new Set(chips.map(c => c.toLowerCase()))
    const trimmed = emails.map(e => e.trim()).filter(Boolean)
    const newEmails = trimmed.filter(e => !existing.has(e.toLowerCase()) && EMAIL_RE.test(e))
    if (newEmails.length === 0) {
      // Nothing was added — either all dupes or all invalid. Don't clear the
      // user's typed query; that way an invalid entry stays visible so they
      // can see what's wrong and edit it. U-03 : on l'explique aussi.
      const firstInvalid = trimmed.find(e => !EMAIL_RE.test(e))
      if (firstInvalid) setInvalidEntry(firstInvalid)
      return
    }
    setInvalidEntry(null)
    const updated = [...chips, ...newEmails]
    onChange(updated.join(', '))
    setQuery('')
    setSuggestions([])
    setIsOpen(false)
  }, [chips, onChange])

  /** Remove a chip by index */
  const removeChip = useCallback((index: number) => {
    const updated = chips.filter((_, i) => i !== index)
    onChange(updated.join(', '))
    setActiveChipPopover(-1)
  }, [chips, onChange])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value
    // If user is typing, the input is focused — fix stale ref from blur flicker
    isFocusedRef.current = true
    // U-03 : l'utilisateur corrige sa saisie — retirer le hint d'invalidité
    if (invalidEntry) setInvalidEntry(null)
    if (!multi) {
      // Single mode — original behavior
      setQuery(newValue)
      onChange(newValue)
    } else {
      // Multi mode — check for comma/semicolon to confirm chip
      if (newValue.includes(',') || newValue.includes(';')) {
        const parts = newValue.split(/[,;]/).map(s => s.trim()).filter(Boolean)
        if (parts.length > 0) {
          addChips(parts)
          return
        }
      }
      setQuery(newValue)
    }

    // Detect @prefix for group filtering
    const searchStr = multi ? newValue : newValue
    if (searchStr.startsWith('@') && contactGroups && contactGroups.length > 0) {
      const q = searchStr.slice(1).toLowerCase()
      const matched = contactGroups
        .filter(g => g.name.toLowerCase().includes(q))
        .slice(0, 8)
        .map(g => ({ type: 'group' as const, group: g }))

      // Synthesize "Tous" virtual groups for project labels with 2+ sub-groups
      const virtualEntries: GroupSuggestion[] = []
      if (q) {
        const byLabel = new Map<string, typeof contactGroups>()
        for (const g of contactGroups) {
          if (g.label_name) {
            const arr = byLabel.get(g.label_name) || []
            arr.push(g)
            byLabel.set(g.label_name, arr)
          }
        }
        for (const [labelName, labelGroups] of byLabel) {
          if (labelGroups.length < 2) continue
          if (!labelName.toLowerCase().includes(q)) continue
          // Already showing individual sub-groups — add "Tous" at the top
          const seen = new Set<string>()
          const allMembers = labelGroups.flatMap(g => g.members).filter(m => {
            const key = m.email.toLowerCase()
            if (seen.has(key)) return false
            seen.add(key)
            return true
          })
          if (allMembers.length === 0) continue
          virtualEntries.push({
            type: 'group',
            group: {
              id: `virtual_tous_${labelName}`,
              name: `${labelName} — Tous`,
              emoji: '👥',
              description: null,
              label_name: labelName,
              members: allMembers,
              created_at: '',
              updated_at: '',
              use_count: 0,
            },
          })
        }
      }

      const all = [...virtualEntries, ...matched].slice(0, 10)
      setSuggestions(all)
      updateDropdownPos()
      setIsOpen(all.length > 0)
      setHighlightedIndex(-1)
      return
    }

    // Local search if contacts provided
    if (contacts && !accountId) {
      const matches = searchContactsLocal(searchStr, contacts)
      setSuggestions(matches)
      updateDropdownPos()
      setIsOpen(searchStr.trim().length > 0)
      setHighlightedIndex(-1)
      return
    }

    // API-based search (debounced)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      searchAPI(searchStr)
    }, 300)
  }

  const handleSelectEntry = (entry: SuggestionEntry) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    suppressNextFocusRef.current = true

    if (multi) {
      if (isGroupSuggestion(entry)) {
        const emails = entry.group.members.map(m => m.email)
        addChips(emails)
        onGroupUsed?.(entry.group.id)
        // Report each member so parents tracking {name, email} can enrich names
        for (const m of entry.group.members) {
          onContactSelect?.({ name: m.name || '', email: m.email })
        }
      } else {
        addChips([entry.email])
        onContactSelect?.({ name: entry.name || '', email: entry.email })
      }
    } else {
      // Single mode — original behavior
      if (isGroupSuggestion(entry)) {
        const emails = entry.group.members.map(m => m.email).join(', ')
        setQuery(emails)
        onChange(emails)
        onGroupUsed?.(entry.group.id)
      } else {
        setQuery(entry.email)
        onChange(entry.email)
        onContactSelect?.({ name: entry.name || '', email: entry.email })
      }
      setSuggestions([])
      setIsOpen(false)
    }

    if (inputRef && 'current' in inputRef) {
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Single mode: Enter on non-empty query with no suggestion selected → submit raw value
    if (!multi && e.key === 'Enter' && query.trim() && highlightedIndex < 0) {
      const q = query.trim()
      // Was: `q.includes('@')` — accepted obvious non-emails like "@foo" or
      // "foo@". Require a proper user@host.tld shape via EMAIL_RE.
      if (EMAIL_RE.test(q) && onContactSelect) {
        e.preventDefault()
        onContactSelect({ name: '', email: q })
        setQuery('')
        onChange('')
        setSuggestions([])
        setIsOpen(false)
        return
      }
    }

    // Multi mode: Backspace on empty query removes last chip
    if (multi && e.key === 'Backspace' && !query && chips.length > 0) {
      removeChip(chips.length - 1)
      return
    }

    // Multi mode: Enter/Tab on non-empty query with no suggestion selected → confirm as chip
    if (multi && (e.key === 'Enter' || e.key === 'Tab') && query.trim() && highlightedIndex < 0) {
      e.preventDefault()
      const q = query.trim()
      if (q.startsWith('@') && contactGroups && contactGroups.length > 0) {
        const name = q.slice(1).toLowerCase()
        const group = contactGroups.find(g => g.name.toLowerCase() === name || g.name.toLowerCase().replace(/\s+/g, '') === name)
        if (group && group.members.length > 0) {
          addChips(group.members.map(m => m.email))
          onGroupUsed?.(group.id)
          return
        }
        // If @prefix but group not found, try first dropdown suggestion (if any)
        if (suggestions.length > 0 && isGroupSuggestion(suggestions[0])) {
          handleSelectEntry(suggestions[0])
          return
        }
      }
      addChips([q])
      return
    }

    if (!isOpen) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightedIndex((prev) =>
        prev < suggestions.length - 1 ? prev + 1 : prev
      )
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : prev))
    } else if (e.key === 'Enter' && highlightedIndex >= 0) {
      e.preventDefault()
      handleSelectEntry(suggestions[highlightedIndex])
    } else if (e.key === 'Escape') {
      // Only swallow Escape if the user actively navigated the suggestion list
      // (a row is highlighted). Otherwise let Escape bubble so the parent modal
      // closes in a single key press — the dropdown auto-reopens when the user
      // starts typing again, so closing it here costs nothing in that case.
      if (highlightedIndex >= 0) {
        e.stopPropagation()
      }
      setIsOpen(false)
    }
  }

  const handleBlur = () => {
    isFocusedRef.current = false
    if (debounceRef.current) clearTimeout(debounceRef.current)
    // Auto-confirm typed text as chip on blur — but NOT @group queries (those resolve via click/Enter)
    if (multi && query.trim() && !query.trim().startsWith('@')) {
      addChips([query.trim()])
    }
    setTimeout(() => {
      setIsOpen(false)
    }, 150)
  }

  const handleHideContact = useCallback((email: string) => {
    // Remove the hidden contact from current suggestions
    setSuggestions(prev => prev.filter(s => isGroupSuggestion(s) || s.email !== email))
    onHideContact?.(email)
  }, [onHideContact])

  const handleFocus = () => {
    isFocusedRef.current = true
    if (suppressNextFocusRef.current) {
      suppressNextFocusRef.current = false
      return
    }
    // Always search on focus — show top contacts if empty, matching contacts if query exists
    searchAPI(query.trim())
  }

  // Click on container focuses input; if already focused, open dropdown manually
  // (focus event doesn't re-fire when input is already focused, so searchAPI
  // is never called on subsequent clicks after adding the first chip)
  const handleContainerClick = () => {
    if (inputRef && 'current' in inputRef) {
      inputRef.current?.focus()
    }
    if (isFocusedRef.current) {
      searchAPI(query.trim())
    }
  }

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  // Dismiss chip email popover on outside click or Escape.
  // Capture-phase mousedown: a bubble-phase document listener never fires when
  // this field is mounted inside a modal that stops native mousedown
  // propagation (e.g. AutoReplyModal nested in the Settings modal). Capture
  // runs on the way down from document, before any parent stopPropagation.
  useEffect(() => {
    if (activeChipPopover < 0) return
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (!target.closest('.ca-chip-email-popover') && !target.closest('.ca-chip')) {
        setActiveChipPopover(-1)
      }
    }
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setActiveChipPopover(-1)
    }
    document.addEventListener('mousedown', handleClickOutside, { capture: true })
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside, { capture: true })
      document.removeEventListener('keydown', handleEscape)
    }
  }, [activeChipPopover])

  const getChipDisplayLabel = (email: string) => {
    // Key the cache by the bare address so both "addr" and "Name <addr>"
    // chips resolve (QA 2026-06-10 — chip showed "Nathansok" instead of
    // the contact's real name "Nathan Roy").
    const cached = nameMapRef.current[getChipEmail(email).trim().toLowerCase()]
      ?? nameMapRef.current[email.toLowerCase()]
    if (cached) return cached
    return getChipLabel(email)
  }

  return (
    <div
      ref={containerRef}
      className={`contact-autocomplete${multi ? ' multi' : ''}${className ? ' ' + className : ''}`}
      onClick={multi ? handleContainerClick : undefined}
    >
      {multi && chips.length > 0 && (
        <div className="ca-chips">
          {chips.map((chip, i) => (
            <span
              key={`${chip}-${i}`}
              className={`ca-chip${fieldId ? ' ca-chip-draggable' : ''}${dragOverIndex === i ? ' drag-insert-before' : ''}`}
              draggable={!!fieldId}
              title={fieldId
                ? t('compose:chip_drag_hint', {
                    email: chip,
                    defaultValue: `${chip} — drag to move between To / Cc / Cci`,
                  })
                : chip}
              onMouseDown={(e) => {
                mouseDownPosRef.current = { x: e.clientX, y: e.clientY }
              }}
              onMouseUp={(e) => {
                const start = mouseDownPosRef.current
                mouseDownPosRef.current = null
                if (!start) return
                if (Math.abs(e.clientX - start.x) < 3 && Math.abs(e.clientY - start.y) < 3) {
                  setActiveChipPopover(prev => prev === i ? -1 : i)
                  setChipCopied(false)
                }
              }}
              onDragStart={(e) => {
                setActiveChipPopover(-1)
                e.dataTransfer.effectAllowed = 'move'
                e.dataTransfer.setData('text/plain', chip)
                localDragEmailRef.current = chip
                onChipDragStart?.(chip, fieldId!)
              }}
              onDragEnd={() => {
                localDragEmailRef.current = null
                setDragOverIndex(null)
                onChipDragEnd?.()
              }}
              onDragOver={(e) => {
                e.preventDefault()
                // Only handle same-field reorder (cross-field drop handled by parent)
                if (localDragEmailRef.current && localDragEmailRef.current !== chip) {
                  setDragOverIndex(i)
                }
              }}
              onDragLeave={() => setDragOverIndex(null)}
              onDrop={(e) => {
                const draggedEmail = localDragEmailRef.current
                if (!draggedEmail) {
                  // Cross-field drop (e.g. a chip dragged from the To: row
                  // landed on a chip in the Cc: row). `localDragEmailRef` is
                  // per-ContactAutocomplete-instance and is only set on
                  // drag-start within THIS field, so a null here means the
                  // drag originated in a sibling field. Return WITHOUT
                  // preventDefault/stopPropagation so the event bubbles up
                  // to the parent `.gmail-field`'s onDrop, which calls
                  // `handleFieldDrop` and moves the chip across fields.
                  // Pre-fix, this branch called stopPropagation and silently
                  // ate the cross-field drop — the chip would "miss" the
                  // drop target whenever the cursor happened to land on
                  // another chip rather than the field's whitespace, which
                  // made drag-to-Cc/Bcc look broken.
                  return
                }
                e.preventDefault()
                e.stopPropagation()
                if (draggedEmail === chip) {
                  setDragOverIndex(null)
                  return
                }
                // Same-field reorder
                const from = chips.indexOf(draggedEmail)
                if (from !== -1) {
                  const newOrder = [...chips]
                  newOrder.splice(from, 1)
                  newOrder.splice(i, 0, draggedEmail)
                  onChange(newOrder.join(', '))
                }
                setDragOverIndex(null)
                localDragEmailRef.current = null
              }}
            >
              <span className="ca-chip-avatar" aria-hidden="true" style={{ background: generateColorFromString(getChipEmail(chip)) }}>
                {getInitials(getChipDisplayLabel(chip), getChipEmail(chip))}
              </span>
              <span className="ca-chip-label">{getChipDisplayLabel(chip)}</span>
              <button
                type="button"
                className="ca-chip-remove"
                onClick={(e) => { e.stopPropagation(); removeChip(i); }}
                tabIndex={-1}
                aria-label={`${t('remove')} ${chip}`}
              >
                <CloseIcon size={12} />
              </button>
              {activeChipPopover === i && (
                <span className="ca-chip-email-popover" onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
                  <span className="ca-chip-email-popover-email">{getChipEmail(chip)}</span>
                  <button
                    type="button"
                    className="ca-chip-email-popover-copy"
                    aria-label="Copier l'adresse e-mail"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={(e) => {
                      e.stopPropagation()
                      void copyToClipboard(getChipEmail(chip))
                      setChipCopied(true)
                      setTimeout(() => setChipCopied(false), 2000)
                    }}
                  >
                    {chipCopied ? (
                      <CheckIcon size={14} />
                    ) : (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                    )}
                  </button>
                </span>
              )}
            </span>
          ))}
        </div>
      )}
      <input
        ref={inputRef}
        type="text"
        role="combobox"
        data-testid={fieldId ? `compose-${fieldId}-input` : undefined}
        aria-expanded={isOpen}
        aria-autocomplete="list"
        aria-controls={isOpen ? 'contact-suggestions' : undefined}
        aria-activedescendant={
          highlightedIndex >= 0
            ? `contact-option-${highlightedIndex}`
            : undefined
        }
        value={multi ? query : query}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        onFocus={handleFocus}
        placeholder={multi && chips.length > 0 ? '' : placeholder}
        disabled={disabled}
        autoComplete="nope"
        autoFocus={autoFocus}
        spellCheck={false}
        aria-invalid={invalidEntry ? true : undefined}
        aria-describedby={invalidEntry ? 'ca-invalid-hint' : undefined}
      />

      {invalidEntry && (
        <span id="ca-invalid-hint" className="ca-invalid-hint" role="alert">
          {t('recipient_invalid_email', {
            email: invalidEntry,
            defaultValue: 'Invalid address "{{email}}" — expected name@domain.com',
          })}
        </span>
      )}

      {isOpen && dropdownPos && createPortal(
        <ul
          ref={listRef}
          id="contact-suggestions"
          role="listbox"
          aria-label="Suggestions de contacts"
          className="suggestions-list"
          style={{ position: 'fixed', top: dropdownPos.top, left: dropdownPos.left, width: dropdownPos.width, maxHeight: dropdownPos.maxHeight, margin: 0 }}
          // QA 2026-06-12: only claim Escape ownership while the user is
          // actively navigating the list (a row highlighted). The keydown
          // handler above deliberately lets Escape bubble when nothing is
          // highlighted so a single press closes the host modal — but the
          // unconditional data-escape-owner tag made hasEscapeOwner() return
          // true in NewMessageModal/useAppShortcuts, so the modal never
          // closed and the footer's "Esc Close" hint lied. Conditional
          // ownership restores the documented behaviour: no highlight →
          // one Esc closes the compose; highlighted → first Esc dismisses
          // the dropdown, second closes the compose.
          data-escape-owner={highlightedIndex >= 0 ? '' : undefined}
        >
          {suggestions.length > 0 ? suggestions.map((entry, index) => (
            <li
              key={isGroupSuggestion(entry) ? `grp-${entry.group.id}` : entry.email}
              id={`contact-option-${index}`}
              role="option"
              aria-selected={index === highlightedIndex}
              className={`suggestion-item ${
                index === highlightedIndex ? 'highlighted' : ''
              }${isGroupSuggestion(entry) && entry.group.id.startsWith('virtual_tous_') ? ' suggestion-item--tous' : ''}`}
              onMouseDown={(e) => { e.preventDefault(); handleSelectEntry(entry) }}
              onMouseEnter={() => setHighlightedIndex(index)}
            >
              {isGroupSuggestion(entry) ? (
                <>
                  <span className="suggestion-avatar suggestion-avatar-group">{entry.group.emoji || '👥'}</span>
                  <div className="contact-info">
                    <span className="contact-name">{entry.group.name}</span>
                    <span className="contact-email">{entry.group.members.length} {t('contacts')}</span>
                  </div>
                </>
              ) : (
                <>
                  {/* Même identité (2 lettres + couleur canon) que le chip une
                      fois sélectionné — l'ancienne formule hsl inline faisait
                      CHANGER la couleur au moment de la sélection. */}
                  <span className="suggestion-avatar" style={{ backgroundColor: generateColorFromString(entry.email) }}>
                    {getInitials(entry.name || null, entry.email)}
                  </span>
                  <div className="contact-info">
                    <span className="contact-name">{highlightMatch(entry.name || entry.email.split('@')[0], query)}</span>
                    <span className="contact-email">{highlightMatch(entry.email, query)}</span>
                  </div>
                  {onHideContact && (
                    <button
                      type="button"
                      className="suggestion-hide-btn"
                      title={t('hide_contact', 'Hide this contact')}
                      onMouseDown={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        handleHideContact(entry.email)
                      }}
                    >
                      <CloseIcon size={14} />
                    </button>
                  )}
                </>
              )}
            </li>
          )) : (
            <li className="suggestion-item suggestion-empty" aria-disabled="true">
              {t('no_contact_found')}
            </li>
          )}
        </ul>,
        document.body
      )}
    </div>
  )
}
