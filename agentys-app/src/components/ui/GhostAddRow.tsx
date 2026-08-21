import { PlusIcon } from '../icons/ActionIcons'
import './GhostAddRow.css'

interface GhostAddRowProps {
  /** Visible label — also serves as the button's accessible name. */
  label: string
  onClick: () => void
  /** Optional extra class on the outer button. */
  className?: string
}

/**
 * Dashed "ghost" row shaped like a list item, meant to sit as the first row
 * of a row list and open a create flow. The row-list counterpart to
 * GhostAddCard. Shared by the Contact groups list and the Training FAQ list.
 */
export function GhostAddRow({ label, onClick, className }: GhostAddRowProps) {
  return (
    <button
      type="button"
      className={`ghost-add-row${className ? ` ${className}` : ''}`}
      onClick={onClick}
    >
      <span className="ghost-add-row__icon">
        <PlusIcon size={15} />
      </span>
      <span className="ghost-add-row__label">{label}</span>
    </button>
  )
}
