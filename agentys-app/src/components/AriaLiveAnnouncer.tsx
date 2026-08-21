import { useEffect, useRef, useState } from 'react'

/**
 * A11Y-2 fix — région aria-live globale pour annoncer les événements dynamiques
 * (nouveaux brouillons prêts, emails archivés, erreurs de pipeline, etc.) aux
 * lecteurs d'écran (NVDA, JAWS, VoiceOver).
 *
 * Usage côté composant :
 *   window.dispatchEvent(new CustomEvent('agentys:announce', {
 *     detail: { message: 'Brouillon prêt pour Jean', priority: 'polite' }
 *   }))
 *
 * - priority="polite" (défaut) : annoncé au prochain silence du lecteur (nouveaux brouillons, archivage)
 * - priority="assertive"      : interrompt la lecture (erreurs critiques uniquement)
 *
 * Le composant instancie DEUX écouteurs si utilisé deux fois (un polite, un assertive).
 * Un message est effacé après 3s pour permettre à un message identique d'être re-annoncé.
 */
export function AriaLiveAnnouncer({ priority = 'polite' }: { priority?: 'polite' | 'assertive' }) {
  const [message, setMessage] = useState('')
  const clearRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      const wantedPriority = (detail && detail.priority) || 'polite'
      if (wantedPriority !== priority) return
      const msg = typeof detail === 'string' ? detail : (detail?.message || '')
      if (!msg) return
      setMessage(msg)
      if (clearRef.current) clearTimeout(clearRef.current)
      clearRef.current = setTimeout(() => setMessage(''), 3000)
    }
    window.addEventListener('agentys:announce', handler)
    return () => {
      window.removeEventListener('agentys:announce', handler)
      if (clearRef.current) clearTimeout(clearRef.current)
    }
  }, [priority])

  return (
    <div
      role={priority === 'assertive' ? 'alert' : 'status'}
      aria-live={priority}
      aria-atomic="true"
      className="sr-only"
      data-testid={`aria-live-${priority}`}
    >
      {message}
    </div>
  )
}
