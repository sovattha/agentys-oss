import { useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { getLabelDisplayName } from '../../types/labels'
import { CloseIcon } from '../icons/ActionIcons'
import './LabelBadge.css'

interface LabelBadgeProps {
  name: string
  color: string
  size?: 'small' | 'medium'
  /** Left-click / keyboard activation. Receives the originating event so the
   *  caller can anchor a popover at the pointer (and stop the click from
   *  bubbling to a clickable ancestor — e.g. the email row's open handler). */
  onClick?: (e: React.MouseEvent) => void
  onRemove?: () => void
  showRemove?: boolean
  onContextMenu?: (e: React.MouseEvent) => void
}

export function LabelBadge({
  name,
  color,
  size = 'small',
  onClick,
  onRemove,
  showRemove = false,
  onContextMenu,
}: LabelBadgeProps) {
  const { t } = useTranslation('common')
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (!onContextMenu) return
    const touch = e.touches[0]
    longPressTimerRef.current = setTimeout(() => {
      longPressTimerRef.current = null
      // Synthesize a MouseEvent-like object with touch coordinates
      const syntheticEvent = {
        clientX: touch.clientX,
        clientY: touch.clientY,
        preventDefault: () => e.preventDefault(),
        stopPropagation: () => e.stopPropagation(),
      } as React.MouseEvent
      onContextMenu(syntheticEvent)
    }, 500)
  }, [onContextMenu])

  const handleTouchEnd = useCallback(() => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current)
      longPressTimerRef.current = null
    }
  }, [])

  const handleTouchMove = useCallback(() => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current)
      longPressTimerRef.current = null
    }
  }, [])

  // Keyboard activation for the (now focusable) badge button. Enter/Space must
  // open the picker — and crucially stopPropagation so the keypress never
  // bubbles to the email row's Enter/Space handler and opens the email. We
  // synthesize a mouse-like event anchored just below the badge so the caller
  // can position the popover even though there are no pointer coordinates.
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!onClick) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      e.stopPropagation()
      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
      onClick({
        clientX: rect.left,
        clientY: rect.bottom,
        preventDefault: () => {},
        stopPropagation: () => {},
      } as React.MouseEvent)
    }
  }, [onClick])

  return (
    <span
      className={`label-badge label-badge-${size} ${onClick ? 'clickable' : ''}`}
      style={{ '--label-color': color } as React.CSSProperties}
      onClick={onClick}
      onContextMenu={onContextMenu}
      onKeyDown={onClick ? handleKeyDown : undefined}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      onTouchMove={handleTouchMove}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <span className="label-badge-name">{getLabelDisplayName(name)}</span>
      {showRemove && onRemove && (
        <button
          className="label-badge-remove"
          onClick={(e) => {
            e.stopPropagation()
            onRemove()
          }}
          aria-label={`${t('remove')} ${getLabelDisplayName(name)}`}
        >
          <CloseIcon size={10} />
        </button>
      )}
    </span>
  )
}

interface LabelBadgeGroupProps {
  labels: Array<{ name: string; color: string }>
  maxVisible?: number
  size?: 'small' | 'medium'
  /** Left-click / tap on a label. Mirrors `onLabelContextMenu`: a label click
   *  is an intent to *change* that label, so the group stops the event from
   *  bubbling to a clickable container (the email row) before delegating. */
  onLabelClick?: (e: React.MouseEvent, label: { name: string; color: string }) => void
  onLabelContextMenu?: (e: React.MouseEvent, label: { name: string; color: string }) => void
  /** When provided, only labels whose name is in this set are shown. */
  allowedLabels?: ReadonlySet<string>
}

const HIDDEN_LABELS = new Set(['Waiting'])

export function LabelBadgeGroup({
  labels,
  maxVisible = 3,
  size = 'small',
  onLabelClick,
  onLabelContextMenu,
  allowedLabels,
}: LabelBadgeGroupProps) {
  // Filter out hidden labels + labels not in user library, then cap at maxVisible
  const visible = labels
    .filter((l) => !HIDDEN_LABELS.has(l.name) && (!allowedLabels || allowedLabels.has(l.name)))
    .slice(0, maxVisible)
  const [first, ...rest] = visible

  return (
    <div className="label-badge-group">
      {first && (
        <LabelBadge
          key={first.name}
          name={first.name}
          color={first.color}
          size={size}
          onClick={onLabelClick ? (e) => { e.stopPropagation(); onLabelClick(e, first) } : undefined}
          onContextMenu={onLabelContextMenu ? (e) => onLabelContextMenu(e, first) : undefined}
        />
      )}
      {rest.map((label) => (
        <span
          key={label.name}
          className={`label-badge-chip${onLabelClick ? ' clickable' : ''}`}
          style={{ '--label-color': label.color } as React.CSSProperties}
          title={getLabelDisplayName(label.name)}
          onClick={onLabelClick ? (e) => { e.preventDefault(); e.stopPropagation(); onLabelClick(e, label) } : undefined}
          onContextMenu={onLabelContextMenu ? (e) => {
            e.preventDefault()
            e.stopPropagation()
            onLabelContextMenu(e, label)
          } : undefined}
        />
      ))}
    </div>
  )
}
