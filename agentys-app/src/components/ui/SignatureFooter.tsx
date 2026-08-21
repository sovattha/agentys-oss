/**
 * SignatureFooter — non-editable preview of the active account's signature,
 * sanitized and stripped of any divider styling that would otherwise render
 * a stray line above the signature.
 *
 * Mount below a RichTextEditor (or any compose-like surface) so the user
 * sees what the recipient will see. The actual signature is appended on
 * the backend at send time, so this is purely a visual hint — keep the
 * underlying body payload signature-free.
 *
 * Each consumer passes its own className for site-specific positioning /
 * spacing tweaks. Centralizing the sanitize + scrub logic here avoids the
 * existing duplicate implementations in NewMessageModal / ReplyComposer
 * drifting further apart.
 */
import { useMemo } from 'react'
import DOMPurify from 'dompurify'

import { useAccountSignature } from '../../hooks/useAccountSignature'

interface SignatureFooterProps {
  /** Class applied to the wrapper div — used by each call site for layout. */
  className?: string
  /** Optional inline style merged onto the wrapper (e.g. matching the
   *  editor's font-family / font-size for visual continuity). */
  style?: React.CSSProperties
}

export function SignatureFooter({ className = 'signature-footer', style }: SignatureFooterProps) {
  const { html: rawHtml } = useAccountSignature()
  const cleanHtml = useMemo(() => {
    if (!rawHtml) return null
    const clean = DOMPurify.sanitize(rawHtml, { USE_PROFILES: { html: true } })
    // Strip border-top/padding-top so the signature blends with the editor
    // wrapper rather than drawing a stray divider line above itself.
    return clean
      .replace(/border-top\s*:[^;"]*/gi, 'border-top:none')
      .replace(/padding-top\s*:\s*[^;"]*/gi, 'padding-top:0')
  }, [rawHtml])

  if (!cleanHtml) return null
  return (
    <div
      className={className}
      style={style}
      dangerouslySetInnerHTML={{ __html: cleanHtml }}
    />
  )
}
