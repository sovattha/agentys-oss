import { getAuthHeaders } from '../services/authToken'

/**
 * Strip path separators, control chars, and any leading dots from an attachment
 * filename before passing it to the save dialog (audit Codex 2026-04-25
 * [F-T-08]). The dialog initialises with `defaultPath`; on Windows, a malicious
 * email named `..\\Windows\\System32\\drivers\\etc\\hosts` would otherwise
 * navigate the dialog there. Result is a basename-shaped string with at most
 * 200 chars.
 */
function sanitizeFilename(name: string): string {
  const stripped = name
    // eslint-disable-next-line no-control-regex
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, '_')
    .replace(/^\.+/, '_')
    .trim()
  const safe = stripped || 'attachment'
  return safe.length > 200 ? safe.slice(0, 200) : safe
}

interface DownloadAttachmentOptions {
  openPreviewOnMobile?: boolean
}

function isMobileBrowser(): boolean {
  if (typeof navigator === 'undefined') return false
  const userAgent = navigator.userAgent || ''
  return /Android|iPhone|iPad|iPod/i.test(userAgent) ||
    (/Macintosh/i.test(userAgent) && navigator.maxTouchPoints > 1)
}

export function isPreviewableAttachment(contentType: string, filename: string): boolean {
  const normalizedType = contentType.split(';')[0].trim().toLowerCase()
  const lowerName = filename.toLowerCase()

  if (normalizedType === 'application/pdf') return true
  if (normalizedType.startsWith('image/')) return true
  // Audit 2026-06-10 F-01 : seuls les text/* inertes. text/html (et xml/js)
  // rendrait le document de l'attaquant comme HTML vivant dans la préview.
  if (normalizedType === 'text/plain' || normalizedType === 'text/csv') return true

  return /\.(pdf|png|jpe?g|gif|webp|txt|csv)$/i.test(lowerName)
}

export const PREVIEW_IMAGE_RE = /\.(png|jpe?g|gif|webp|svg|bmp|avif)$/i

/**
 * Types serveur acceptés tels quels quand l'extension ne suffit pas (review
 * F1 : README sans extension, .jfif/.heic… s'affichaient avant le fix F-01).
 * Allowlist stricte — jamais text/html ni aucun type actif.
 */
const SAFE_SERVER_DISPLAY_TYPES = new Set([
  'application/pdf',
  'text/plain',
  'text/csv',
  'text/markdown',
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'image/svg+xml',
  'image/bmp',
  'image/avif',
])

/**
 * Type MIME d'affichage : dérivé d'abord de l'extension du nom de fichier ;
 * à défaut, le content-type serveur n'est honoré que s'il appartient à
 * l'allowlist ci-dessus. Le type serveur vient du MIME de l'email
 * (attaquant-contrôlé) et ne doit jamais atteindre un iframe hors allowlist
 * (audit 2026-06-10 F-01). Tout le reste devient octet-stream (inerte).
 */
export function safeDisplayBlobType(filename: string, serverType = ''): string {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.pdf')) return 'application/pdf'
  const img = lower.match(PREVIEW_IMAGE_RE)
  if (img) {
    const ext = img[1].replace('jpg', 'jpeg')
    return ext === 'svg' ? 'image/svg+xml' : `image/${ext}`
  }
  if (/\.(txt|csv|md|log)$/i.test(lower)) return 'text/plain'
  const normalized = serverType.split(';')[0].trim().toLowerCase()
  if (SAFE_SERVER_DISPLAY_TYPES.has(normalized)) {
    return normalized.startsWith('text/') ? 'text/plain' : normalized
  }
  return 'application/octet-stream'
}

/** Re-type systématiquement un blob téléchargé vers son type d'affichage sûr. */
export function toSafeDisplayBlob(raw: Blob, filename: string): Blob {
  const wanted = safeDisplayBlobType(filename, raw.type)
  return raw.type === wanted ? raw : new Blob([raw], { type: wanted })
}

/**
 * Décode le manifeste d'échecs partiels du download-all (audit 2026-06-10
 * F-02) : header `X-Failed-Attachments`, noms URL-encodés séparés par des
 * virgules — voir routes_emails.py download_all_email_attachments.
 */
export function parseFailedAttachmentsHeader(value: string | null): string[] {
  if (!value) return []
  return value
    .split(',')
    .map((part) => {
      const trimmed = part.trim()
      try {
        return decodeURIComponent(trimmed)
      } catch {
        return trimmed
      }
    })
    .filter(Boolean)
}

export interface DownloadAttachmentResult {
  /** Fichiers que le backend n'a pas pu inclure dans l'archive (zip partiel). */
  failedAttachments: string[]
}

function renderMobilePreview(previewWindow: Window, blobUrl: string, filename: string, displayType: string): void {
  const doc = previewWindow.document
  doc.title = filename
  doc.documentElement.style.height = '100%'
  doc.body.textContent = ''
  doc.body.style.margin = '0'
  doc.body.style.height = '100%'
  doc.body.style.background = '#fff'

  const frame = doc.createElement('iframe')
  frame.src = blobUrl
  frame.title = filename
  frame.style.border = '0'
  frame.style.width = '100%'
  frame.style.height = '100%'
  frame.style.display = 'block'
  // Audit 2026-06-10 F-01 : neutralise tout contenu actif. Exception pdf :
  // le viewer Chromium ne se charge pas dans un iframe sandboxé, et le blob
  // est déjà re-typé application/pdf (inerte) par toSafeDisplayBlob.
  if (displayType !== 'application/pdf') frame.setAttribute('sandbox', '')
  doc.body.appendChild(frame)
}

/**
 * Downloads an attachment. In Tauri, opens a native save dialog.
 * Falls back to browser download otherwise. Mobile Safari gets a preview tab for
 * browser-readable files because the `download` attribute often produces a file
 * the user cannot open from the in-app browser chrome.
 */
export async function downloadAttachment(
  downloadUrl: string,
  filename: string,
  options: DownloadAttachmentOptions = {},
): Promise<DownloadAttachmentResult> {
  const safeFilename = sanitizeFilename(filename)
  const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
  const shouldOpenPreview = options.openPreviewOnMobile !== false && !isTauri && isMobileBrowser()
  const previewWindow = shouldOpenPreview ? window.open('about:blank', '_blank') : null

  try {
    const response = await fetch(downloadUrl, { headers: getAuthHeaders() })
    if (!response.ok) throw new Error('Download failed')
    const blob = await response.blob()
    const result: DownloadAttachmentResult = {
      failedAttachments: parseFailedAttachmentsHeader(response.headers?.get('X-Failed-Attachments') ?? null),
    }

    if (isTauri) {
      try {
        const { save } = await import('@tauri-apps/plugin-dialog')
        // Annulation volontaire : aucun fichier écrit, un avertissement
        // « archive incomplète » serait hors sujet (review F6).
        const selectedPath = await save({ defaultPath: safeFilename })
        if (!selectedPath) return { failedAttachments: [] }
        const { writeFile } = await import('@tauri-apps/plugin-fs')
        await writeFile(selectedPath, new Uint8Array(await blob.arrayBuffer()))
        return result
      } catch (err) {
        console.warn('[downloadAttachment] Tauri save failed, falling back to browser:', err)
      }
    }

    const contentType = response.headers?.get('content-type') || blob.type
    if (previewWindow && isPreviewableAttachment(contentType, safeFilename)) {
      // Audit 2026-06-10 F-01 : re-typage forcé — le type serveur vient du
      // MIME de l'email et ne doit jamais atteindre un iframe tel quel.
      const typed = toSafeDisplayBlob(blob, safeFilename)
      const url = URL.createObjectURL(typed)
      renderMobilePreview(previewWindow, url, safeFilename, typed.type)
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      return result
    }

    previewWindow?.close()

    // Browser fallback. Append the anchor to the DOM before clicking (a detached
    // anchor click is a no-op in some engines) and defer revoking the object URL —
    // revoking synchronously right after click() can abort an in-flight download of
    // a larger blob. Mirrors the working .ics download path in EmailDetailModal.
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = safeFilename
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    return result
  } catch (err) {
    previewWindow?.close()
    throw err
  }
}
