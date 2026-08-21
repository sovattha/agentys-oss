import { useState, useCallback, useRef, useEffect } from 'react'

const STORAGE_KEY = 'agentys_detail_panel_width'
// Floor wide enough to keep the whole reply/compose toolbar on one row without
// clipping its icons (the toolbar's natural single-row width is ~600px; below
// ~560px the icons start to get lost). Kept in sync with --detail-panel-min in
// App.css. The Tauri window minWidth is 800px, so this floor is always honourable.
const MIN_WIDTH = 560
const MAX_WIDTH = 1200
const DEFAULT_WIDTH = 560

// BUG-P002 fix: clamp loaded width against viewport so a saved value from a
// wider display (or a lower zoom level) doesn't overflow at 130% zoom.
// Reserve at least 400px for sidebar + email list. The MIN_WIDTH floor still
// wins on small viewports (Math.max(MIN_WIDTH, …) keeps the cap ≥ MIN_WIDTH, and
// the grid lets the list shrink to honour the floor).
function clampToViewport(w: number): number {
  const maxFromVp = typeof window !== 'undefined' ? Math.max(MIN_WIDTH, window.innerWidth - 400) : MAX_WIDTH
  return Math.min(Math.max(w, MIN_WIDTH), Math.min(MAX_WIDTH, maxFromVp))
}

export function useResizePanel() {
  const [width, setWidth] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return clampToViewport(saved ? parseInt(saved, 10) : DEFAULT_WIDTH)
  })
  const [isDragging, setIsDragging] = useState(false)
  const isDraggingRef = useRef(false)
  const widthRef = useRef(width)
  widthRef.current = width

  // Store handlers in refs for cleanup
  const handlersRef = useRef<{ move: (ev: MouseEvent) => void; up: () => void } | null>(null)

  // Cleanup on unmount — prevents listener leaks if component unmounts mid-drag
  useEffect(() => {
    return () => {
      if (handlersRef.current) {
        document.removeEventListener('mousemove', handlersRef.current.move)
        document.removeEventListener('mouseup', handlersRef.current.up)
        handlersRef.current = null
      }
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [])

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDraggingRef.current = true
    setIsDragging(true)
    const startX = e.clientX
    const startWidth = widthRef.current

    const handleMouseMove = (ev: MouseEvent) => {
      if (!isDraggingRef.current) return
      const delta = startX - ev.clientX
      const newWidth = Math.min(Math.max(startWidth + delta, MIN_WIDTH), MAX_WIDTH)
      setWidth(newWidth)
    }

    const handleMouseUp = () => {
      isDraggingRef.current = false
      setIsDragging(false)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      handlersRef.current = null
      setWidth(w => {
        localStorage.setItem(STORAGE_KEY, String(w))
        return w
      })
    }

    // Clean up any stale handlers from a previous drag
    if (handlersRef.current) {
      document.removeEventListener('mousemove', handlersRef.current.move)
      document.removeEventListener('mouseup', handlersRef.current.up)
    }
    handlersRef.current = { move: handleMouseMove, up: handleMouseUp }

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }, [])

  return { detailPanelWidth: width, isDragging, handleResizeStart }
}
