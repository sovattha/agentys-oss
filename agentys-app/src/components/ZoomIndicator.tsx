import { useEffect, useRef, useState } from 'react'
import { ZOOM_USER_CHANGE_EVENT, type ZoomLevel } from '../hooks/useZoom'
import './ZoomIndicator.css'

/**
 * HUD transitoire affichant le niveau de zoom après un changement utilisateur.
 * Apparaît ~1.2s puis s'efface. Écoute le custom event `agentys:zoom-user-change`
 * (dispatché UNIQUEMENT depuis setZoom/zoomIn/zoomOut/resetZoom) — pas la prop
 * `zoom` directement. Sinon le HUD s'afficherait au refresh quand le hook
 * hydrate la valeur stockée après le 1er render (le mount initial reçoit
 * default=1.0, puis l'effet [accountId] charge la vraie valeur → faux positif).
 */
export function ZoomIndicator({ zoom }: { zoom: ZoomLevel }) {
  const [visible, setVisible] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const onUserChange = () => {
      setVisible(true)
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => setVisible(false), 1200)
    }
    window.addEventListener(ZOOM_USER_CHANGE_EVENT, onUserChange)
    return () => {
      window.removeEventListener(ZOOM_USER_CHANGE_EVENT, onUserChange)
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  return (
    <div
      className={`zoom-indicator${visible ? ' zoom-indicator--visible' : ''}`}
      role="status"
      aria-live="polite"
      aria-hidden={!visible}
    >
      {Math.round(zoom * 100)}%
    </div>
  )
}
