import { PlusIcon } from '../icons/ActionIcons'
import './GhostAddCard.css'

interface GhostAddCardProps {
  /** Visible label — also serves as the button's accessible name. */
  label: string
  onClick: () => void
  /** Optional extra class on the outer button (e.g. grid-span tweaks). */
  className?: string
}

/**
 * Dashed "ghost" card shaped like a content card, meant to sit as the first
 * cell of a card grid and open a create flow. Shared by the Label library and
 * Snippet library grids — one visual system instead of a full-width bar that
 * fights the grid.
 */
export function GhostAddCard({ label, onClick, className }: GhostAddCardProps) {
  return (
    <button
      type="button"
      className={`ghost-add-card${className ? ` ${className}` : ''}`}
      onClick={onClick}
    >
      <span className="ghost-add-card__icon">
        <PlusIcon size={17} />
      </span>
      <span className="ghost-add-card__label">{label}</span>
    </button>
  )
}
