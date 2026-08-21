import { useTranslation } from 'react-i18next'
import type { SearchFilter } from './SmartSearchBar'
import { CloseIcon } from '../icons/ActionIcons'

// eslint-disable-next-line react-refresh/only-export-components
export const CHIP_COLORS: Record<string, string> = {
  from: '#3b82f6',
  to: '#8b5cf6',
  subject: '#ea580c',
  body: '#6366f1',
  label: '#22c55e',
  has: '#0d9488',
  after: '#eab308',
  before: '#eab308',
  exclude: '#dc2626',
  text: '#6b7280',
  in: '#3b82f6',
  cc: '#8b5cf6',
}

const TYPE_LABEL_KEYS: Record<string, string> = {
  from: 'chip_from',
  to: 'chip_to',
  cc: 'chip_cc',
  subject: 'chip_subject',
  body: 'chip_body',
  label: 'chip_label',
  has: 'chip_has',
  after: 'chip_after',
  before: 'chip_before',
  exclude: 'chip_exclude',
  in: 'chip_in',
  text: 'chip_text',
}

function ChipIcon({ type }: { type: string }) {
  const p = {
    'aria-hidden': true as const,
    width: 10,
    height: 10,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2.5,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
  switch (type) {
    case 'from':
    case 'to':
    case 'cc':
      return (
        <svg {...p}>
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </svg>
      )
    case 'subject':
    case 'text':
      return (
        <svg {...p}>
          <polyline points="4 7 4 4 20 4 20 7" />
          <line x1="9" y1="20" x2="15" y2="20" />
          <line x1="12" y1="4" x2="12" y2="20" />
        </svg>
      )
    case 'body':
      return (
        <svg {...p}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="8" y1="13" x2="16" y2="13" />
        </svg>
      )
    case 'label':
      return (
        <svg {...p}>
          <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
          <line x1="7" y1="7" x2="7.01" y2="7" />
        </svg>
      )
    case 'has':
      return (
        <svg {...p}>
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
        </svg>
      )
    case 'after':
    case 'before':
      return (
        <svg {...p}>
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      )
    case 'in':
      return (
        <svg {...p}>
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
        </svg>
      )
    case 'exclude':
      return (
        <svg {...p}>
          <circle cx="12" cy="12" r="10" />
          <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
        </svg>
      )
    default:
      return null
  }
}

interface SearchChipProps {
  filter: SearchFilter
  onRemove: () => void
  onEdit?: () => void
}

export function SearchChip({ filter, onRemove, onEdit }: SearchChipProps) {
  const { t } = useTranslation('search')
  const color = filter.color || CHIP_COLORS[filter.type] || 'var(--accent-primary)'
  const labelKey = TYPE_LABEL_KEYS[filter.type]
  const label = labelKey ? t(labelKey) : filter.type

  return (
    <span
      className="search-chip"
      style={{ '--chip-color': color } as React.CSSProperties}
      onClick={onEdit}
      role={onEdit ? 'button' : undefined}
      tabIndex={onEdit ? 0 : undefined}
      onKeyDown={onEdit ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onEdit() } } : undefined}
      title={onEdit ? 'Cliquer pour modifier' : undefined}
    >
      <span className="search-chip-icon" aria-hidden="true">
        <ChipIcon type={filter.type} />
      </span>
      <span className="search-chip-label">{label}</span>
      <span className="search-chip-separator" aria-hidden="true">·</span>
      <span className="search-chip-value">{filter.displayValue}</span>
      <button
        type="button"
        className="search-chip-remove"
        onClick={(e) => { e.stopPropagation(); onRemove() }}
        aria-label={t('remove_filter', { label, value: filter.displayValue })}
      >
        <CloseIcon size={12} />
      </button>
    </span>
  )
}