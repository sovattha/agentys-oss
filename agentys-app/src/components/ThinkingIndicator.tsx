import { useEffect, useRef, useState } from 'react'
import './ThinkingIndicator.css'

interface Props {
  visible: boolean
  label: string
  minShowMs?: number
  /** Debounce before appearing. Default 120 ms. */
  debounceMs?: number
  className?: string
}

export function ThinkingIndicator({
  visible,
  label,
  minShowMs = 0,
  debounceMs = 120,
  className,
}: Props) {
  const [shown, setShown] = useState(false)
  const shownAtRef = useRef<number | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    if (visible) {
      const t = setTimeout(() => {
        if (!mountedRef.current) return
        shownAtRef.current = Date.now()
        setShown(true)
      }, debounceMs)
      return () => clearTimeout(t)
    }
    const shownAt = shownAtRef.current
    if (shownAt == null) {
      setShown(false)
      return
    }
    const elapsed = Date.now() - shownAt
    const remaining = minShowMs > 0 ? Math.max(0, minShowMs - elapsed) : 0
    const t = setTimeout(() => {
      if (!mountedRef.current) return
      shownAtRef.current = null
      setShown(false)
    }, remaining)
    return () => clearTimeout(t)
  }, [visible, debounceMs, minShowMs])

  if (!shown) return null
  return (
    <div
      className={`thinking-indicator${className ? ` ${className}` : ''}`}
      role="status"
      aria-live="polite"
    >
      <span className="thinking-indicator-dot" aria-hidden="true" />
      <span className="thinking-indicator-text">{label}</span>
    </div>
  )
}
