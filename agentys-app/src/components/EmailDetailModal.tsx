import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from '../i18n';
import { formatGmailDateTime, formatShortDateFromDate } from '../utils/dateFormat';
import { API_URL } from '../config';
import { ReplyComposer } from './reply';
import { ErrorBoundary } from './ErrorBoundary';
import type { EmailDetail as EmailDetailType } from '../types/email';
import {
  sanitizeEmailBody,
  isHtmlContent,
  stripQuotedContent,
  stripQuotedHtml,
  stripEmailTrackingResources,
  repairLowContrastEmailText,
  upgradeInsecureImageSources,
  computeFitScale,
} from '../utils/emailContent';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { AIProgressBar, type AIStage } from './AIProgressBar';
import { getCachedEmailDetail, updateCachedEmailDetail } from '../api/emails';
import { getReplyDraftForEmail } from '../services/draftStorage';
import { apiClient, rsvpMeeting, ApiError } from '../services/api';
import { getAuthHeaders, handleAuthResponse, getJwtEmail } from '../services/authToken';
import { getWebSocketClient } from '../services/websocket';
import { LabelBadgeGroup } from './labels/LabelBadge';
import { ReceivedAttachments } from './attachments/ReceivedAttachments';
import { useComposeFontPrefs } from '../hooks/useComposeFontPrefs';
import { openUrl } from '../utils/openUrl';
import { silentFailLog } from '../utils/silentFail';
import { hasEscapeOwner } from '../utils/escapeOwner';
import { QuickStepsBar } from './QuickStepsBar';
import { QuickStepsPalette } from './QuickStepsPalette';
import { ContactAvatar } from './ContactAvatar';
import { CloseIcon, CheckIcon, ChevronUpIcon, ChevronDownIcon } from './icons/ActionIcons';
import { generateColorFromString, getInitials } from './Avatar';
import './EmailDetailModal.css';

function isMeetingInvite(email: EmailDetailType | null): boolean {
  if (!email) return false;
  const subject = email.subject || '';
  const body = (email.body_html || email.body || '').replace(/<[^>]+>/g, ' ');

  // Booking-tool confirmation (Calendly). Recognised once the backend has
  // tagged meeting_meta as an appointment, OR straight from the body so the
  // card's body-fetch retry fires before meeting_meta is populated.
  if (email.meeting_meta?.kind === 'appointment') return true;
  if (/calendly\.com/i.test(body)) return true;

  // Subject-based detection (Google Calendar / Outlook standard patterns)
  if (
    /^(?:(?:re|tr|rv|fw|fwd)\s*:\s*)?(?:new\s+)?invitation\s*:/i.test(subject) ||
    /^(?:(?:re|tr|rv|fw|fwd)\s*:\s*)?nouvelle\s+invitation\s*:/i.test(subject) ||
    /(?:zoom|teams|google\s+meet)\s+meeting\s+invitation/i.test(subject) ||
    /microsoft\s+teams\s+meeting/i.test(subject)
  ) return true;

  // .ics attachment present
  if (email.attachments?.some(a => a.filename?.toLowerCase().endsWith('.ics'))) return true;

  // Body signals (Teams / Zoom / Meet links)
  if (
    /réunion\s+microsoft\s+teams/i.test(body) ||
    /microsoft\s+teams\s+meeting/i.test(body) ||
    /join\.microsoft\.com\/meet\//i.test(body) ||
    /teams\.microsoft\.com\/l\/meetup/i.test(body) ||
    /zoom\.us\/j\//i.test(body) ||
    /meet\.google\.com\//i.test(body)
  ) return true;

  return false;
}

/**
 * Build and download an .ics for a booking-tool appointment confirmation.
 *
 * The slot is already booked; this is a convenience so the user can drop it into
 * whatever calendar they use (Google, Outlook, Apple — provider-agnostic).
 * DTSTART/DTEND are emitted as *floating* local time (no TZID): the email states
 * its own zone (kept in `tz_label`, shown in the card and the DESCRIPTION), and
 * for the common case the viewer is in that same zone. Calendar apps show an
 * import preview, so a zone mismatch stays visible and correctable before save.
 */
function downloadAppointmentIcs(
  meta: NonNullable<EmailDetail['meeting_meta']>,
  fallbackTitle: string,
): void {
  if (!meta.dtstart) return;
  const toStamp = (iso: string): string | null => {
    const m = iso.match(/(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    return m ? `${m[1]}${m[2]}${m[3]}T${m[4]}${m[5]}00` : null;
  };
  const start = toStamp(meta.dtstart);
  if (!start) return;
  const end = (meta.dtend && toStamp(meta.dtend)) || start;
  const esc = (s: string) =>
    s.replace(/\\/g, '\\\\').replace(/([,;])/g, '\\$1').replace(/\r?\n/g, '\\n');
  const title = (meta.summary || fallbackTitle || 'Appointment').replace(/\s+/g, ' ').trim();
  const desc: string[] = [];
  if (meta.tz_label) desc.push(meta.tz_label);
  if (meta.reschedule_url) desc.push(`Reschedule: ${meta.reschedule_url}`);
  if (meta.cancel_url) desc.push(`Cancel: ${meta.cancel_url}`);
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Agentys//Appointment//EN',
    'CALSCALE:GREGORIAN',
    'BEGIN:VEVENT',
    `UID:agentys-appt-${start}-${end}@agentys.io`,
    `DTSTART:${start}`,
    `DTEND:${end}`,
    `SUMMARY:${esc(title)}`,
    meta.location ? `LOCATION:${esc(meta.location)}` : '',
    desc.length ? `DESCRIPTION:${esc(desc.join('\n'))}` : '',
    'END:VEVENT',
    'END:VCALENDAR',
  ].filter(Boolean);
  const blob = new Blob([lines.join('\r\n')], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'appointment.ics';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

type EmailDetailLoadDiagnostic =
  | { kind: 'provider_slow' }
  | { kind: 'backend_ok'; latencyMs: number }
  | { kind: 'backend_unhealthy'; status: number; latencyMs: number }
  | { kind: 'backend_unknown' };

async function probeBackendHealth(): Promise<EmailDetailLoadDiagnostic> {
  const startedAt = performance.now();
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 3500);
  try {
    const response = await fetch(`${API_URL}/api/health/strict`, {
      signal: controller.signal,
      headers: { ...getAuthHeaders() },
    });
    const latencyMs = Math.max(1, Math.round(performance.now() - startedAt));
    if (response.ok) return { kind: 'backend_ok', latencyMs };
    return { kind: 'backend_unhealthy', status: response.status, latencyMs };
  } catch {
    return { kind: 'backend_unknown' };
  } finally {
    window.clearTimeout(timeout);
  }
}

/**
 * Renders HTML emails in a sandboxed iframe for proper style isolation.
 * Email <style> blocks are preserved without leaking into the app.
 *
 * Uses srcDoc (not doc.write) so React injects content before mount,
 * avoiding the Tauri/WebKit timing issue where contentDocument is null
 * when a useEffect fires on an empty iframe.
 */
/** Map data-theme → iframe background/text/link colors and color-scheme. */
const IFRAME_THEME_STYLES: Record<string, { bg: string; text: string; link: string; scheme: 'light' | 'dark' }> = {
  'default':       { bg: '#ffffff', text: '#1a1a1a', link: '#1a73e8', scheme: 'light' },
};

export function HtmlEmailIframe({ body }: { body: string }) {
  const { t } = useTranslation('inbox');
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(80);
  const cleanupRef = useRef<(() => void) | null>(null);

  // Même typo par défaut que l'éditeur de réponse (préférence utilisateur) :
  // le corps reçu et la réponse partagent police, taille et interligne. Les
  // emails HTML riches gardent leurs styles inline (priorité CSS normale).
  const { fontFamilyCss, fontSizeCss } = useComposeFontPrefs();
  const resolvedBodyFont = useMemo(() => {
    // var(--font-sans) ne se résout pas dans l'iframe (document isolé).
    if (fontFamilyCss.startsWith('var(')) {
      const name = fontFamilyCss.slice(4, -1);
      const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return val || "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    }
    return fontFamilyCss;
  }, [fontFamilyCss]);

  // Track current theme so the iframe background matches the app theme.
  // We read data-theme from <html> and watch it via MutationObserver.
  const [currentTheme, setCurrentTheme] = useState<string>(
    () => document.documentElement.getAttribute('data-theme') || 'default'
  );
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setCurrentTheme(document.documentElement.getAttribute('data-theme') || 'default');
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, []);

  const themeStyle = IFRAME_THEME_STYLES[currentTheme] ?? IFRAME_THEME_STYLES['default'];

  // Resolve the app's --text-primary so an *uncolored* HTML email renders the
  // same body-text color as a plain-text email (.email-body-content / single-
  // email view). var() doesn't resolve inside the isolated iframe document, so
  // we read the computed value here (same pattern as resolvedBodyFont). Emails
  // that hardcode their own colors keep them — this only sets the default.
  const resolvedTextColor = useMemo(() => {
    const val = getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim();
    return val || '#111827';
  }, [currentTheme]);

  // Compute HTML once per body/theme change (memoized)
  const processedHtml = useMemo(() => {
    const { bg, link, scheme } = themeStyle;
    const text = resolvedTextColor;
    // Rail horizontal aligné sur var(--space-4) du parent = 16px × --app-zoom.
    // L'iframe est un document isolé : la variable n'y existe pas, on résout.
    const appZoom = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--app-zoom')) || 1;
    const railPad = `${(16 * appZoom).toFixed(1)}px`;
    let html = body;
    // Fix legacy cached emails where HTML was entity-encoded inside a pre-wrap wrapper
    // e.g. <div style="white-space:pre-wrap">text&lt;div class=&quot;agentys-signature&quot;&gt;...&lt;/div&gt;</div>
    if (/white-space:\s*pre-wrap/.test(html) && /&lt;(div|p|br|span)\s*/i.test(html)) {
      const tmp = document.createElement('div');
      tmp.innerHTML = html;
      html = tmp.textContent || tmp.innerText || html;
    }
    // Strip scripts only — keep <style> and inline styles for layout
    html = html.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '');
    // Strip unresolved cid: image references (inline images not resolved to data: URIs by backend)
    html = html.replace(/<img[^>]+src=["']cid:[^"']+["'][^>]*\/?>/gi, '');
    html = stripEmailTrackingResources(html);
    // srcDoc iframes inherit the parent CSP (img-src https: only) — upgrade
    // http:// images or they render as broken placeholders. After the pixel
    // strip so open beacons are removed, not upgraded-and-fired.
    html = upgradeInsecureImageSources(html);

    // Base styles: theme-aware background + email-safe resets.
    // Note: many HTML emails hardcode colors — we intentionally keep their inline styles
    // and only set defaults for un-styled elements.
    const baseStyles = `<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="${scheme}"><style>
      :root { color-scheme: ${scheme} !important; }
      html { width: 100%; background: ${bg}; overflow-x: hidden; scrollbar-width: none; -ms-overflow-style: none; }
      html::-webkit-scrollbar, body::-webkit-scrollbar { width: 0 !important; height: 0 !important; display: none !important; }
      body { margin: 0; padding: 4px ${railPad} 16px; box-sizing: border-box; background: ${bg}; color: ${text}; font-family: ${resolvedBodyFont}; font-size: ${fontSizeCss}; line-height: 1.4; overflow-x: hidden; scrollbar-width: none; -ms-overflow-style: none; }
      /* Hide the trailing signature separator — already visually distinct from the body spacing */
      .agentys-signature { border-top: none !important; padding-top: 0 !important; margin-top: 12px !important; color: ${text} !important; }
      .agentys-signature * { color: inherit !important; }
      img { max-width: 100% !important; height: auto; display: inline-block; }
      table { border-collapse: collapse; }
      td, th { word-break: break-word; }
      a { color: ${link}; }
    </style>`;

    // Override styles: cap overflow, responsive images, basic reset.
    const overrideStyles = `<style>
      body { padding: 4px ${railPad} 16px !important; }
      td, th { word-break: break-word; }
      img { max-width: 100% !important; height: auto; }
      /* Make fixed-width tables fluid so email footer icon grids don't
         overflow their column and overlap adjacent cells. */
      table { max-width: 100% !important; }
      table[width] { width: 100% !important; }
      center { display: block !important; text-align: center !important; }
      td[align="center"] table,
      th[align="center"] table,
      table[align="center"],
      td[style*="text-align:center"] table,
      td[style*="text-align: center"] table {
        margin-left: auto !important;
        margin-right: auto !important;
      }
      center > table,
      center > div {
        margin-left: auto !important;
        margin-right: auto !important;
      }
      /* Print/PDF: the fit-to-width JS scales <body> with a CSS transform sized
         to the on-screen pane. Print engines lay out to the paper width and some
         drop transforms — either way the screen scale is wrong on paper, so undo
         it and let the page width drive layout. */
      @media print {
        html, body { overflow: visible !important; }
        body { transform: none !important; width: auto !important; }
      }
    </style>`;

    const wrapOpen = '<div style="width:100%;max-width:100%;box-sizing:border-box;text-align:left;">';
    const wrapClose = '</div>';

    if (/<html[\s>]/i.test(html)) {
      html = html.replace(/<html/i, '<html lang="fr"');
      html = html.replace(/<head([^>]*)>/i, `<head$1><meta charset="utf-8">${baseStyles}`);
      html = html.replace(/<\/head>/i, `${overrideStyles}</head>`);
      html = html.replace(/(<body[^>]*>)/i, `$1${wrapOpen}`);
      html = html.replace(/<\/body>/i, `${wrapClose}</body>`);
    } else {
      html = `<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">${baseStyles}${overrideStyles}</head><body>${wrapOpen}${html}${wrapClose}</body></html>`;
    }

    return html;
  }, [body, themeStyle, resolvedBodyFont, resolvedTextColor, fontSizeCss]);

  // Clean up listeners when body changes or component unmounts
  useEffect(() => {
    return () => {
      cleanupRef.current?.();
      cleanupRef.current = null;
    };
  }, [body]);

  const handleLoad = useCallback(() => {
    // Tear down previous listeners (body change fired a new load)
    cleanupRef.current?.();
    cleanupRef.current = null;

    const iframe = iframeRef.current;
    if (!iframe) return;
    const doc = iframe.contentDocument;
    if (!doc || !doc.body) return;

    const resize = () => {
      repairLowContrastEmailText(doc);
      const docEl = doc.documentElement;
      const bodyEl = doc.body;
      if (!bodyEl) return;

      // --- Fit-to-width ---
      // Fixed-width emails (a 600px table, a `<div style="width:...px">`, a long
      // unbreakable token) overflow a narrow reading pane and are clipped on the
      // right by the body's `overflow-x:hidden` -- the "email coupe" bug. The
      // override CSS only constrains <img>/<table>; everything else still
      // overflows, and how much you see depends purely on the pane width (wide
      // monitor -> fits, narrower pane / higher display-scaling -> clipped). So we
      // measure the real content width and scale the whole document down to fit.
      //
      // Reset any prior fit FIRST so we always measure the natural width. This
      // also makes resize idempotent: re-running on an already-fitted body
      // recomputes the identical width, so the ResizeObserver below sees no net
      // size change between deliveries and does not loop.
      bodyEl.style.transform = '';
      bodyEl.style.width = '';
      bodyEl.style.transformOrigin = '';
      // clientWidth = iframe inner viewport (scrollbars are hidden -> no inset),
      // independent of body width. scrollWidth reports the full content extent
      // even under overflow:hidden.
      const available = docEl.clientWidth;
      const contentWidth = Math.max(bodyEl.scrollWidth, docEl.scrollWidth);
      const scale = computeFitScale(available, contentWidth);
      if (scale < 1) {
        // Widen the body to the content's natural width so nothing is clipped,
        // then scale the whole box down to fit the pane. Anchor the origin to the
        // content's start edge: 'top left' for LTR, 'top right' for RTL emails
        // (Arabic/Hebrew/etc.) so the meaningful edge stays put if a floor-clamped
        // pathological email is still wider than the pane and the far side clips.
        const isRtl = (doc.defaultView?.getComputedStyle(bodyEl).direction === 'rtl');
        bodyEl.style.width = `${contentWidth}px`;
        bodyEl.style.transformOrigin = isRtl ? 'top right' : 'top left';
        bodyEl.style.transform = `scale(${scale})`;
      }

      // --- Height (accounts for the scale) ---
      // scrollHeight is layout-based and ignores the CSS transform, so multiply
      // by `scale` for the visual height. Default: full scaled scrollHeight.
      const fullH = Math.max(
        docEl?.scrollHeight || 0,
        bodyEl?.scrollHeight || 0,
      ) * scale;
      // Trim trailing empty space: scan all non-blank elements and take the
      // MAX bottom edge. Why max (not "last in DOM order"): CSS layout (flex,
      // float, position, table-row reordering) can place a deeply-nested
      // element visually higher than an earlier-in-source sibling. Using max
      // guarantees we never clip content that paints further down. Newsletters
      // often append empty <br>/<p>/<table> rows that inflate scrollHeight,
      // so this is still tighter than fullH on those.
      // getBoundingClientRect already returns post-transform (scaled) coords, so
      // these bottoms are visual -- no extra multiply here.
      let trimmedH = 0;
      try {
        const isBlank = (el: Element): boolean => {
          if (el.querySelector('img,hr,input,button,svg,video,canvas')) return false;
          const text = (el.textContent || '').replace(/\u00A0/g, ' ').trim();
          return text.length === 0;
        };
        const all = bodyEl.querySelectorAll<HTMLElement>('*');
        for (let i = 0; i < all.length; i++) {
          const el = all[i];
          if (isBlank(el)) continue;
          const rect = el.getBoundingClientRect();
          const bottom = rect.bottom + (docEl.scrollTop || 0);
          if (bottom > trimmedH) {
            trimmedH = Math.ceil(bottom);
          }
        }
      } catch {
        trimmedH = fullH;
      }
      // +8px buffer to avoid clipping anti-aliased text or 1px box-shadow.
      const h = Math.min(fullH, trimmedH ? trimmedH + 8 : fullH);
      // Guard against sub-pixel oscillation: setHeight -> iframe height change ->
      // contentWindow 'resize' -> resize() again. Ignore <1px deltas.
      if (h > 0) setHeight((prev) => (Math.abs(prev - h) < 1 ? prev : Math.round(h)));
    };

    // Resize on body mutations and image loads — wrap in rAF to avoid
    // "ResizeObserver loop completed with undelivered notifications" warnings
    const rafResize = () => requestAnimationFrame(resize);
    const observer = new ResizeObserver(rafResize);
    observer.observe(doc.body);
    // Re-fit when the pane (iframe viewport) itself changes width — e.g. the
    // user drags the split divider or resizes the window. The body ResizeObserver
    // above misses this once a fit pins body.width, so listen on the iframe's own
    // window, which fires when the iframe element is resized.
    const iframeWin = doc.defaultView;
    iframeWin?.addEventListener('resize', rafResize);
    const imgs = doc.querySelectorAll('img');
    imgs.forEach((img) => {
      if (!img.complete) img.addEventListener('load', resize);
    });
    resize();
    // Progressive resize with exponential backoff (newsletters load progressively)
    const timer1 = setTimeout(resize, 200);
    const timer2 = setTimeout(resize, 800);
    const timer3 = setTimeout(resize, 2000);

    // Intercept link clicks → open in system browser (not webview)
    const handleClick = (e: MouseEvent) => {
      const anchor = (e.target as HTMLElement).closest('a');
      if (anchor?.href) {
        e.preventDefault();
        openUrl(anchor.href);
      }
    };
    doc.addEventListener('click', handleClick);

    // Forward keyboard shortcuts from inside the iframe to the parent window
    // (iframe keydown events don't bubble to parent — needed for Del, E, R, etc.)
    // BUG-N003 fix: '/' missing → search shortcut swallowed when focus is inside iframe.
    const FORWARDED_KEYS = new Set(['Delete', 'Backspace', 'Escape', 'ArrowUp', 'ArrowDown', 'e', 'r', 'a', 'f', 'n', 'u', 'g', 'G', '/']);
    const handleIframeKeyDown = (e: KeyboardEvent) => {
      if (FORWARDED_KEYS.has(e.key)) {
        e.preventDefault();
        window.dispatchEvent(new KeyboardEvent('keydown', {
          key: e.key,
          code: e.code,
          ctrlKey: e.ctrlKey,
          metaKey: e.metaKey,
          shiftKey: e.shiftKey,
          altKey: e.altKey,
          bubbles: true,
        }));
      }
    };
    doc.addEventListener('keydown', handleIframeKeyDown);

    // Forward wheel events from the iframe to the parent so scroll feels continuous
    // between the original email body and the draft composer below. Without this,
    // scrolling over the iframe is a dead zone — wheel events stay in the sandboxed
    // document and don't bubble up to .email-detail-inline (the unified scroller).
    const handleIframeWheel = (e: WheelEvent) => {
      // Find the nearest scrollable ancestor outside the iframe (.email-detail-inline)
      const iframeEl = iframeRef.current;
      if (!iframeEl) return;
      let scroller: HTMLElement | null = iframeEl.parentElement;
      while (scroller) {
        const cs = window.getComputedStyle(scroller);
        const canScroll = (cs.overflowY === 'auto' || cs.overflowY === 'scroll')
          && scroller.scrollHeight > scroller.clientHeight;
        if (canScroll) break;
        scroller = scroller.parentElement;
      }
      if (!scroller) return;
      e.preventDefault();
      scroller.scrollBy({ top: e.deltaY, left: e.deltaX, behavior: 'auto' });
    };
    doc.addEventListener('wheel', handleIframeWheel, { passive: false });

    cleanupRef.current = () => {
      observer.disconnect();
      iframeWin?.removeEventListener('resize', rafResize);
      clearTimeout(timer1);
      clearTimeout(timer2);
      clearTimeout(timer3);
      imgs.forEach((img) => img.removeEventListener('load', resize));
      doc.removeEventListener('click', handleClick);
      doc.removeEventListener('keydown', handleIframeKeyDown);
      doc.removeEventListener('wheel', handleIframeWheel);
    };
  }, []);

  // sandbox keeps `allow-same-origin` (we read contentDocument for click
  // interception + ResizeObserver) but deliberately omits `allow-scripts`,
  // `allow-forms`, `allow-popups`, `allow-modals`, etc. Audit Codex
  // 2026-04-25 [F-XSS-06]: that combination neutralises script execution
  // and form-submission exfil even if the manual `<script>` strip above
  // misses something. Do NOT add allow-scripts — see the linked finding.
  return (
    <iframe
      ref={iframeRef}
      className="email-body-iframe"
      sandbox="allow-same-origin"
      srcDoc={processedHtml}
      onLoad={handleLoad}
      style={{ width: '100%', height: `${height}px`, border: 'none', background: 'transparent' }}
      title={t('email_detail_iframe_title')}
      aria-label={t('email_detail_iframe_aria')}
    />
  );
}


/**
 * Component to render email body with proper formatting.
 * HTML emails → sandboxed iframe (preserves original layout/styles).
 * Plain text / markdown → sanitized inline HTML.
 */
export function EmailBodyContent({ body, stripQuoted = false }: { body: string | null | undefined; stripQuoted?: boolean }) {
  const { t } = useTranslation('inbox');
  const isHtml = useMemo(() => isHtmlContent(body ?? ''), [body]);
  const [showQuoted, setShowQuoted] = useState(false);
  // Même typo que l'éditeur de réponse (préférence utilisateur) : police,
  // taille et interligne (1.4, cf. .draft-editor-content p) partagés entre le
  // corps reçu et la réponse. Style inline : prime sur la règle
  // .email-body-content d'EmailContentReader.css.
  const { fontFamilyCss, fontSizeCss } = useComposeFontPrefs();
  const bodyTypoStyle = useMemo(
    () => ({ fontFamily: fontFamilyCss, fontSize: fontSizeCss, lineHeight: 1.4 }),
    [fontFamilyCss, fontSizeCss],
  );

  if (!body) {
    return <div className="email-body-content" />;
  }

  if (isHtml) {
    const stripped = stripQuoted ? stripQuotedHtml(body) : body;
    // Du contenu cité/transféré a été retiré : on l'affiche derrière un toggle
    // « ··· » (comme le plain-text) au lieu de le perdre — crucial pour les
    // transferts (TR:/Fwd:) où le message transféré EST le contenu utile.
    const quotedRemoved = stripQuoted && stripped.trim().length < body.trim().length;
    return (
      <>
        <HtmlEmailIframe body={showQuoted ? body : stripped} />
        {quotedRemoved && (
          <div className="email-quoted-section">
            <button
              type="button"
              className="email-quoted-toggle"
              onClick={() => setShowQuoted(v => !v)}
              aria-label={showQuoted ? t('email_detail_quoted_hide', 'Masquer le message cité') : t('email_detail_quoted_show', 'Voir le message cité')}
            >
              ···
            </button>
          </div>
        )}
      </>
    );
  }

  const { clean, quoted } = stripQuotedContent(body);
  const sanitizedBody = sanitizeEmailBody(clean);
  const sanitizedQuoted = (!stripQuoted && quoted) ? sanitizeEmailBody(quoted) : null;

  return (
    <>
      <div
        className="email-body-content"
        style={bodyTypoStyle}
        dangerouslySetInnerHTML={{ __html: sanitizedBody }}
      />
      {sanitizedQuoted && (
        <div className="email-quoted-section">
          <button
            type="button"
            className="email-quoted-toggle"
            onClick={() => setShowQuoted(v => !v)}
            aria-label={showQuoted ? t('email_detail_quoted_hide', 'Masquer le message cité') : t('email_detail_quoted_show', 'Voir le message cité')}
          >
            ···
          </button>
          {showQuoted && (
            <div
              className="email-quoted-content"
              style={bodyTypoStyle}
              dangerouslySetInnerHTML={{ __html: sanitizedQuoted }}
            />
          )}
        </div>
      )}
    </>
  );
}

interface EmailDetailModalProps {
  emailId: string;
  isOpen: boolean;
  onClose: () => void;
  onDraftGenerated?: () => void;
  onDraftSaved?: () => void;
  onDraftDiscarded?: () => void;
  /** Render inline (no backdrop/modal overlay) for split-view */
  inline?: boolean;
  /** Called when user sends a reply (for Deep Focus stats tracking) */
  onReplySent?: (emailId: string) => void;
  /** Navigation arrows — "X of Y" Gmail-style */
  navInfo?: { current: number; total: number; hasPrev: boolean; hasNext: boolean } | null;
  onNavigatePrev?: () => void;
  onNavigateNext?: () => void;
  /** Expand inline panel into fullscreen modal */
  onExpand?: () => void;
  /** Render as expanded fullscreen modal (wider than default) */
  expanded?: boolean;
  /** External trigger to open reply/reply_all/forward composer (from keyboard shortcut) */
  triggerReplyType?: 'reply' | 'reply_all' | 'forward' | null;
  /** Called after triggerReplyType has been consumed */
  onTriggerReplyHandled?: () => void;
  /** Email labels from list view (for smart reply filtering) */
  emailLabels?: Array<{ name: string; color: string; confidence?: number }>;
  /** Notify parent when reply composer opens/closes */
  onComposerStateChange?: (open: boolean) => void;
  /** Current folder name for breadcrumb navigation */
  folderName?: string;
  /** Email of the active account — used to mark "You" on messages
   *  the logged-in user sent in the thread. Falls back to the JWT email
   *  when omitted, but multi-account callers should pass it explicitly. */
  accountEmail?: string;
  aiEnabled?: boolean;
  onUpgradeRequired?: () => void;
}

interface AttachmentMeta {
  id: string;
  filename: string;
  size: number;
  content_type: string;
}

const EMAIL_BODY_RETRY_DELAYS_MS = [3000, 7000, 14000, 30000] as const;

export interface EmailDetail {
  id: string;
  messageId: string;
  threadId: string;
  sender: string;
  senderName: string;
  senderEmail: string;
  recipient: string;
  to: string[];
  cc: string[];
  subject: string;
  body: string;
  bodyFetchPending?: boolean;
  providerUnavailable?: boolean;
  needsReauth?: boolean;
  receivedAt: string;
  isSent?: boolean;
  labels?: Array<{ name: string; color: string }>;
  attachments?: AttachmentMeta[];
  meeting_meta?: {
    summary: string;
    dtstart: string | null;
    dtend: string | null;
    location: string;
    organizer: string;
    kind?: 'invite' | 'appointment';
    provider?: string | null;
    reschedule_url?: string | null;
    cancel_url?: string | null;
    tz_label?: string | null;
  } | null;
}

function formatDate(dateString: string): string {
  return formatGmailDateTime(dateString, i18n.language);
}

/**
 * Transform snake_case API response to camelCase
 */
function transformApiResponse(apiData: Record<string, unknown>): EmailDetail {
  const sender = apiData.sender as string || '';
  return {
    id: apiData.id as string,
    messageId: (apiData.message_id || apiData.id) as string,
    threadId: (apiData.thread_id || apiData.conversation_id || '') as string,
    sender: sender,
    senderName: (apiData.sender_name || '') as string,
    senderEmail: (apiData.sender_email || sender) as string,
    recipient: (apiData.recipient || '') as string,
    to: (apiData.to || []) as string[],
    cc: (apiData.cc || []) as string[],
    subject: apiData.subject as string,
    body: (apiData.body_html || apiData.body || '') as string,
    bodyFetchPending: apiData.body_fetch_pending === true,
    providerUnavailable: apiData.provider_unavailable === true,
    needsReauth: apiData.needs_reauth === true,
    receivedAt: apiData.received_at as string,
    isSent: apiData.is_sent === true,
    attachments: (apiData.attachments as AttachmentMeta[]) || [],
    meeting_meta: (apiData.meeting_meta as EmailDetail['meeting_meta']) ?? null,
  };
}

/**
 * Decide whether a freshly-fetched email detail should replace the one already
 * in state. Makes body updates MONOTONIC: once we hold a populated body for an
 * email, a later response that lacks a body must NOT blank it.
 *
 * Why: opening an email fires several overlapping, un-aborted requests for the
 * same id — the initial headers-only read, the 3/7/14/30s silent body-retries,
 * and the `email_body_ready` WebSocket refetch. A slow EARLY request can
 * resolve with `body_html: null` AFTER a later request already delivered the
 * real body, blanking the reader to the "body failed" state (audit 2026-05-20:
 * a GET returned the full body_html in ~15ms yet the modal showed empty).
 *
 * Rules:
 *  - First load, or a different email id → always apply.
 *  - Same id, current has a non-empty body, incoming has none → keep current.
 *  - Otherwise (upgrade empty→body, refresh body→body, metadata-only) → apply.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function shouldReplaceEmailDetail(
  prev: EmailDetail | null,
  next: EmailDetail,
): boolean {
  if (!prev || prev.id !== next.id) return true;
  const prevHasBody = !!(prev.body && prev.body.trim());
  const nextHasBody = !!(next.body && next.body.trim());
  if (prevHasBody && !nextHasBody) return false;
  return true;
}

function getSenderAvatarColor(email: string): string {
  return generateColorFromString(email);
}

const EMAIL_ADDRESS_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;

export type IncomingReplyScope = {
  kind: 'me' | 'all';
  recipients: string[];
};

function comparableEmailAddress(value?: string | null): string {
  if (!value) return '';
  const angleMatch = value.match(/<([^<>]+)>/);
  const candidate = (angleMatch?.[1] || value).trim().replace(/^mailto:/i, '');
  return (candidate.match(EMAIL_ADDRESS_RE)?.[0] || value.match(EMAIL_ADDRESS_RE)?.[0] || candidate)
    .trim()
    .toLowerCase();
}

function splitRecipientValues(value?: string | string[] | null): string[] {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  return value.split(/[;,]/);
}

function getVisibleRecipients(message: {
  to?: string[];
  cc?: string[];
  recipient?: string;
}): Array<{ display: string; comparable: string }> {
  const rawRecipients = [
    ...splitRecipientValues(message.to),
    ...splitRecipientValues(message.cc),
  ];
  if (rawRecipients.length === 0) {
    rawRecipients.push(...splitRecipientValues(message.recipient));
  }

  const byAddress = new Map<string, { display: string; comparable: string }>();
  for (const raw of rawRecipients) {
    const display = String(raw || '').trim();
    const comparable = comparableEmailAddress(display);
    if (!display && !comparable) continue;
    const key = comparable || display.toLowerCase();
    if (!byAddress.has(key)) {
      byAddress.set(key, { display: display || comparable, comparable });
    }
  }
  return Array.from(byAddress.values());
}

// eslint-disable-next-line react-refresh/only-export-components
export function getIncomingReplyScope(
  message: {
    to?: string[];
    cc?: string[];
    recipient?: string;
    isSent?: boolean;
    sender?: string;
    senderEmail?: string;
  },
  userEmail?: string,
): IncomingReplyScope | null {
  const ownEmail = comparableEmailAddress(userEmail);
  if (!ownEmail) return null;

  const senderEmail = comparableEmailAddress(message.senderEmail || message.sender);
  if (message.isSent === true || (senderEmail && senderEmail === ownEmail)) {
    return null;
  }

  const recipients = getVisibleRecipients(message);
  if (recipients.length === 0) return null;

  const hasOtherVisibleRecipient = recipients.some(recipient => recipient.comparable !== ownEmail);
  return {
    kind: hasOtherVisibleRecipient ? 'all' : 'me',
    recipients: recipients.map(recipient => recipient.display),
  };
}

function canonicalEmailId(id?: string | null): string {
  return String(id || '').replace(/^sent:/, '');
}

function isSyntheticSentMessage(message: EmailDetail): boolean {
  const id = canonicalEmailId(message.id || message.messageId).toLowerCase();
  return message.isSent === true && (id.startsWith('reply-') || id.startsWith('compose-'));
}

function normalizeSubjectForDedupe(subject?: string | null): string {
  return String(subject || '')
    .replace(/^(?:re|fw|fwd|tr|rv)\s*:\s*/i, '')
    .trim()
    .toLowerCase();
}

function recipientKeyForDedupe(message: EmailDetail): string {
  return getVisibleRecipients(message)
    .map(recipient => recipient.comparable || recipient.display.trim().toLowerCase())
    .filter(Boolean)
    .sort()
    .join(',');
}

function isSyntheticTwinOfRealSent(synthetic: EmailDetail, real: EmailDetail): boolean {
  if (synthetic === real || real.isSent !== true || isSyntheticSentMessage(real)) return false;

  const syntheticSubject = normalizeSubjectForDedupe(synthetic.subject);
  const realSubject = normalizeSubjectForDedupe(real.subject);
  if (syntheticSubject && realSubject && syntheticSubject !== realSubject) return false;

  const syntheticSender = comparableEmailAddress(synthetic.senderEmail || synthetic.sender);
  const realSender = comparableEmailAddress(real.senderEmail || real.sender);
  if (syntheticSender && realSender && syntheticSender !== realSender) return false;

  const syntheticRecipients = recipientKeyForDedupe(synthetic);
  const realRecipients = recipientKeyForDedupe(real);
  if (syntheticRecipients && realRecipients && syntheticRecipients !== realRecipients) return false;

  const syntheticTime = Date.parse(synthetic.receivedAt || '');
  const realTime = Date.parse(real.receivedAt || '');
  if (Number.isFinite(syntheticTime) && Number.isFinite(realTime)) {
    return Math.abs(realTime - syntheticTime) <= 10 * 60 * 1000;
  }
  return true;
}

// eslint-disable-next-line react-refresh/only-export-components
export function reconcileConversationMessages(messages: EmailDetail[]): EmailDetail[] {
  const realSentMessages = messages.filter(message => message.isSent === true && !isSyntheticSentMessage(message));
  const withoutSupersededSynthetic = messages.filter(message => (
    !isSyntheticSentMessage(message)
    || !realSentMessages.some(real => isSyntheticTwinOfRealSent(message, real))
  ));

  const byId = new Map<string, EmailDetail>();
  for (const message of withoutSupersededSynthetic) {
    const key = canonicalEmailId(message.id || message.messageId);
    const existing = byId.get(key);
    if (!existing || (!isSyntheticSentMessage(message) && isSyntheticSentMessage(existing))) {
      byId.set(key, message);
    }
  }
  return Array.from(byId.values());
}

/* "Latest" is computed via max(receivedAt) instead of trusting the array
   index — the upstream sort can produce an unexpected order when a sibling
   has a missing/blank receivedAt (empty string sorts to top). Picking by
   max-date guarantees the right message gets the expanded treatment even
   with imperfect data. */
function latestByReceivedAt(messages: EmailDetail[]): EmailDetail | null {
  if (messages.length === 0) return null;
  return messages.reduce((acc, m) => {
    const accTs = Date.parse(acc.receivedAt || '') || 0;
    const mTs = Date.parse(m.receivedAt || '') || 0;
    return mTs >= accTs ? m : acc;
  }, messages[0]);
}

// eslint-disable-next-line react-refresh/only-export-components
export function getBodySnippet(body: string, maxLength = 120): string {
  if (!body) return '';
  // Strip <style>/<script> blocks INCLUDING their content first — otherwise the
  // CSS/JS inside (e.g. "#outlook a{ padding: 0; } body{ ... }" from newsletter
  // resets) survives tag-stripping and leaks into the thread card preview.
  let text = body
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, ' ')
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, ' ');
  // Strip trailing signature blocks BEFORE the generic tag-strip pass. Gmail,
  // Apple Mail and Outlook all wrap the signature in a container whose class
  // contains "signature" (gmail_signature, agentys-signature, email-signature…)
  // and it always trails the message body — so cutting from the first such
  // element to end-of-string drops it (and any nested markup) cleanly. Without
  // this a one-word reply ("ok") leaked the full signature into the thread card.
  text = text.replace(/<[a-z][^>]*class\s*=\s*["'][^"']*signature[^"']*["'][\s\S]*$/i, ' ');
  // Cut at the RFC 3676 plain-text signature delimiter ("-- " on its own line),
  // before whitespace normalisation collapses the newlines that anchor it.
  text = text.replace(/\n-- ?\r?\n[\s\S]*$/, '');
  // Strip remaining HTML tags
  text = text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  // Decode HTML entities (e.g. &#39; → ' , &amp; → &) using the DOM parser
  try {
    const entityDiv = document.createElement('div');
    entityDiv.innerHTML = text;
    text = (entityDiv.textContent ?? entityDiv.innerText ?? text).trim();
  } catch { /* fallback: leave text as-is */ }
  // Strip markdown formatting markers
  text = text.replace(/\*\*([^*]*)\*\*/g, '$1').replace(/\*([^*]*)\*/g, '$1');
  text = text.replace(/__([^_]*)__/g, '$1').replace(/_([^_]*)_/g, '$1');
  const { clean } = stripQuotedContent(text);
  const snippet = clean.replace(/\s+/g, ' ').trim();
  return snippet.length > maxLength ? snippet.slice(0, maxLength) + '\u2026' : snippet;
}

// Pièces jointes reçues : composant partagé (cartes type compose + aperçu
// intégré) — voir components/attachments/ReceivedAttachments.tsx.

export function ThreadMessageCard({
  message,
  isExpanded,
  isLatest,
  isLoadingBody,
  onToggle,
  onRetryBody,
  latestRef,
  userEmail,
}: {
  message: EmailDetail;
  isExpanded: boolean;
  isLatest: boolean;
  isLoadingBody: boolean;
  onToggle: () => void;
  onRetryBody?: () => void;
  latestRef?: React.RefObject<HTMLDivElement | null>;
  userEmail?: string;
}) {
  const { t } = useTranslation('inbox');
  const isSentByMe = message.isSent === true ||
    (!!userEmail && (message.senderEmail || '').toLowerCase() === userEmail.toLowerCase());
  // When the message is from the logged-in user, derive avatar identity from
  // the account email so all of "my" messages share the same color + initial,
  // even if some headers carry a display name and others don't.
  const name = isSentByMe
    ? (userEmail || message.senderEmail || '')
    : (message.senderName || message.senderEmail || '');
  const senderKey = isSentByMe
    ? (userEmail || '')
    : (message.senderEmail || message.senderName || '');
  // Two-letter initials via the shared Avatar helper so the fallback matches
  // the account chip ("You" → "CR", not a lone "C"; "Alexandre Sauvage" → "AS").
  const initial = getInitials(name || null, senderKey) || '?';
  const avatarBg = getSenderAvatarColor(senderKey);
  const hasBody = !!(message.body && message.body.trim());
  const needsReauth = message.needsReauth === true || message.providerUnavailable === true;
  const senderLabel = isSentByMe ? t('you_prefix') : (message.senderName || message.senderEmail);
  const replyScope = getIncomingReplyScope(message, userEmail);
  const replyScopeLabel = replyScope
    ? t(replyScope.kind === 'all' ? 'email_detail_reply_scope_all' : 'email_detail_reply_scope_me')
    : null;
  const replyScopeTitle = replyScope
    ? t('email_detail_reply_scope_title', { recipients: replyScope.recipients.join(', ') })
    : undefined;
  const formattedDate = formatDate(message.receivedAt);
  const threadCardAriaLabel = [senderLabel, replyScopeLabel, formattedDate].filter(Boolean).join(', ');

  if (!isExpanded) {
    const snippet = getBodySnippet(message.body, 120);
    return (
      <div
        className="thread-card thread-card-collapsed"
        onClick={onToggle}
        role="button"
        aria-label={threadCardAriaLabel}
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); } }}
        ref={isLatest ? latestRef : undefined}
      >
        <ContactAvatar
          email={isSentByMe ? (userEmail || null) : (message.senderEmail || null)}
          fallbackInitial={initial}
          fallbackBg={avatarBg}
          ariaLabel=""
        />
        <div className="thread-card-summary">
          <span className="thread-card-sender">{senderLabel}</span>
          {snippet && <span className="thread-card-snippet">{snippet}</span>}
        </div>
        {/* Scope pill on the right, next to the date: between the name and
            the preview it chopped the collapsed row into three fragments. */}
        {replyScope && replyScopeLabel && (
          <span
            className={`thread-reply-scope thread-reply-scope-${replyScope.kind}`}
            title={replyScopeTitle}
          >
            {replyScopeLabel}
          </span>
        )}
        <span className="thread-card-date">{formattedDate}</span>
      </div>
    );
  }

  return (
    <div className="thread-card thread-card-expanded" ref={isLatest ? latestRef : undefined}>
      <div
        className="thread-card-header"
        onClick={onToggle}
        role="button"
        aria-label={threadCardAriaLabel}
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); } }}
      >
        <ContactAvatar
          email={isSentByMe ? (userEmail || null) : (message.senderEmail || null)}
          fallbackInitial={initial}
          fallbackBg={avatarBg}
          ariaLabel=""
        />
        <div className="thread-card-header-meta">
          <div className="thread-card-sender-row">
            <span className="thread-card-sender">{senderLabel}</span>
            {replyScope && replyScopeLabel && (
              <span
                className={`thread-reply-scope thread-reply-scope-${replyScope.kind}`}
                title={replyScopeTitle}
              >
                {replyScopeLabel}
              </span>
            )}
          </div>
          {replyScope && replyScope.recipients.length > 0 && (
            <div className="thread-card-recipients">
              <span className="recipient-label">{t('email_detail_to')}</span>
              <span className="recipient-list">{replyScope.recipients.join(', ')}</span>
            </div>
          )}
        </div>
        <span className="thread-card-date">{formattedDate}</span>
      </div>
      <ReceivedAttachments attachments={message.attachments || []} emailId={message.id} />
      <div className="thread-card-body">
        {hasBody ? (
          <EmailBodyContent body={message.body} stripQuoted />
        ) : isLoadingBody && !needsReauth ? (
          <div className="email-detail-loading">
            <div className="loading-spinner" />
            <p>{t('email_detail_loading')}</p>
          </div>
        ) : (
          <div className="thread-card-body-empty" role="status">
            <p>{needsReauth ? t('email_detail_body_reauth') : t('email_detail_body_failed')}</p>
            {needsReauth ? (
              <button
                type="button"
                className="thread-card-body-retry"
                onClick={() => window.dispatchEvent(new Event('open-settings'))}
              >
                {t('email_detail_body_settings_link')}
              </button>
            ) : onRetryBody && (
              <button
                type="button"
                className="thread-card-body-retry"
                onClick={onRetryBody}
              >
                {t('email_detail_retry')}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Modal to display full email content
 * Used when clicking on an email reference in the ContextReferencePanel (AC3)
 */
export const EmailDetailModal = React.memo(function EmailDetailModal({
  emailId,
  isOpen,
  onClose,
  onDraftSaved,
  onDraftDiscarded,
  onDraftGenerated,
  inline = false,
  onReplySent,
  navInfo,
  onNavigatePrev,
  onNavigateNext,
  expanded = false,
  triggerReplyType,
  onTriggerReplyHandled,
  onComposerStateChange,
  accountEmail,
  aiEnabled = true,
  onUpgradeRequired,
}: EmailDetailModalProps) {
  const { t } = useTranslation('inbox');
  const { t: tErrors } = useTranslation('errors');
  const [email, setEmail] = useState<EmailDetail | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadDiagnostic, setLoadDiagnostic] = useState<EmailDetailLoadDiagnostic | null>(null);
  // P0-1 (2026-05-17): exponential-backoff retry state for 429 rate-limited
  // responses on GET /api/emails/<id>. `retryAfterSec` lets the banner show
  // a live countdown ("Server is busy — retrying in N s…") instead of the
  // raw `rate_limited` token that the backend returns in error.error.
  const [retryAfterSec, setRetryAfterSec] = useState<number | null>(null);

  // Coordinates with QuickStepsListHotkeys: while the detail modal is
  // open, the in-modal QuickStepsBar owns shortcut handling. The list
  // listener reads this dataset flag and defers, avoiding double-fire on
  // potentially-different emails (modal email vs. hovered list row).
  useEffect(() => {
    if (!isOpen) return;
    document.body.dataset.emailDetailOpen = 'true';
    return () => {
      delete document.body.dataset.emailDetailOpen;
    };
  }, [isOpen]);
  const [bodyPending, setBodyPending] = useState(false);
  const [thread, setThread] = useState<EmailDetail[]>([]);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  // Thread sibling messages may come back from /thread without a body (DB cache
  // miss → body_html and body_text both null). Track which siblings are
  // currently being lazy-fetched so the expanded card can show a spinner
  // instead of a silent empty area. The ref is the dedup gate (so the
  // callback stays referentially stable); the state is what drives the UI.
  const loadingMessageIdsRef = useRef<Set<string>>(new Set());
  const [loadingMessageIds, setLoadingMessageIds] = useState<Set<string>>(new Set());
  const [replySentFlash, setReplySentFlash] = useState(false);
  const loadDiagnosticMessage = useMemo(() => {
    if (!loadDiagnostic) return null;
    if (loadDiagnostic.kind === 'provider_slow') {
      return t('email_detail_provider_slow');
    }
    if (loadDiagnostic.kind === 'backend_ok') {
      return t('email_detail_backend_ok', { latency: loadDiagnostic.latencyMs });
    }
    if (loadDiagnostic.kind === 'backend_unhealthy') {
      return t('email_detail_backend_unhealthy', {
        status: loadDiagnostic.status,
        latency: loadDiagnostic.latencyMs,
      });
    }
    return t('email_detail_backend_unknown');
  }, [loadDiagnostic, t]);
  const latestMessageRef = useRef<HTMLDivElement>(null);
  const expandInitializedRef = useRef<string | null>(null);
  const composerContextExpandedRef = useRef(false);
  const [showReplyComposer, _setShowReplyComposer] = useState(false);
  const setShowReplyComposer = useCallback((open: boolean) => {
    _setShowReplyComposer(open);
    onComposerStateChange?.(open);
  }, [onComposerStateChange]);
  const [replyType, setReplyType] = useState<'reply' | 'reply_all' | 'forward'>('reply');
  const [isClosing, setIsClosing] = useState(false);
  const [aiStage] = useState<AIStage>('idle');
  const [composerPrefillBody, setComposerPrefillBody] = useState('');
  const [composerAutoPrompt, setComposerAutoPrompt] = useState('');
  const replyComposerRef = useRef<HTMLDivElement>(null);
  const inlineScrollRef = useRef<HTMLDivElement>(null);
  const modalContentRef = useRef<HTMLDivElement>(null);
  const footerRef = useRef<HTMLDivElement>(null);
  const [rsvpLoading, setRsvpLoading] = useState<string | null>(null);
  const [calendarStatus, setCalendarStatus] = useState<{
    state: 'idle' | 'loading' | 'free' | 'conflict' | 'unavailable';
    conflictTitles?: string[];
  }>({ state: 'idle' });
  const [showJumpPill, setShowJumpPill] = useState(false);
  const [showScrollDownPill, setShowScrollDownPill] = useState(false);
  const [composerHighlight, setComposerHighlight] = useState(false);
  const focusTrapRef = useFocusTrap(isOpen && !inline);
  const emailIdRef = useRef(emailId);
  emailIdRef.current = emailId;
  // Track in-flight fetch to dedupe StrictMode's double-invoke effect in dev
  // (and guard against any other source of back-to-back re-fetches for the same id).
  const inFlightFetchIdRef = useRef<string | null>(null);
  // P0-1: abort the previous /api/emails/<id> GET when the user clicks another
  // email or closes the modal. Without this, a slow request for the old email
  // can still resolve and stomp the newly-selected email's state.
  const inFlightAbortRef = useRef<AbortController | null>(null);
  // Pending backoff timer + countdown interval — cleared on emailId change,
  // close, or successful fetch to prevent leaked timers.
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryCountdownRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Per-emailId rate-limit on email_body_ready handler. Defense in depth against
  // a runaway WS-refetch loop: incident 2026-05-04 ran the same email through
  // 890 fetches in 4 minutes (~6 req/s) when the backend kept emitting
  // email_body_ready for an email that couldn't be persisted. Backend is the
  // primary fix (only emit on real change); this cap keeps the blast radius
  // bounded if a similar regression slips through.
  const wsEventLogRef = useRef<Map<string, number[]>>(new Map());

  // Merge thread + current email into a chronological conversation (null = single email)
  // Map-based dedup: if thread already contains the current email, avoid duplicates
  const conversationMessages = useMemo(() => {
    if (!email || thread.length === 0) return null;
    const byId = new Map<string, EmailDetail>();
    for (const msg of thread) byId.set(canonicalEmailId(msg.id || msg.messageId), msg);
    byId.set(canonicalEmailId(email.id || email.messageId), email); // current email always wins (freshest data)
    return reconcileConversationMessages(Array.from(byId.values())).sort(
      (a, b) => (a.receivedAt || '').localeCompare(b.receivedAt || '')
    );
  }, [email, thread]);

  // Lazy-fetch the body of a thread sibling whose body came back empty from
  // /api/emails/<id>/thread (DB cache had headers only). Hits /api/emails/<id>
  // which schedules the backend's background IMAP body fetch — but that fetch
  // is async, so the FIRST response is usually still empty. We mirror
  // fetchEmail's silent-retry cadence so once the backend thread populates
  // body_html, the next poll merges it into `thread` and the expanded card
  // re-renders with real content. The last retry covers slow
  // provider fetches observed in prod where Gmail took ~30s to return a body.
  const loadMessageBody = useCallback(async (messageId: string) => {
    if (loadingMessageIdsRef.current.has(messageId)) return;
    loadingMessageIdsRef.current.add(messageId);
    setLoadingMessageIds(prev => {
      const next = new Set(prev);
      next.add(messageId);
      return next;
    });

    const tryOnce = async (): Promise<boolean> => {
      try {
        const response = handleAuthResponse(await fetch(
          `${API_URL}/api/emails/${encodeURIComponent(messageId)}`,
          { headers: { ...getAuthHeaders() } }
        ));
        if (!response.ok) return false;
        const data = await response.json();
        const hasContent = !!(data.body_html || data.body);
        if (!hasContent) return false;
        const transformed = transformApiResponse(data);
        if (emailIdRef.current === messageId) {
          // Lazy-load was triggered for the main email itself (rare — happens
          // when expand-all is hit before fetchEmail filled the body). Mirror
          // fetchEmail's success path.
          setEmail(transformed);
          updateCachedEmailDetail(messageId, data);
        } else {
          setThread(prev => prev.map(m => (m.id === messageId ? transformed : m)));
        }
        return true;
      } catch {
        return false;
      }
    };

    const isStillRelevant = () => loadingMessageIdsRef.current.has(messageId);

    try {
      if (await tryOnce()) return;
      for (const delay of EMAIL_BODY_RETRY_DELAYS_MS) {
        await new Promise<void>(resolve => setTimeout(resolve, delay));
        if (!isStillRelevant()) return; // modal closed or switched emails
        if (await tryOnce()) return;
      }
    } finally {
      loadingMessageIdsRef.current.delete(messageId);
      setLoadingMessageIds(prev => {
        const next = new Set(prev);
        next.delete(messageId);
        return next;
      });
    }
  }, []);

  // Auto-expand latest message when conversation first loads for this emailId.
  // Guard with a ref so background data refreshes (setEmail calls) don't reset
  // user-initiated expansions after the initial load.
  useEffect(() => {
    if (conversationMessages && conversationMessages.length > 0 && expandInitializedRef.current !== emailId) {
      expandInitializedRef.current = emailId;
      const latestMsg = latestByReceivedAt(conversationMessages);
      if (!latestMsg) return;
      setExpandedMessages(new Set([latestMsg.id]));
      // If the auto-expanded message has no body yet (thread DB cache miss),
      // kick off the lazy fetch so the user sees a spinner instead of a blank
      // card on first render. Skip when the latest is the main email — that
      // path is already handled by fetchEmail's silent retries.
      if (latestMsg.id !== emailId && (!latestMsg.body || !latestMsg.body.trim())) {
        loadMessageBody(latestMsg.id);
      }
      requestAnimationFrame(() => {
        latestMessageRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      });
    }
  }, [conversationMessages, emailId, loadMessageBody]);

  // Opening the reply composer with every thread card collapsed leaves zero
  // context above the draft — the user can't see the message they're replying
  // to. Re-expand the latest message in that case, once per composer opening
  // (the ref), so a collapse the user makes WHILE composing is respected.
  // Covers all three open paths: footer buttons, R/F shortcut, saved-draft
  // auto-open.
  useEffect(() => {
    if (!showReplyComposer) {
      composerContextExpandedRef.current = false;
      return;
    }
    if (composerContextExpandedRef.current) return;
    if (!conversationMessages || conversationMessages.length === 0) return;
    composerContextExpandedRef.current = true;
    // Context already visible (≥1 card open): nothing to expand, and no
    // body fetch either — fetching for a card that stays collapsed would be
    // wasted network round-trips (silent-retry cadence included).
    if (expandedMessages.size > 0) return;
    const latestMsg = latestByReceivedAt(conversationMessages);
    if (!latestMsg) return;
    setExpandedMessages(new Set([latestMsg.id]));
    if (latestMsg.id !== emailId && (!latestMsg.body || !latestMsg.body.trim())) {
      loadMessageBody(latestMsg.id);
    }
  }, [showReplyComposer, conversationMessages, emailId, loadMessageBody, expandedMessages]);

  const handleClose = useCallback(() => {
    setIsClosing(true);
    setTimeout(() => {
      setIsClosing(false);
      onClose();
    }, 150);
  }, [onClose]);

  // P0-1 helper: clear any pending backoff timers / countdowns. Called when
  // the user switches emails, clicks the manual Retry button, or closes the
  // modal — keeps the auto-retry loop bounded to a single emailId at a time.
  const cancelPendingRetries = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    if (retryCountdownRef.current) {
      clearInterval(retryCountdownRef.current);
      retryCountdownRef.current = null;
    }
    setRetryAfterSec(null);
  }, []);

  const fetchEmail = useCallback(async (forceRefresh = false) => {
    const requestedId = emailId; // Capture at call time

    // Dedup concurrent fetches for the same emailId (e.g. React StrictMode
    // double-invoke in dev). Force refresh bypasses the guard so users can
    // still trigger a manual reload.
    if (!forceRefresh && inFlightFetchIdRef.current === requestedId) {
      return;
    }
    // P0-1: abort any prior in-flight request from a previous emailId so a
    // slow response can't land on the newly-selected email.
    if (inFlightAbortRef.current) {
      try { inFlightAbortRef.current.abort(); } catch { /* noop */ }
      inFlightAbortRef.current = null;
    }
    // Manual retry clears the backoff state so the user sees an immediate
    // "Loading…" instead of "retrying in N s…" stuck behind the spinner.
    cancelPendingRetries();
    inFlightFetchIdRef.current = requestedId;

    setError(null);
    setLoadDiagnostic(null);
    setIsLoading(true);
    setBodyPending(false);

    try {
      // Stale-while-revalidate: show cached data instantly, refresh in background
      const cached = forceRefresh ? null : await getCachedEmailDetail(emailId);
      const cachedBody = cached && (cached.body_html || cached.body);
      // Don't serve stale cache when attachments are expected but metadata is missing
      const cachedRaw = cached as unknown as Record<string, unknown> | null;
      const cachedAttOk = !cachedRaw?.has_attachments || ((cachedRaw?.attachments as AttachmentMeta[])?.length > 0 && (cachedRaw?.attachments as AttachmentMeta[])?.[0]?.filename);
      if (cached && cachedBody && cachedAttOk) {
        if (emailIdRef.current !== requestedId) return;
        const cachedTransformed = transformApiResponse(cached as unknown as Record<string, unknown>);
        setEmail(cachedTransformed);
        setIsLoading(false);
        // Fetch thread for cached emails too
        if (cachedTransformed.threadId) {
          fetch(`${API_URL}/api/emails/${encodeURIComponent(emailId)}/thread`, { headers: { ...getAuthHeaders() } })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
              if (data?.emails && emailIdRef.current === requestedId) {
                const others = (data.emails as Record<string, unknown>[])
                  .map(transformApiResponse)
                  .filter(e => e.id !== requestedId)
                  .sort((a, b) => (a.receivedAt || '').localeCompare(b.receivedAt || ''));
                setThread(others);
              }
            })
            // Audit Cluster D (2026-05-11) F-05: previously silent. Log so the
            // failure shows up in DevTools / Sentry instead of vanishing.
            .catch(silentFailLog('emaildetail-thread-refetch-cached'));
        }
        // Email bodies are immutable enough for the cache TTL. Avoid a hidden
        // backend/provider revalidation on every reopen; explicit refresh still
        // bypasses this path via `forceRefresh`.
        if (inFlightFetchIdRef.current === requestedId) {
          inFlightFetchIdRef.current = null;
        }
        return;
      }
    } catch {
      // Cache read failed — proceed to full fetch
    }

    const controller = new AbortController();
    inFlightAbortRef.current = controller;
    const timeoutId = setTimeout(() => controller.abort(), 60000);

    try {
      // Single-shot retry on transient 5xx (background sync vs detail fetch
      // contention has been seen at ~17:02 UTC 2026-05-04 — see lessons.md
      // "[Frontend] Transient 5xx on /api/emails/<id>"). 4xx are not retried
      // (they're definitive: 401 → re-auth flow, 404 → email gone).
      const fetchOnce = () => fetch(`${API_URL}/api/emails/${encodeURIComponent(emailId)}`, {
        signal: controller.signal,
        headers: { ...getAuthHeaders() },
      });
      let response = handleAuthResponse(await fetchOnce());
      if (!response.ok && response.status >= 500 && response.status < 600) {
        // Log enough context for ops/Codex to triage if the retry also fails.
        const peek = await response.clone().text().catch(() => '');
        console.warn(
          `[EmailDetail] transient ${response.status} on first try for email ${emailId} — body=${peek.slice(0, 200)}; retrying once after 500ms`,
        );

        await new Promise<void>((res) => setTimeout(res, 500));
        if (emailIdRef.current !== requestedId) return; // user moved on
        response = handleAuthResponse(await fetchOnce());
      }

      // P0-1 (2026-05-17): handle 429 rate_limited with exponential backoff.
      // Backend returns either `Retry-After` (seconds) or `{retry_after: N}`
      // in the JSON body. Cap delays at 15s and attempt up to 5 times before
      // surfacing a definitive error. The retry loop respects the same
      // emailId-change + AbortController guards as the rest of the function.
      if (response.status === 429) {
        const backoffSchedule = [1, 2, 4, 8, 15]; // seconds, max 5 attempts
        for (let attempt = 0; attempt < backoffSchedule.length; attempt++) {
          if (emailIdRef.current !== requestedId || controller.signal.aborted) return;
          const errBody = await response.clone().json().catch(() => ({} as Record<string, unknown>));
          const headerRa = Number.parseInt(response.headers.get('Retry-After') || '', 10);
          const bodyRa = typeof (errBody as { retry_after?: unknown }).retry_after === 'number'
            ? (errBody as { retry_after: number }).retry_after
            : NaN;
          const serverHint = Number.isFinite(headerRa) ? headerRa : (Number.isFinite(bodyRa) ? bodyRa : NaN);
          const waitSec = Math.min(
            15,
            Number.isFinite(serverHint) && serverHint > 0 ? serverHint : backoffSchedule[attempt],
          );
          // Drive a per-second countdown so the banner reads "retrying in N s…".
          setRetryAfterSec(waitSec);
          setError('rate_limited');
          setLoadDiagnostic({ kind: 'provider_slow' });
          setIsLoading(false);
          if (retryCountdownRef.current) clearInterval(retryCountdownRef.current);
          retryCountdownRef.current = setInterval(() => {
            setRetryAfterSec((prev) => (prev !== null && prev > 1 ? prev - 1 : prev));
          }, 1000);
          // Sleep with abort-awareness.
          const slept = await new Promise<boolean>((resolve) => {
            const t = setTimeout(() => resolve(true), waitSec * 1000);
            retryTimerRef.current = t;
            controller.signal.addEventListener('abort', () => {
              clearTimeout(t);
              resolve(false);
            }, { once: true });
          });
          if (retryCountdownRef.current) {
            clearInterval(retryCountdownRef.current);
            retryCountdownRef.current = null;
          }
          retryTimerRef.current = null;
          if (!slept) return;
          if (emailIdRef.current !== requestedId) return;
          setIsLoading(true);
          response = handleAuthResponse(await fetchOnce());
          if (response.status !== 429) {
            setRetryAfterSec(null);
            if (response.ok) {
              setError(null);
              setLoadDiagnostic(null);
            }
            break;
          }
        }
        if (response.status === 429) {
          // Exhausted attempts — surface a definitive error so the user can
          // try again manually instead of looping forever.
          setRetryAfterSec(null);
          throw new Error('rate_limited');
        }
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        // Surface the response body in console for diagnostics — the visible
        // message stays user-friendly via tErrors when no .error key.
        if (response.status >= 500) {
          console.error(
            `[EmailDetail] ${response.status} for email ${emailId} after retry — payload=${JSON.stringify(errorData).slice(0, 300)}`,
          );
          setLoadDiagnostic(await probeBackendHealth());
        }
        throw new Error(errorData.error || `Erreur HTTP ${response.status}`);
      }

      // Race guard: discard if user switched to another email
      if (emailIdRef.current !== requestedId) return;

      const responseData = await response.json();
      // Debug: check if body_html is available
      if (!responseData.body_html) {
        console.debug('[EmailDetail] body_html is missing for email', emailId, '— falling back to plain text body (text-only email).');
      }
      // API returns data directly (not wrapped in { data: ... })
      const transformedData = transformApiResponse(responseData);
      // Monotonic apply — never let a later empty response blank a body we
      // already have for this email (see shouldReplaceEmailDetail).
      setEmail(prev => (shouldReplaceEmailDetail(prev, transformedData) ? transformedData : prev));
      setLoadDiagnostic(null);

      // Fetch thread if email belongs to a conversation
      if (transformedData.threadId) {
        fetch(`${API_URL}/api/emails/${encodeURIComponent(emailId)}/thread`, { headers: { ...getAuthHeaders() } })
          .then(r => r.ok ? r.json() : null)
          .then(data => {
            if (data?.emails && emailIdRef.current === requestedId) {
              const others = (data.emails as Record<string, unknown>[])
                .map(transformApiResponse)
                .filter(e => e.id !== transformedData.id)
                .sort((a, b) => (a.receivedAt || '').localeCompare(b.receivedAt || ''));
              setThread(others);
            }
          })
          // Audit Cluster D F-05: log instead of silent.
          .catch(silentFailLog('emaildetail-thread-fetch'));
      }

      // Email may return headers-only initially (body fetched in background).
      // Also retry when email has attachments but metadata is missing (background fetch needed).
      // Also retry when a meeting invite has no meeting_meta yet (.ics being downloaded in bg).
      // Silent retries pick up the body/attachments/meeting data after the backend
      // finishes its provider fetch. Respect body_fetch_pending so slow Gmail
      // fetches don't become a false "content failed" state.
      const _missingBody = !responseData.body_html && !responseData.body;
      const _missingAttachments = responseData.has_attachments && (!responseData.attachments || responseData.attachments.length === 0 || !responseData.attachments[0]?.filename);
      const _isMeetingInviteResponse = isMeetingInvite(responseData as unknown as EmailDetailType);
      const _missingMeetingMeta = _isMeetingInviteResponse && !responseData.meeting_meta;
      if ((_missingBody || _missingAttachments || _missingMeetingMeta) && emailIdRef.current === requestedId) {
        setBodyPending(true);
        const silentRetry = (attempt: number) => {
          const delay = EMAIL_BODY_RETRY_DELAYS_MS[attempt - 1] ?? EMAIL_BODY_RETRY_DELAYS_MS[EMAIL_BODY_RETRY_DELAYS_MS.length - 1];
          setTimeout(() => {
            if (emailIdRef.current !== requestedId) { setBodyPending(false); return; }
            fetch(`${API_URL}/api/emails/${encodeURIComponent(emailId)}`, { headers: { ...getAuthHeaders() } })
              .then(res => res.ok ? res.json() : null)
              .then(fresh => {
                if (!fresh || emailIdRef.current !== requestedId) { setBodyPending(false); return; }
                const _hasContent = fresh.body_html || fresh.body;
                const _freshBodyPending = fresh.body_fetch_pending === true;
                const _hasRealAttachments = !fresh.has_attachments || (fresh.attachments?.length > 0 && fresh.attachments[0]?.filename);
                const _hasMeetingMeta = !_isMeetingInviteResponse || !!fresh.meeting_meta;
                const _bodyResolved = !_missingBody || _hasContent;
                const _attachmentsResolved = !_missingAttachments || _hasRealAttachments;
                const _meetingResolved = !_missingMeetingMeta || _hasMeetingMeta;
                if (_bodyResolved && _attachmentsResolved && _meetingResolved) {
                  const _next = transformApiResponse(fresh);
                  setEmail(prev => (shouldReplaceEmailDetail(prev, _next) ? _next : prev));
                  setBodyPending(false);
                } else if (_attachmentsResolved && _meetingResolved && !_hasContent && !_freshBodyPending && attempt >= 2) {
                  const _next = transformApiResponse(fresh);
                  setEmail(prev => (shouldReplaceEmailDetail(prev, _next) ? _next : prev));
                  setBodyPending(false);
                } else if (attempt < EMAIL_BODY_RETRY_DELAYS_MS.length) {
                  silentRetry(attempt + 1);
                } else {
                  const nextEmail = transformApiResponse(fresh);
                  if (!_hasContent && _freshBodyPending) nextEmail.bodyFetchPending = false;
                  setEmail(prev => (shouldReplaceEmailDetail(prev, nextEmail) ? nextEmail : prev));
                  setBodyPending(false);
                }
              })
              .catch(() => {
                if (attempt < EMAIL_BODY_RETRY_DELAYS_MS.length) silentRetry(attempt + 1);
                else setBodyPending(false);
              });
          }, delay);
        };
        silentRetry(1);
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        // P0-1: aborts triggered by switching emails are expected — silence
        // them. Only the 60s timeout should surface as a load_timeout.
        if (emailIdRef.current !== requestedId) return;
        setLoadDiagnostic(await probeBackendHealth());
        setError(tErrors('load_timeout'));
        return;
      }
      if (emailIdRef.current !== requestedId) return;
      const isNetworkError = err instanceof TypeError && err.message === 'Failed to fetch';
      if (isNetworkError) {
        setLoadDiagnostic(await probeBackendHealth());
      }
      const errorMessage = isNetworkError
        ? tErrors('server_unreachable')
        : err instanceof Error ? err.message : tErrors('load_error');
      setError(errorMessage);
      setEmail(null);
    } finally {
      clearTimeout(timeoutId);
      if (emailIdRef.current === requestedId) {
        setIsLoading(false);
      }
      if (inFlightFetchIdRef.current === requestedId) {
        inFlightFetchIdRef.current = null;
      }
      if (inFlightAbortRef.current === controller) {
        inFlightAbortRef.current = null;
      }
    }
  }, [emailId, cancelPendingRetries, tErrors]);

  useEffect(() => {
    if (isOpen && emailId) {
      setThread([]);
      setExpandedMessages(new Set());
      expandInitializedRef.current = null;
      loadingMessageIdsRef.current.clear();
      setLoadingMessageIds(new Set());
      fetchEmail();
    }
    // P0-1: cancel pending backoff retries + abort in-flight requests when
    // emailId changes or the modal closes — prevents zombie 429-loops from
    // mutating state for the wrong email.
    return () => {
      cancelPendingRetries();
      if (inFlightAbortRef.current) {
        try { inFlightAbortRef.current.abort(); } catch { /* noop */ }
        inFlightAbortRef.current = null;
      }
    };
  }, [isOpen, emailId, fetchEmail, cancelPendingRetries]);

  useEffect(() => {
    if (inline) return; // Skip Escape handling for inline mode
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        // Defer to an inner popover that owns Escape (Quick Steps palette,
        // label picker, etc.) — it must dismiss itself first without this
        // modal also closing. See utils/escapeOwner.ts.
        if (hasEscapeOwner()) return;
        if (showReplyComposer) {
          setShowReplyComposer(false);
        } else {
          handleClose();
        }
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose, showReplyComposer, inline]);

  // Re-fetch when backend signals that background body fetch completed
  useEffect(() => {
    if (!isOpen) return;
    const ws = getWebSocketClient();
    const unsubscribe = ws.subscribe((event) => {
      if (event.type !== 'email_body_ready' || event.data.email_id !== emailId) return;
      // Rate-limit: max 3 receipts per email_id in any 30s window. The backend
      // should never emit this many for the same email (each emit means the
      // body genuinely advanced), so hitting this cap means something upstream
      // is misbehaving — log it loudly and stop refetching to avoid the storm
      // documented in incident 2026-05-04.
      const now = Date.now();
      const log = wsEventLogRef.current;
      const recent = (log.get(emailId) || []).filter(t => now - t < 30_000);
      if (recent.length >= 3) {
        console.warn(`[EmailDetailModal] Throttled email_body_ready for ${emailId} (received ${recent.length + 1} in 30s)`);
        recent.push(now);
        log.set(emailId, recent.slice(-10));
        return;
      }
      recent.push(now);
      log.set(emailId, recent);
      // Silent re-fetch: body is now ready in backend cache, update without showing spinner
      fetch(`${API_URL}/api/emails/${encodeURIComponent(emailId)}`, { headers: { ...getAuthHeaders() } })
        .then(res => res.ok ? res.json() : null)
        .then(fresh => {
          if (fresh && emailIdRef.current === emailId && (fresh.body_html || fresh.body)) {
            const _next = transformApiResponse(fresh);
            setEmail(prev => (shouldReplaceEmailDetail(prev, _next) ? _next : prev));
            updateCachedEmailDetail(emailId, fresh);
          }
        })
        // Audit Cluster D F-05: log instead of silent.
        .catch(silentFailLog('emaildetail-revalidate'));
    });
    return unsubscribe;
  }, [isOpen, emailId, fetchEmail]);

  // Reset reply composer when modal closes
  useEffect(() => {
    if (!isOpen) {
      setShowReplyComposer(false);
    }
  }, [isOpen]);

  const handleJumpToComposer = useCallback(() => {
    replyComposerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setComposerHighlight(true);
    setTimeout(() => {
      const ta = replyComposerRef.current?.querySelector('textarea');
      ta?.focus();
    }, 200);
    setTimeout(() => setComposerHighlight(false), 800);
  }, []);

  // Option 2 — Show jump pill when composer is below the visible area
  useEffect(() => {
    if (!showReplyComposer || !replyComposerRef.current) {
      setShowJumpPill(false);
      return;
    }
    const root = inline ? inlineScrollRef.current : modalContentRef.current;
    const observer = new IntersectionObserver(
      ([entry]) => setShowJumpPill(!entry.isIntersecting),
      { root, threshold: 0.2 }
    );
    observer.observe(replyComposerRef.current);
    return () => observer.disconnect();
  }, [showReplyComposer, inline]);

  // Show scroll-down pill when action footer is below the visible area (inline only —
  // in modal mode the footer is a sibling outside the scroll area, always pinned)
  useEffect(() => {
    if (!inline || showReplyComposer || !email || isLoading || error) {
      setShowScrollDownPill(false);
      return;
    }
    if (!footerRef.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => setShowScrollDownPill(!entry.isIntersecting),
      { root: inlineScrollRef.current, threshold: 0.1 }
    );
    observer.observe(footerRef.current);
    return () => observer.disconnect();
  }, [inline, showReplyComposer, email, isLoading, error]);

  const handleScrollToBottom = useCallback(() => {
    footerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, []);

  // Option 3 — Keyboard shortcut G: scroll to composer and focus textarea
  // Uses document (not window) to catch events even when an inner div has focus.
  // Note: keys inside the sandboxed email iframe don't bubble — that's expected.
  useEffect(() => {
    if (!isOpen || !showReplyComposer) return;
    const handleJumpKey = (e: KeyboardEvent) => {
      if (e.key !== 'g' && e.key !== 'G') return;
      // Don't fire if any modifier is held — Ctrl+G means "expand notes" in
      // composers, not "jump to composer" (audit Ctrl+G LOW "capture-phase
      // listeners stack across modals").
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return;
      // Skip when typing inside a contenteditable rich body (TipTap, etc.) —
      // otherwise typing the literal letter "g" steals focus into the composer
      // (audit Ctrl+G HIGH "bare g fires inside contenteditable").
      if (target?.isContentEditable) return;
      e.preventDefault();
      handleJumpToComposer();
    };
    document.addEventListener('keydown', handleJumpKey);
    return () => document.removeEventListener('keydown', handleJumpKey);
  }, [isOpen, showReplyComposer, handleJumpToComposer]);

  // Reset reply composer when switching to a different email
  useEffect(() => {
    setShowReplyComposer(false);
  }, [emailId]);

  // Auto-open ReplyComposer when a local reply draft exists for this email
  useEffect(() => {
    if (isOpen && email && !showReplyComposer) {
      const saved = getReplyDraftForEmail(emailId);
      if (saved) {
        setReplyType('reply');
        setShowReplyComposer(true);
        setTimeout(() => {
          replyComposerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }, 150);
      }
    }
  }, [isOpen, email, emailId]);

  // React to external reply/forward trigger (keyboard shortcut R/F)
  useEffect(() => {
    if (triggerReplyType && isOpen && email) {
      setReplyType(triggerReplyType === 'forward' ? 'forward' : triggerReplyType === 'reply_all' ? 'reply_all' : 'reply');
      setShowReplyComposer(true);
      onTriggerReplyHandled?.();
      setTimeout(() => {
        replyComposerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
      }, 100);
    }
  }, [triggerReplyType, isOpen, email, onTriggerReplyHandled]);

const handleReply = useCallback((type: 'reply' | 'reply_all' | 'forward') => {
    setReplyType(type);
    setShowReplyComposer(true);
    setTimeout(() => {
      replyComposerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }, 100);
  }, []);

  const handleRsvp = useCallback(async (response: 'accepted' | 'declined' | 'tentative') => {
    if (!email?.id || rsvpLoading) return;
    setRsvpLoading(response);
    const targetId = email.id;
    try {
      const result = await rsvpMeeting(targetId, response);
      if (result.ok) {
        const msgKey = response === 'accepted'
          ? 'meeting_rsvp_accepted'
          : response === 'declined'
          ? 'meeting_rsvp_declined'
          : 'meeting_rsvp_tentative';
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: { message: t(msgKey), type: 'success' },
        }));
        // After a successful RSVP the calendar event becomes the source of
        // truth, so the invitation email is no longer useful in the inbox.
        // Delete it (Trash, not permanent) and close the panel.
        apiClient.deleteEmail(targetId).catch(err => {
          console.warn('[RSVP] post-RSVP delete failed', targetId, err);
        });
        onClose();
      } else {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: { message: t('meeting_rsvp_error'), type: 'error' },
        }));
      }
    } catch (err) {
      // The backend returns specific non-2xx codes for diagnosable failures
      // (403 missing scope, 422 not-an-invite, 404 event-not-found) — surface a
      // precise message instead of the generic "RSVP failed" for all of them.
      let msgKey = 'meeting_rsvp_error';
      if (err instanceof ApiError) {
        if (err.status === 403) msgKey = 'meeting_rsvp_reauth';
        else if (err.status === 422) msgKey = 'meeting_rsvp_not_invite';
        else if (err.status === 404) msgKey = 'meeting_rsvp_event_not_found';
      }
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: t(msgKey), type: 'error' },
      }));
    } finally {
      setRsvpLoading(null);
    }
  }, [email?.id, rsvpLoading, t, onClose]);

  // Appointment-confirmation actions (Calendly). These don't touch our backend
  // — Reschedule/Cancel open the booking tool's own self-service pages, and
  // Add-to-calendar downloads an .ics the user's calendar app imports.
  const openSelfServiceLink = useCallback((url?: string | null) => {
    if (!url) return;
    window.open(url, '_blank', 'noopener,noreferrer');
  }, []);

  const handleAddToCalendar = useCallback(() => {
    const meta = email?.meeting_meta;
    if (!meta) return;
    downloadAppointmentIcs(meta, email?.subject || '');
  }, [email?.meeting_meta, email?.subject]);

  const handleReplySend = useCallback(() => {
    setShowReplyComposer(false);
    setComposerPrefillBody('');
    setComposerAutoPrompt('');

    // Flash "reply sent" indicator
    setReplySentFlash(true);
    setTimeout(() => setReplySentFlash(false), 3000);

    // Re-fetch thread after a short delay (Gmail needs time to surface sent message)
    setTimeout(() => {
      if (emailIdRef.current === emailId && email?.threadId) {
        fetch(`${API_URL}/api/emails/${encodeURIComponent(emailId)}/thread`, { headers: { ...getAuthHeaders() } })
          .then(r => r.ok ? r.json() : null)
          .then(data => {
            if (data?.emails && emailIdRef.current === emailId) {
              const others = (data.emails as Record<string, unknown>[])
                .map(transformApiResponse)
                .filter(e => e.id !== emailId)
                .sort((a, b) => (a.receivedAt || '').localeCompare(b.receivedAt || ''));
              setThread(others);
              // Auto-expand the newest message (the reply just sent)
              if (others.length > 0) {
                const latestId = others[others.length - 1].id;
                setExpandedMessages(prev => new Set([...prev, latestId]));
              }
            }
          })
          // Audit Cluster D F-05: log instead of silent — particularly
          // important here because users notice when the sent reply
          // doesn't appear in the thread after sending.
          .catch(silentFailLog('emaildetail-thread-refetch-after-reply'));
      }
    }, 2000);

    // Notify parent for list refresh (but do NOT close the modal)
    onReplySent?.(emailId);
  }, [onReplySent, emailId, email]);

  const handleReplyCancel = useCallback(() => {
    setShowReplyComposer(false);
    setComposerPrefillBody('');
    setComposerAutoPrompt('');
  }, []);

  // Convert EmailDetail to EmailDetailType for ReplyComposer
  const emailForComposer: EmailDetailType | null = email ? {
    id: email.id,
    sender: email.senderEmail || email.sender,
    sender_name: email.senderName || null,
    subject: email.subject,
    received_at: email.receivedAt,
    has_attachments: (email.attachments && email.attachments.length > 0) || false,
    attachments: email.attachments,
    conversation_id: email.threadId || null,
    is_read: true,
    body: email.body,
    to: email.to.length > 0 ? email.to : (email.recipient ? [email.recipient] : []),
    cc: email.cc,
  } : null;

  // Calendar conflict detection: fetch events for the meeting day and report
  // free / conflict / unavailable based on time-slot overlap. Hook MUST be
  // declared before the `if (!isOpen) return null` guard below to satisfy
  // rules-of-hooks — early-returning above a hook causes inconsistent ordering.
  const _meetingMeta = email?.meeting_meta ?? null;
  const _isMeeting = isMeetingInvite(email as unknown as EmailDetailType ?? null);
  const _isAppointment = _meetingMeta?.kind === 'appointment';
  useEffect(() => {
    // Appointments are already booked — there's nothing to free/busy-check.
    if (!_isMeeting || _isAppointment || !_meetingMeta?.dtstart) {
      setCalendarStatus({ state: 'idle' });
      return;
    }
    const start = new Date(_meetingMeta.dtstart);
    const end = _meetingMeta.dtend ? new Date(_meetingMeta.dtend) : new Date(start.getTime() + 30 * 60000);
    if (isNaN(start.getTime()) || isNaN(end.getTime())) {
      setCalendarStatus({ state: 'idle' });
      return;
    }
    const dayStart = new Date(start); dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(start); dayEnd.setHours(23, 59, 59, 999);
    const ctrl = new AbortController();
    setCalendarStatus({ state: 'loading' });
    fetch(`${API_URL}/api/calendar/events?start=${encodeURIComponent(dayStart.toISOString())}&end=${encodeURIComponent(dayEnd.toISOString())}&limit=50`, {
      headers: { ...getAuthHeaders() },
      signal: ctrl.signal,
    })
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        if (!data) { setCalendarStatus({ state: 'unavailable' }); return; }
        const events = (data.events || []) as Array<{ start?: string; end?: string; title?: string; summary?: string; transparency?: string }>;
        const startMs = start.getTime();
        const endMs = end.getTime();
        const ownTitle = (_meetingMeta.summary || '').trim().toLowerCase();
        const conflicts = events.filter(ev => {
          const evStart = ev.start ? new Date(ev.start).getTime() : NaN;
          const evEnd = ev.end ? new Date(ev.end).getTime() : evStart;
          if (isNaN(evStart)) return false;
          const evTitle = ((ev.title || ev.summary) || '').trim().toLowerCase();
          if (ownTitle && evTitle && evTitle === ownTitle) return false;
          if (ev.transparency === 'transparent') return false;
          return evStart < endMs && evEnd > startMs;
        });
        if (conflicts.length === 0) setCalendarStatus({ state: 'free' });
        else setCalendarStatus({ state: 'conflict', conflictTitles: conflicts.map(c => c.title || c.summary || '').filter(Boolean).slice(0, 2) });
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return;
        setCalendarStatus({ state: 'unavailable' });
      });
    return () => ctrl.abort();
  }, [_isMeeting, _isAppointment, _meetingMeta?.dtstart, _meetingMeta?.dtend, _meetingMeta?.summary]);

  if (!isOpen) {
    return null;
  }

  const headerContent = (
    <div className="email-detail-header">
      <div className="email-detail-header-left">
        {/* P3-24 (2026-05-17): show the localized no-subject placeholder so the
            detail header no longer falls back to the French "(Sans objet)" via
            backend payload — or, worse, an empty <h2>.
            QA 2026-06-10: while the detail is still loading (`email` null) the
            placeholder flashed "(No subject)" for every email. Render nothing
            until the email object exists; the placeholder is only for emails
            that truly have an empty subject. */}
        <h2 className="email-detail-title">{email ? ((email.subject || '').trim() || t('no_subject')) : ''}</h2>
        {conversationMessages && conversationMessages.length > 1 && (
          <span className="thread-count-badge" aria-label={`${conversationMessages.length} messages`}>
            ({conversationMessages.length})
          </span>
        )}
        {email?.labels && email.labels.length > 0 && (
          <LabelBadgeGroup labels={email.labels} maxVisible={3} size="small" />
        )}
      </div>
      <div className="email-detail-header-actions">
        {navInfo && (
          <div className="email-nav-arrows">
            <button
              className="email-nav-btn"
              onClick={onNavigatePrev}
              disabled={!navInfo.hasPrev}
              aria-label={t('email_detail_prev')}
              title={t('email_detail_prev_title')}
              data-testid="prev-email"
            >
              <ChevronUpIcon size={14} />
            </button>
            <button
              className="email-nav-btn"
              onClick={onNavigateNext}
              disabled={!navInfo.hasNext}
              aria-label={t('email_detail_next')}
              title={t('email_detail_next_title')}
              data-testid="next-email"
            >
              <ChevronDownIcon size={14} />
            </button>
          </div>
        )}
        <button
          className="email-detail-close"
          onClick={onClose}
          aria-label={t('email_detail_close')}
          title={t('email_detail_close_title')}
          data-testid="email-detail-close"
        >
          <CloseIcon />
        </button>
      </div>
    </div>
  );

  const isMeeting = isMeetingInvite(email as unknown as EmailDetailType ?? null);

  const meetingMeta = email?.meeting_meta ?? null;

  const meetingInfo = (() => {
    if (!meetingMeta?.dtstart) return null;
    const start = new Date(meetingMeta.dtstart);
    if (isNaN(start.getTime())) return null;
    const end = meetingMeta.dtend ? new Date(meetingMeta.dtend) : null;
    const endValid = end && !isNaN(end.getTime());
    const lang = i18n.language;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const startDay = new Date(start);
    startDay.setHours(0, 0, 0, 0);
    const dayDiff = Math.round((startDay.getTime() - today.getTime()) / 86400000);
    let dayLabel: string;
    if (dayDiff === 0) dayLabel = t('meeting_today');
    else if (dayDiff === 1) dayLabel = t('meeting_tomorrow');
    else if (dayDiff === -1) dayLabel = t('meeting_yesterday');
    else if (dayDiff > 1 && dayDiff < 7) {
      dayLabel = start.toLocaleDateString(lang, { weekday: 'long' });
      dayLabel = dayLabel.charAt(0).toUpperCase() + dayLabel.slice(1);
    } else {
      // "Wed May 27th" (EN ordinal) / "mer. 27 mai" (FR day-first).
      const wd = new Intl.DateTimeFormat(lang, { weekday: 'short' }).format(start);
      dayLabel = `${wd} ${formatShortDateFromDate(start, lang)}`;
    }
    const timeFmt = (d: Date) => d.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit', hour12: false });
    const startTime = timeFmt(start);
    let timeRange = startTime;
    let durationLabel: string | null = null;
    if (endValid && end) {
      const sameDay = start.toDateString() === end.toDateString();
      timeRange = sameDay ? `${startTime} – ${timeFmt(end)}` : `${startTime} – ${formatShortDateFromDate(end, lang)}, ${timeFmt(end)}`;
      const minutes = Math.round((end.getTime() - start.getTime()) / 60000);
      if (minutes > 0 && minutes < 24 * 60) {
        if (minutes < 60) durationLabel = `${minutes} min`;
        else if (minutes % 60 === 0) durationLabel = `${minutes / 60} h`;
        else durationLabel = `${Math.floor(minutes / 60)} h ${minutes % 60}`;
      }
    }
    return { dayLabel, timeRange, durationLabel, isToday: dayDiff === 0 };
  })();

  const isVideoMeeting = !!meetingMeta?.location && /(teams|meet|zoom|webex|skype)/i.test(meetingMeta.location);

  const meetingCard = (isMeeting || _isAppointment) && meetingMeta && (meetingInfo || meetingMeta.location || meetingMeta.organizer || _isAppointment) ? (
    <div className={`meeting-card${meetingInfo?.isToday ? ' meeting-card--today' : ''}`}>
      {meetingInfo && (
        <div className="meeting-card-header">
          <span className="meeting-card-when">
            <span className="meeting-card-day">{meetingInfo.dayLabel}</span>
            <span className="meeting-card-dot">·</span>
            <span className="meeting-card-time">{meetingInfo.timeRange}</span>
          </span>
          {meetingInfo.durationLabel && (
            <span className="meeting-card-duration">{meetingInfo.durationLabel}</span>
          )}
        </div>
      )}
      {(meetingMeta.summary || email?.subject) && (
        <div className="meeting-card-title">{meetingMeta.summary || email?.subject}</div>
      )}
      <div className="meeting-card-meta">
        {meetingMeta.location && (
          <div className="meeting-card-row">
            {isVideoMeeting ? (
              <svg className="meeting-card-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect x="1.5" y="4" width="9" height="8" rx="1.3"/><path d="M10.5 7l3.5-2v6l-3.5-2z"/>
              </svg>
            ) : (
              <svg className="meeting-card-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M8 14s5-4.5 5-8.5a5 5 0 0 0-10 0c0 4 5 8.5 5 8.5z"/><circle cx="8" cy="5.5" r="1.8"/>
              </svg>
            )}
            <span className="meeting-card-text">{meetingMeta.location}</span>
          </div>
        )}
        {meetingMeta.organizer && (
          <div className="meeting-card-row">
            <svg className="meeting-card-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="8" cy="5.5" r="2.5"/><path d="M2.5 13.5c.8-2.4 3-3.8 5.5-3.8s4.7 1.4 5.5 3.8"/>
            </svg>
            <span className="meeting-card-text">{meetingMeta.organizer}</span>
            <span className="meeting-card-badge">{t('meeting_organizer')}</span>
          </div>
        )}
        {_isAppointment && meetingMeta.tz_label && (
          <div className="meeting-card-row">
            <svg className="meeting-card-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="8" cy="8" r="6.5"/><path d="M8 8V4.5M8 8l3 1.5M1.6 8h12.8"/>
            </svg>
            <span className="meeting-card-text">{meetingMeta.tz_label}</span>
          </div>
        )}
        {!_isAppointment && calendarStatus.state !== 'idle' && calendarStatus.state !== 'unavailable' && (
          <div className={`meeting-card-row meeting-card-status meeting-card-status--${calendarStatus.state}`}>
            {calendarStatus.state === 'loading' ? (
              <svg className="meeting-card-icon meeting-card-icon--spin" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
                <path d="M8 1.5a6.5 6.5 0 1 1-6.5 6.5" />
              </svg>
            ) : calendarStatus.state === 'free' ? (
              <svg className="meeting-card-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M3 8.2l3 3 7-7" />
              </svg>
            ) : (
              <svg className="meeting-card-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M8 1.5L1 14h14L8 1.5z" /><path d="M8 6v3.5M8 11.5v.4" />
              </svg>
            )}
            <span className="meeting-card-text">
              {calendarStatus.state === 'loading' && t('meeting_calendar_checking')}
              {calendarStatus.state === 'free' && t('meeting_calendar_free')}
              {calendarStatus.state === 'conflict' && (
                (calendarStatus.conflictTitles?.length ?? 0) <= 1
                  ? t('meeting_calendar_conflict_one', { title: calendarStatus.conflictTitles?.[0] || '' })
                  : t('meeting_calendar_conflict_many', { count: calendarStatus.conflictTitles?.length || 0 })
              )}
            </span>
          </div>
        )}
      </div>
      {_isAppointment ? (
        <div className="meeting-card-rsvp">
          {meetingMeta.dtstart && (
            <button
              className="meeting-rsvp-btn meeting-rsvp-accept meeting-rsvp-primary"
              onClick={handleAddToCalendar}
              aria-label={t('appointment_add_to_calendar')}
            >
              <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="3" width="12" height="11" rx="1.5"/><path d="M2 6.5h12M5 1.5v3M11 1.5v3M8 9v3M6.5 10.5h3"/>
              </svg>
              {t('appointment_add_to_calendar')}
            </button>
          )}
          {meetingMeta.reschedule_url && (
            <button
              className="meeting-rsvp-btn meeting-rsvp-maybe"
              onClick={() => openSelfServiceLink(meetingMeta.reschedule_url)}
              aria-label={t('appointment_reschedule')}
            >
              <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d="M13.5 8a5.5 5.5 0 1 1-1.7-3.97M13.5 2v3h-3"/>
              </svg>
              {t('appointment_reschedule')}
            </button>
          )}
          {meetingMeta.cancel_url && (
            <button
              className="meeting-rsvp-btn meeting-rsvp-decline"
              onClick={() => openSelfServiceLink(meetingMeta.cancel_url)}
              aria-label={t('appointment_cancel')}
            >
              <CloseIcon size={14} />
              {t('appointment_cancel')}
            </button>
          )}
        </div>
      ) : (
        <div className="meeting-card-rsvp">
          <button
            className="meeting-rsvp-btn meeting-rsvp-accept meeting-rsvp-primary"
            onClick={() => handleRsvp('accepted')}
            disabled={!!rsvpLoading}
            aria-label={t('meeting_accept')}
          >
            {rsvpLoading === 'accepted' ? (
              <span className="meeting-rsvp-spinner" aria-hidden="true" />
            ) : (
              <CheckIcon size={15} />
            )}
            {t('meeting_accept')}
          </button>
          <button
            className="meeting-rsvp-btn meeting-rsvp-maybe"
            onClick={() => handleRsvp('tentative')}
            disabled={!!rsvpLoading}
            aria-label={t('meeting_tentative')}
          >
            {rsvpLoading === 'tentative' ? (
              <span className="meeting-rsvp-spinner" aria-hidden="true" />
            ) : (
              <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="8" cy="8" r="6"/><path d="M8 5v3l2 2"/>
              </svg>
            )}
            {t('meeting_tentative')}
          </button>
          <button
            className="meeting-rsvp-btn meeting-rsvp-decline"
            onClick={() => handleRsvp('declined')}
            disabled={!!rsvpLoading}
            aria-label={t('meeting_decline')}
          >
            {rsvpLoading === 'declined' ? (
              <span className="meeting-rsvp-spinner" aria-hidden="true" />
            ) : (
              <CloseIcon size={14} />
            )}
            {t('meeting_decline')}
          </button>
        </div>
      )}
    </div>
  ) : null;

  const footerContent = !showReplyComposer && !error ? (
    <div className="email-action-footer" ref={footerRef}>
      <div className="email-action-footer-actions">
        <button
          className="email-reply-btn"
          onClick={() => handleReply('reply')}
          disabled={!email}
          data-testid="reply-button"
          title={t('email_detail_reply_title')}
          aria-label={t('email_detail_reply_title')}
        >
          <svg aria-hidden="true" className="reply-icon" width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M6.5 3L2.5 7L6.5 11"/><path d="M2.5 7H10.5C12.1569 7 13.5 8.3431 13.5 10V13"/></svg>
          {t('email_detail_reply')}
        </button>
        <button
          className="email-reply-btn"
          onClick={() => handleReply('reply_all')}
          disabled={!email}
          data-testid="reply-all-button"
          title={t('email_detail_reply_all')}
          aria-label={t('email_detail_reply_all')}
        >
          <svg aria-hidden="true" className="reply-icon" width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M6.5 3L2.5 7L6.5 11"/><path d="M9.5 3L5.5 7L9.5 11"/><path d="M5.5 7H10.5C12.1569 7 13.5 8.3431 13.5 10V13"/></svg>
          {t('email_detail_reply_all')}
        </button>
        <button
          className="email-reply-btn"
          onClick={() => handleReply('forward')}
          disabled={!email}
          data-testid="forward-button"
          title={t('email_detail_forward_title')}
          aria-label={t('email_detail_forward_title')}
        >
          <svg aria-hidden="true" className="reply-icon" width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9.5 3L13.5 7L9.5 11"/><path d="M13.5 7H5.5C3.8431 7 2.5 8.3431 2.5 10V13"/></svg>
          {t('email_detail_forward')}
        </button>
        <QuickStepsBar emailId={email?.id ?? null} onExecuted={onClose} />
      </div>
      <QuickStepsPalette emailId={email?.id ?? null} onExecuted={onClose} />
    </div>
  ) : null;

  const emailContent = (
    <div className={`email-detail-body ${showReplyComposer ? 'compact' : ''}`}>
      {isLoading && (
        <div className="email-detail-loading">
          <div className="loading-spinner" />
          <p>{t('email_detail_loading')}</p>
        </div>
      )}

      {error && (
        <div className="email-detail-error">
          {error === 'rate_limited' ? (
            <p>
              {retryAfterSec !== null
                ? t('email_detail_rate_limited_retrying', { seconds: retryAfterSec })
                : t('email_detail_rate_limited')}
            </p>
          ) : (
            <p>{t('email_detail_error_prefix')} {error}</p>
          )}
          {loadDiagnosticMessage && (
            <p className="email-detail-diagnostic">{loadDiagnosticMessage}</p>
          )}
          <button onClick={() => fetchEmail(true)} className="retry-button">{t('email_detail_retry')}</button>
        </div>
      )}

      {!isLoading && !error && !email && (
        <div className="email-detail-error">
          <p>{t('email_detail_load_failed')}</p>
          <button onClick={() => fetchEmail(true)} className="retry-button">{t('email_detail_retry')}</button>
        </div>
      )}

      {!isLoading && !error && email && (
        <>
        {conversationMessages ? (
          /* THREAD VIEW: chronological conversation cards */
          <div className="email-conversation-view">
            {meetingCard}
            {conversationMessages.length > 1 && (
              /* Single toggle: two permanent buttons were heavy chrome for a
                 2-message thread. The label reflects the action still
                 available — "expand all" until everything is open, then
                 "collapse all". */
              <div className="thread-toggle-bar">
                <button
                  className="thread-toggle-btn"
                  onClick={() => {
                    const allExpanded = conversationMessages.every(m => expandedMessages.has(m.id));
                    if (allExpanded) {
                      // QA 2026-06-10: "Collapse all" used to keep the latest
                      // message expanded (Set([latestId])), which reads as the
                      // button not working on 2-message threads. Collapse means
                      // collapse — every message folds to its summary row.
                      setExpandedMessages(new Set());
                    } else {
                      setExpandedMessages(new Set(conversationMessages.map(m => m.id)));
                      // Kick off lazy fetches for any sibling whose body is empty
                      conversationMessages.forEach(m => {
                        if (!m.body || !m.body.trim()) {
                          loadMessageBody(m.id);
                        }
                      });
                    }
                  }}
                >
                  {conversationMessages.every(m => expandedMessages.has(m.id))
                    ? t('collapse_all')
                    : t('expand_all')}
                </button>
              </div>
            )}
            {conversationMessages.map((msg, idx) => {
              const isLatest = idx === conversationMessages.length - 1;
              const isExp = expandedMessages.has(msg.id);
              const msgHasBody = !!(msg.body && msg.body.trim());
              const msgNeedsReauth = msg.needsReauth === true || msg.providerUnavailable === true;
              return (
                <ThreadMessageCard
                  key={msg.id}
                  message={msg}
                  isExpanded={isExp}
                  isLatest={isLatest}
                  isLoadingBody={loadingMessageIds.has(msg.id) || (msg.bodyFetchPending === true && !msgNeedsReauth)}
                  onToggle={() => {
                    setExpandedMessages(prev => {
                      const next = new Set(prev);
                      const willExpand = !next.has(msg.id);
                      if (willExpand) {
                        next.add(msg.id);
                      } else {
                        next.delete(msg.id);
                      }
                      return next;
                    });
                    // Trigger a lazy fetch on first expand if the body is missing
                    if (!isExp && !msgHasBody) {
                      loadMessageBody(msg.id);
                    }
                  }}
                  onRetryBody={() => loadMessageBody(msg.id)}
                  latestRef={isLatest ? latestMessageRef : undefined}
                  userEmail={accountEmail || getJwtEmail() || undefined}
                />
              );
            })}
            {replySentFlash && (
              <div className="reply-sent-flash" role="status" aria-live="polite">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6L9 17l-5-5"/></svg>
                {t('reply_sent_flash')}
              </div>
            )}
          </div>
        ) : (
          /* SINGLE EMAIL VIEW: unchanged original layout */
          <div className="email-original-section">
            {meetingCard}
            <div className="email-original-sender">
              <ContactAvatar
                email={email.senderEmail || null}
                fallbackInitial={getInitials(email.senderName || null, email.senderEmail || '') || '?'}
                fallbackBg={getSenderAvatarColor(email.senderEmail || email.senderName || '')}
                ariaLabel={email.senderName || email.senderEmail}
              />
              <span className="email-original-from">
                <span className="email-original-from-name">
                  {email.senderName || email.senderEmail}
                </span>
                {email.senderName && email.senderEmail && (
                  <span className="email-original-from-address">
                    &lt;{email.senderEmail}&gt;
                  </span>
                )}
              </span>
              {email.receivedAt && (
                <span className="email-original-date">{formatDate(email.receivedAt)}</span>
              )}
            </div>
            {email.to && email.to.length > 0 && (
              <div className="email-original-recipients">
                <span className="recipient-label">{t('email_detail_to', 'À')}</span>
                <span className="recipient-list">{email.to.join(', ')}</span>
              </div>
            )}
            {email.cc && email.cc.length > 0 && (
              <div className="email-original-recipients">
                <span className="recipient-label">Cc</span>
                <span className="recipient-list">{email.cc.join(', ')}</span>
              </div>
            )}
            <ReceivedAttachments attachments={email.attachments || []} emailId={email.id} />
            <div className="email-original-body-container">
              {!email.body || !email.body.trim() ? (
                (email.needsReauth === true || email.providerUnavailable === true) ? (
                  <div className="email-body-empty-warning">
                    <span className="warning-icon">⚠</span>
                    <p>{t('email_detail_body_reauth')}</p>
                    <p className="warning-hint">{t('email_detail_body_hint')} <button className="warning-link" onClick={() => window.dispatchEvent(new Event('open-settings'))}>{t('email_detail_body_settings_link')}</button>.</p>
                  </div>
                ) : bodyPending || email.bodyFetchPending ? (
                  <div className="email-detail-loading">
                    <div className="loading-spinner" />
                    <p>{t('email_detail_loading')}</p>
                  </div>
                ) : email.attachments && email.attachments.length > 0 && email.attachments[0]?.filename ? (
                  <p className="email-body-attachment-only">{t('email_detail_body_attachment_only')}</p>
                ) : (
                  <div className="email-body-empty-warning">
                    <span className="warning-icon">⚠</span>
                    <p>{t('email_detail_body_failed')}</p>
                    <p className="warning-hint">{t('email_detail_body_hint')} <button className="warning-link" onClick={() => window.dispatchEvent(new Event('open-settings'))}>{t('email_detail_body_settings_link')}</button>.</p>
                    <button onClick={() => fetchEmail(true)} className="retry-button">{t('email_detail_retry')}</button>
                  </div>
                )
              ) : (
                <EmailBodyContent body={email.body} />
              )}
            </div>
          </div>
        )}
        </>
      )}
    </div>
  );

  const composerContent = showReplyComposer && emailForComposer ? (
    <div ref={replyComposerRef} className={`email-reply-composer-container${composerHighlight ? ' composer-jump-highlight' : ''}`}>
      {/* BUG-S001 fix (2026-05-16): isolate ReplyComposer crashes (e.g. the
          intermittent TanStack Query `getOptimisticResult on null` race when
          the composer mounts before its QueryClient observer is fully ready)
          so the rest of the app stays usable. Keying by emailId+replyType
          forces a clean remount when switching emails or reply types —
          avoiding stale query subscriptions referencing a torn-down observer. */}
      <ErrorBoundary>
        <ReplyComposer
          key={`${emailForComposer.id}-${replyType}`}
          email={emailForComposer}
          replyType={replyType}
          accountEmail={accountEmail || getJwtEmail() || undefined}
          onSend={handleReplySend}
          onCancel={handleReplyCancel}
          onDraftSaved={onDraftSaved}
          onDraftDiscarded={onDraftDiscarded}
          onDraftGenerated={onDraftGenerated}
          prefillBody={composerPrefillBody}
          autoGeneratePrompt={composerAutoPrompt}
          aiEnabled={aiEnabled}
          onUpgradeRequired={onUpgradeRequired}
        />
      </ErrorBoundary>
    </div>
  ) : null;


  // Inline mode: render without backdrop/modal overlay (for split-view)
  if (inline) {
    return (
      <div className={`email-detail-inline ${showReplyComposer ? 'composing' : ''}`} ref={inlineScrollRef}>
        <AIProgressBar stage={aiStage} visible={aiStage !== 'idle'} />
        {headerContent}
        {emailContent}

        {composerContent}
        {footerContent}

        {showJumpPill && (
          <button
            className="jump-to-composer-pill scroll-down-pill"
            onClick={handleJumpToComposer}
            title={t('jump_to_draft_title')}
            aria-label={t('jump_to_draft_aria')}
          >
            <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 16 16" aria-hidden="true">
              <line x1="8" y1="2" x2="8" y2="12"/><polyline points="4,8 8,13 12,8"/>
            </svg>
          </button>
        )}

        {showScrollDownPill && (
          <button
            className="jump-to-composer-pill scroll-down-pill"
            onClick={handleScrollToBottom}
            aria-label={t('scroll_to_bottom', 'Défiler vers le bas')}
          >
            <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 16 16" aria-hidden="true">
              <line x1="8" y1="2" x2="8" y2="12"/><polyline points="4,8 8,13 12,8"/>
            </svg>
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={`email-detail-modal${isClosing ? ' closing' : ''}`} role="dialog" aria-modal="true" aria-label={t('email_detail_aria')} ref={focusTrapRef} data-testid="email-detail">
      <div className="email-detail-backdrop" onMouseDown={handleClose} />
      <div ref={modalContentRef} className={`email-detail-content ${showReplyComposer ? 'composing' : ''}${expanded ? ' expanded' : ''}`} onMouseDown={e => e.stopPropagation()}>
        <AIProgressBar stage={aiStage} visible={aiStage !== 'idle'} />
        {headerContent}
        {emailContent}

        {composerContent}
        {footerContent}

        {showJumpPill && (
          <button
            className="jump-to-composer-pill scroll-down-pill"
            onClick={handleJumpToComposer}
            title={t('jump_to_draft_title')}
            aria-label={t('jump_to_draft_aria')}
          >
            <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 16 16" aria-hidden="true">
              <line x1="8" y1="2" x2="8" y2="12"/><polyline points="4,8 8,13 12,8"/>
            </svg>
          </button>
        )}

      </div>
    </div>
  );
});
