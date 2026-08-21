/* ============================================================================
 * Canonical action icons for the Agentys UI.
 *
 * ONE source of truth for the common UI verbs — close, edit, save, delete,
 * add, back, settings, search, send, and the chevrons. Before this module the
 * app hand-inlined ~250 copies of these SVGs that had drifted in size, stroke
 * width, and path syntax (and a few were emoji: × ✕ ← ⚙️ ✓). Import from here
 * instead of pasting a new <svg>.
 *
 * Design system:
 *   • 24×24 viewBox · stroke 2 · round caps/joins — matches the dominant
 *     variant the audit found across the codebase.
 *   • Default render size 18px (the most common action-button size). Pass
 *     `size` to override (e.g. 14 for dense chips, 20 for standalone).
 *   • `fill="none" stroke="currentColor"` — colour follows the parent.
 *   • `aria-hidden` — these are decorative; the parent <button> carries the
 *     accessible label.
 * ============================================================================ */

import type { ReactNode } from 'react'

interface IconProps {
  size?: number
  strokeWidth?: number
  className?: string
}

interface SvgProps extends IconProps {
  children: ReactNode
}

/** Shared <svg> wrapper — keeps every action icon pixel-identical. */
function Svg({ size = 18, strokeWidth = 2, className, children }: SvgProps) {
  return (
    <svg
      aria-hidden="true"
      width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round"
      className={className}
    >
      {children}
    </svg>
  )
}

/** Close / dismiss — the canonical "X". Replaces × ✕ and every inline X SVG. */
export function CloseIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </Svg>
  )
}

/** Edit / modify — pencil. */
export function EditIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" />
      <path d="m15 5 4 4" />
    </Svg>
  )
}

/** Save / confirm / done — checkmark. Replaces the inline checks and emoji ✓. */
export function CheckIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M20 6 9 17l-5-5" />
    </Svg>
  )
}

/** Delete / remove — trash can. */
export function TrashIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3 6h18" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </Svg>
  )
}

/** Add / create / new — plus. */
export function PlusIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 12h14" />
      <path d="M12 5v14" />
    </Svg>
  )
}

/** Follow-up / relance — a single circular arrow (rotate-cw). The marker for
 *  woken follow-up drafts; replaces the 🔁 emoji, which rendered as an ugly
 *  fallback box and clashed with the line-art icon set. */
export function FollowUpIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
      <path d="M21 3v5h-5" />
    </Svg>
  )
}

/** Back / collapse-left — chevron. Use for "back" buttons and left nav. */
export function ChevronLeftIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m15 18-6-6 6-6" />
    </Svg>
  )
}

/** Forward / expand-right — chevron. */
export function ChevronRightIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m9 18 6-6-6-6" />
    </Svg>
  )
}

/** Expand / open — chevron down. */
export function ChevronDownIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m6 9 6 6 6-6" />
    </Svg>
  )
}

/** Collapse / close — chevron up. */
export function ChevronUpIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m18 15-6-6-6 6" />
    </Svg>
  )
}

/** Settings — gear. Replaces the inline gear SVG and the ⚙️ emoji. */
export function SettingsIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
      <circle cx="12" cy="12" r="3" />
    </Svg>
  )
}

/** Search — magnifying glass. */
export function SearchIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </Svg>
  )
}

/** Send — paper plane. */
export function SendIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M22 2 11 13" />
      <path d="M22 2 15 22 11 13 2 9z" />
    </Svg>
  )
}

/** AI generate from notes — draft sheet (sidebar Drafts) with a sparkle. */
export function MagicDraftIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M20 12V7l-5-5H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h6" />
      <path d="M14 2v4a1 1 0 0 0 1 1h4" />
      <path d="M9 13h5" />
      <path d="M9 17h3" />
      <path d="m16.7 16.7 1.3-2.7 1.3 2.7 2.7 1.3-2.7 1.3-1.3 2.7-1.3-2.7-2.7-1.3z" />
    </Svg>
  )
}
