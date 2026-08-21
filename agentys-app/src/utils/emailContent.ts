import DOMPurify from 'dompurify';

type ParsedCssColor = { r: number; g: number; b: number; a: number };

function clampColorChannel(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(255, value));
}

function parseCssAlpha(value: string | undefined): number {
  if (!value) return 1;
  const trimmed = value.trim();
  if (trimmed.endsWith('%')) {
    return Math.max(0, Math.min(1, Number(trimmed.slice(0, -1)) / 100));
  }
  return Math.max(0, Math.min(1, Number(trimmed)));
}

function parseCssColor(value: string | null | undefined): ParsedCssColor | null {
  const raw = (value || '').trim().toLowerCase();
  if (!raw) return null;
  if (raw === 'transparent') return { r: 0, g: 0, b: 0, a: 0 };

  const hex = raw.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hex) {
    const body = hex[1].length === 3
      ? hex[1].split('').map(ch => ch + ch).join('')
      : hex[1];
    return {
      r: parseInt(body.slice(0, 2), 16),
      g: parseInt(body.slice(2, 4), 16),
      b: parseInt(body.slice(4, 6), 16),
      a: 1,
    };
  }

  const commaRgb = raw.match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+%?))?\s*\)$/);
  if (commaRgb) {
    return {
      r: clampColorChannel(Number(commaRgb[1])),
      g: clampColorChannel(Number(commaRgb[2])),
      b: clampColorChannel(Number(commaRgb[3])),
      a: parseCssAlpha(commaRgb[4]),
    };
  }

  const spaceRgb = raw.match(/^rgba?\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+%?))?\s*\)$/);
  if (spaceRgb) {
    return {
      r: clampColorChannel(Number(spaceRgb[1])),
      g: clampColorChannel(Number(spaceRgb[2])),
      b: clampColorChannel(Number(spaceRgb[3])),
      a: parseCssAlpha(spaceRgb[4]),
    };
  }

  return null;
}

function isTransparentCssColor(value: string | null | undefined): boolean {
  const color = parseCssColor(value);
  return !color || color.a <= 0.05;
}

function relativeLuminance(color: ParsedCssColor): number {
  const channels = [color.r, color.g, color.b].map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.03928
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return (0.2126 * channels[0]) + (0.7152 * channels[1]) + (0.0722 * channels[2]);
}

function contrastRatio(a: ParsedCssColor, b: ParsedCssColor): number {
  const lighter = Math.max(relativeLuminance(a), relativeLuminance(b));
  const darker = Math.min(relativeLuminance(a), relativeLuminance(b));
  return (lighter + 0.05) / (darker + 0.05);
}

export function getReadableTextColorForLowContrast(
  textColor: string | null | undefined,
  backgroundColor: string | null | undefined,
): '#111827' | '#ffffff' | null {
  const text = parseCssColor(textColor);
  const background = parseCssColor(backgroundColor);
  if (!text || !background || background.a <= 0.05) return null;

  if (contrastRatio(text, background) >= 4.5) return null;

  const dark = parseCssColor('#111827')!;
  const light = parseCssColor('#ffffff')!;
  return contrastRatio(dark, background) >= contrastRatio(light, background)
    ? '#111827'
    : '#ffffff';
}

function getEffectiveBackgroundColor(element: Element, win: Window): string | null {
  let current: Element | null = element;
  while (current) {
    const background = win.getComputedStyle(current).backgroundColor;
    if (!isTransparentCssColor(background)) return background;
    current = current.parentElement;
  }

  return '#ffffff';
}

export function repairLowContrastEmailText(doc: Document, root: ParentNode = doc.body): number {
  const win = doc.defaultView;
  if (!win || !doc.body) return 0;

  const elements: Element[] = [];
  if (root instanceof win.Element) elements.push(root);
  elements.push(...Array.from(root.querySelectorAll('*')));

  let changed = 0;
  elements.forEach((element) => {
    if (!(element instanceof win.HTMLElement)) return;
    const text = (element.textContent || '').replace(/\u00A0/g, ' ').trim();
    if (!text) return;

    const style = win.getComputedStyle(element);
    if (style.display === 'none' || style.visibility === 'hidden') return;

    const background = getEffectiveBackgroundColor(element, win);
    const readableColor = getReadableTextColorForLowContrast(style.color, background);
    if (!readableColor) return;

    if (
      element.style.getPropertyValue('color') === readableColor &&
      element.style.getPropertyPriority('color') === 'important'
    ) {
      return;
    }

    element.style.setProperty('color', readableColor, 'important');
    changed += 1;
  });

  return changed;
}

/**
 * Fit-to-width factor for an HTML email rendered in a fixed-width pane.
 *
 * Fixed-width emails (a 600px layout table, a `<div style="width:…px">`, a long
 * unbreakable token) overflow a narrow reading pane and get clipped on the right
 * by the iframe's `overflow-x:hidden` — the "email coupé" bug. We measure the
 * real content width vs. the available viewport width and scale the document
 * down to fit, exactly like a mobile client's "fit to width".
 *
 * Realistic emails (content up to ~10x the pane width) fit edge-to-edge with no
 * clipping, because the scaled width equals the available width exactly. The
 * `floor` only guards genuinely pathological content (e.g. a >3000px email in a
 * narrow pane) from collapsing toward 0 — those rare outliers stay legible-ish
 * and may clip the far edge, which beats an invisible 2% scale.
 *
 * @param available    Inner width of the iframe viewport (CSS px).
 * @param contentWidth Natural width the content needs (max scrollWidth, CSS px).
 * @param floor        Lower bound so degenerate widths never scale toward 0.
 * @returns A scale in [floor, 1]. Returns 1 (no scaling) when the viewport is
 *          not measurable yet, a value is non-finite, or the content already
 *          fits (+1px tolerance).
 */
export function computeFitScale(available: number, contentWidth: number, floor = 0.1): number {
  if (!Number.isFinite(available) || !Number.isFinite(contentWidth)) return 1;
  if (!(available > 0) || !(contentWidth > 0)) return 1;
  if (contentWidth <= available + 1) return 1;
  return Math.max(available / contentWidth, floor);
}

/**
 * Detects if content is HTML.
 */
export function isHtmlContent(content: string): boolean {
  const htmlPattern = /<(html|body|div|p|br|table|tr|td|span|a\s|img|ul|ol|li|h[1-6]|blockquote)[^>]*>/i;
  return htmlPattern.test(content);
}

/**
 * Detects if content is plain text (not HTML, not proper markdown).
 * Plain text often has URLs in parentheses like (http://example.com)
 */
export function isPlainText(content: string): boolean {
  const urlInParensPattern = /\(https?:\/\/[^\s)]+\)/i;
  const markdownLinkPattern = /\[[^\]]+\]\([^)]+\)/;
  const markdownHeaderPattern = /^#{1,6}\s/m;
  const markdownEmphasisPattern = /(\*\*|__|\*|_)[^*_]+\1/;

  if (urlInParensPattern.test(content) && !markdownLinkPattern.test(content)) {
    return true;
  }

  if (!markdownHeaderPattern.test(content) &&
      !markdownEmphasisPattern.test(content) &&
      !markdownLinkPattern.test(content)) {
    return true;
  }

  return false;
}

/**
 * Converts plain text URLs to clickable HTML links.
 * Handles various formats including Stripe-style "Text (URL)" patterns.
 */
export function convertUrlsToLinks(text: string): string {
  let result = text;

  // Pattern 1a: "Link text <https://url>" -> clickable link with text (common in plain text emails)
  // e.g., "Enable web search <https://example.com/docs>" -> <a href="...">Enable web search</a>
  result = result.replace(
    /([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\s\-_#']+?)\s*<(https?:\/\/[^\s>]+)>/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // Pattern 1b: Standalone angle-bracket URLs <https://url>
  result = result.replace(
    /<(https?:\/\/[^\s>]+)>/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // Pattern 2: "Link text (https://url)" -> clickable link with text
  // e.g., "Download invoice (https://example.com/pdf)" -> <a href="...">Download invoice</a>
  result = result.replace(
    /([A-Za-z][A-Za-z0-9\s\-_#]+?)\s*\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // Pattern 3: Standalone URLs in parentheses (no preceding text)
  result = result.replace(
    /\((https?:\/\/[^\s)]+)\)/g,
    '(<a href="$1" target="_blank" rel="noopener noreferrer">link</a>)'
  );

  // Pattern 4: URLs in brackets [https://url]
  result = result.replace(
    /\[(https?:\/\/[^\s\]]+)\]/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // Pattern 5: Standalone URLs not already in links
  result = result.replace(
    /(?<!href="|">)(https?:\/\/[^\s<>"()[\]]+)(?![^<]*<\/a>)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // Pattern 6: Bare domains (e.g. docs.google.com/path, example.com)
  // Must have a known TLD and not already be inside a link. The second
  // lookbehind requires a token boundary — the match may not be preceded by a
  // word char or "@" — so an email-address domain (the "acme.com" in
  // support@acme.com, and mid-token slices like "cme.com") is left intact
  // while genuine bare domains after a space/punctuation still linkify.
  result = result.replace(
    /(?<!href="|">|\/\/)(?<![\w@])([a-zA-Z0-9][\w-]*\.(?:com|org|net|io|dev|co|ca|fr|be|ch|de|uk|eu|app|me|info|biz|tv|cc)(?:\.[\w]{2,3})?(?:\/[^\s<>"()[\]]*[^\s<>"()[\].,;:!?])?)(?![^<]*<\/a>)/g,
    '<a href="https://$1" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // Convert line breaks
  result = result.replace(/\n/g, '<br>');

  return result;
}

/**
 * Converts markdown-like content to HTML.
 * Handles common patterns from email clients including malformed markdown.
 */
export function markdownToHtml(text: string): string {
  let result = text;

  // Convert angle-bracket URLs BEFORE HTML escaping (otherwise < > get escaped)
  // Pattern: "Link text <https://url>" -> clickable link with text as label
  result = result.replace(
    /([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\s\-_#']+?)\s*<(https?:\/\/[^\s>]+)>/g,
    '%%TLINK%%$1%%SEP%%$2%%END%%'
  );
  // Pattern: Standalone <https://url>
  result = result.replace(
    /<(https?:\/\/[^\s>]+)>/g,
    '%%LINK%%$1%%END%%'
  );

  // Escape HTML entities
  result = result
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Restore text+URL links
  result = result.replace(
    /%%TLINK%%(.*?)%%SEP%%(.*?)%%END%%/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );
  // Restore standalone URL links
  result = result.replace(
    /%%LINK%%(.*?)%%END%%/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // Convert markdown links (including malformed ones with spaces)
  result = result.replace(
    /\[\s*([^\]]+?)\s*\]\((https?:\/\/[^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // Convert bold: **text** or __text__
  result = result.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  result = result.replace(/__([^_]+)__/g, '<strong>$1</strong>');

  // Convert italic: *text* or _text_.
  // Guards: an opening marker must not be followed by whitespace and a closing
  // marker must not be preceded by whitespace (so "2 * 3 * 4" isn't italicised),
  // and `_` emphasis must sit on a word boundary so snake_case identifiers and
  // underscore-heavy URLs (first_name_field, docs.google.com/a_b_c) stay intact.
  result = result.replace(/(?<!\*)\*(?!\s)([^*]+?)(?<!\s)\*(?!\*)/g, '<em>$1</em>');
  result = result.replace(/(?<!\w)_(?!\s)([^_]+?)(?<!\s)_(?!\w)/g, '<em>$1</em>');

  // Convert headers (handle with or without space)
  result = result.replace(/^######\s*(.+)$/gm, '<h6>$1</h6>');
  result = result.replace(/^#####\s*(.+)$/gm, '<h5>$1</h5>');
  result = result.replace(/^####\s*(.+)$/gm, '<h4>$1</h4>');
  result = result.replace(/^###\s*(.+)$/gm, '<h3>$1</h3>');
  result = result.replace(/^##\s*(.+)$/gm, '<h2>$1</h2>');
  result = result.replace(/^#\s*(.+)$/gm, '<h1>$1</h1>');

  // Convert horizontal rules
  result = result.replace(/^[-*_]{3,}$/gm, '<hr>');

  // Convert bullet lists
  result = result.replace(/^[-*]\s+(.+)$/gm, '<li>$1</li>');
  result = result.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

  // Convert line breaks
  result = result.replace(/\n(?!<)/g, '<br>\n');
  result = result.replace(/(<\/(?:h[1-6]|ul|li|hr)>)\s*<br>/g, '$1');

  return result;
}

function stripTrackingResourcesFallback(html: string): string {
  return html.replace(
    /<img\b[^>]*\bsrc\s*=\s*["'][^"']*\/\/click\.formspree\.io\/wf\/open\?[^"']*["'][^>]*>/gi,
    ''
  );
}

function readPixelDimension(value: string | null): number | null {
  if (!value) return null;
  const match = value.match(/^\s*(\d+(?:\.\d+)?)/);
  return match ? Number(match[1]) : null;
}

function isHiddenPixelStyle(style: string | null): boolean {
  if (!style) return false;
  return (
    /display\s*:\s*none/i.test(style) ||
    /visibility\s*:\s*hidden/i.test(style) ||
    /opacity\s*:\s*0(?:\.0+)?/i.test(style) ||
    /(?:^|;)\s*(?:width|height)\s*:\s*(?:0|1)px/i.test(style)
  );
}

function isTrackingImage(img: HTMLImageElement): boolean {
  const src = img.getAttribute('src') || '';
  if (!src || /^data:image\//i.test(src)) return false;

  let url: URL;
  try {
    url = new URL(src, window.location.origin);
  } catch {
    return /\/\/click\.formspree\.io\/wf\/open\?/i.test(src);
  }

  const host = url.hostname.toLowerCase();
  const path = url.pathname.toLowerCase();
  const raw = `${url.hostname}${url.pathname}${url.search}`.toLowerCase();

  if (host === 'click.formspree.io' && path === '/wf/open') {
    return true;
  }

  const width = readPixelDimension(img.getAttribute('width'));
  const height = readPixelDimension(img.getAttribute('height'));
  const isTiny = width !== null && height !== null && width <= 1 && height <= 1;
  const isHidden = isHiddenPixelStyle(img.getAttribute('style'));
  const looksLikeOpenPixel = /(?:^|[/?&._-])(open|pixel|beacon|track|tracking)(?:[/?&._=-]|$)/i.test(raw);

  return (isTiny || isHidden) && looksLikeOpenPixel;
}

/**
 * Removes email open-tracking pixels while preserving normal newsletter images.
 * This prevents opening a message from firing third-party "opened" beacons.
 */
export function stripEmailTrackingResources(html: string): string {
  if (!html) return '';

  if (typeof document === 'undefined' || typeof DOMParser === 'undefined') {
    return stripTrackingResourcesFallback(html);
  }

  const removeTrackingImages = (root: ParentNode) => {
    root.querySelectorAll<HTMLImageElement>('img').forEach((img) => {
      if (isTrackingImage(img)) {
        img.remove();
      }
    });
  };

  if (/<html[\s>]/i.test(html) || /<body[\s>]/i.test(html)) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    removeTrackingImages(doc);
    return doc.documentElement.outerHTML;
  }

  const template = document.createElement('template');
  template.innerHTML = html;
  removeTrackingImages(template.content);
  return template.innerHTML;
}

/**
 * The page CSP only allows https: images (index.html meta + tauri.conf.json),
 * so emails referencing http:// images render as broken placeholders even
 * though the host usually serves the same file over TLS (e.g. SendGrid's CDN
 * links are generated as http://). Upgrade them — the Gmail-proxy equivalent.
 * Hosts that genuinely can't do TLS stay blocked, which is the safe outcome:
 * loading them in plaintext would leak read-tracking to any on-path observer.
 */
export function upgradeInsecureImageSources(html: string): string {
  if (!html) return '';
  return html.replace(/(<img\b[^>]*?\bsrc\s*=\s*["'])http:\/\//gi, '$1https://');
}

/**
 * Sanitizes and renders email body content.
 * Detects content type (HTML, markdown, plain text) and converts accordingly.
 */
export function sanitizeEmailBody(body: string): string {
  if (!body) return '';

  // Common allowed tags for HTML emails (including images for newsletters)
  const HTML_ALLOWED_TAGS = [
    'p', 'br', 'div', 'span', 'a',
    'strong', 'em', 'b', 'i', 'u', 's', 'strike',
    'ul', 'ol', 'li',
    'blockquote', 'pre', 'code',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'table', 'tr', 'td', 'th', 'thead', 'tbody', 'tfoot', 'caption', 'colgroup', 'col',
    'img', 'figure', 'figcaption',
    'hr', 'center',
    'section', 'article', 'header', 'footer', 'nav', 'aside',
    'font', 'sup', 'sub', 'small', 'big',
  ];

  // Audit Codex 2026-04-25 [F-CSS-12]: keeping `style` here turns every email
  // into a CSS-exfil channel (`background-image:url(https://attacker/...)`).
  // The structural attributes (align/valign/bgcolor/border/etc.) cover the
  // vast majority of HTML-email layouts; inline styles were redundant for
  // anything other than tracking pixels and font-color tweaks.
  const HTML_ALLOWED_ATTR = [
    'href', 'target', 'rel', 'class', 'id',
    'src', 'alt', 'width', 'height', 'title',
    'align', 'valign', 'bgcolor', 'color',
    'border', 'cellpadding', 'cellspacing',
    'colspan', 'rowspan',
  ];

  // HTML emails: only strip <style>/<script>, preserve inline styles and structure
  if (isHtmlContent(body)) {
    let cleaned = body;
    cleaned = cleaned.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '');
    cleaned = cleaned.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '');
    // Remove <img> tags with unresolvable cid: src (inline attachments)
    cleaned = cleaned.replace(/<img[^>]+src=["']cid:[^"']+["'][^>]*>/gi, '');
    cleaned = stripEmailTrackingResources(cleaned);
    // Pre-extract data:image/ URIs — DOMPurify strips them by default (XSS protection).
    // Safe to bypass: data:image/ cannot carry executable payloads.
    const dataUris: string[] = [];
    const preProcessed = cleaned.replace(/src\s*=\s*["'](data:image\/[^"']{4,})["']/gi, (_m, uri) => {
      dataUris.push(uri);
      return `src="__DATAURI${dataUris.length - 1}__"`;
    });

    let sanitized = DOMPurify.sanitize(preProcessed, {
      ALLOWED_TAGS: HTML_ALLOWED_TAGS,
      ALLOWED_ATTR: HTML_ALLOWED_ATTR,
      ALLOW_DATA_ATTR: false,
    });

    // Restore data:image/ URIs after sanitization
    dataUris.forEach((uri, idx) => {
      sanitized = sanitized.replace(
        new RegExp(`src=["']__DATAURI${idx}__["']`, 'g'),
        `src="${uri}"`
      );
    });
    // Strip height-related inline styles that prevent Superhuman-style thread scroll
    // Gmail/Outlook inject min-height, height, max-height on wrapper divs
    // Negative lookbehind (?<![a-zA-Z-]) avoids matching inside line-height
    const heightStripped = sanitized.replace(/style="([^"]*)"/gi, (_match, styles: string) => {
      const cleaned = styles
        .replace(/(?<![a-zA-Z-])(min-height|max-height|height)\s*:\s*[^;]+;?/gi, '')
        .trim();
      return cleaned ? `style="${cleaned}"` : '';
    });
    // Strip redundant email headers injected in reply/forward bodies (Sujet:/De:/Date: etc.)
    // These are already shown in the UI header — no need to repeat them in the body
    const headerStripped = heightStripped
      .replace(/<(p|div|span|b|strong)[^>]*>\s*(Sujet|Subject|Objet|De|From|Envoyé[e]?|Sent|Date|À|To|Cc|Cci|Bcc)\s*:\s*.*?<\/\1>/gi, '')
      .replace(/(?:^|\n)\s*(Sujet|Subject|Objet)\s*:.*(?:\n|$)/gi, '');
    return upgradeInsecureImageSources(headerStripped)
      .replace(/<a /g, '<a target="_blank" rel="noopener noreferrer" ');
  }

  // Non-HTML content: only clean CSS junk if the body actually contains CSS-like patterns
  let cleaned = body;
  const hasCssPatterns = /(@media|!important|\{[^}]*\}|min-width|max-width|display\s*:|font-size\s*:)/i.test(body);
  if (hasCssPatterns) {
    // Remove curly-brace blocks (multiple passes for nested braces)
    for (let i = 0; i < 10; i++) {
      const prev = cleaned;
      cleaned = cleaned.replace(/\{[^}]*\}/g, ' ');
      if (cleaned === prev) break;
    }
    // Remove @media and other @-rules leftovers
    cleaned = cleaned.replace(/@media[^;{]*/gi, ' ');
    cleaned = cleaned.replace(/@[\w-]+\s+[^;{]*/gi, ' ');
    // Remove !important
    cleaned = cleaned.replace(/!important/gi, ' ');
    // Remove CSS property patterns (e.g. "display:block;")
    cleaned = cleaned.replace(/\b[\w-]+\s*:\s*[\w%#(),.!\s-]+;/g, ' ');
    // Remove CSS selectors like .class, *[class], #id
    cleaned = cleaned.replace(/[*][^a-zA-Z\s]/g, ' ');
    // Collapse whitespace (but preserve single newlines for paragraph structure)
    cleaned = cleaned.replace(/[^\S\n]{2,}/g, ' ');
    cleaned = cleaned.replace(/\n{3,}/g, '\n\n');
    cleaned = cleaned.trim();
    // If still mostly CSS junk after cleaning, discard the body
    if (cleaned && /(@media|!important|\{|\}|min-width|max-width|display\s*:)/i.test(cleaned)) {
      cleaned = '';
    }
  }

  if (!cleaned) return '';

  // Strip unresolvable CID image references (inline attachments shown as text)
  cleaned = cleaned.replace(/\[cid:[^\]]+\]/gi, '').replace(/\n{3,}/g, '\n\n').trim()

  // Strip quoted email header blocks at the start (De:/From:/Sujet:/Subject:/Date:/À:/To:)
  // These are injected by Outlook/Apple Mail in reply/forward bodies and are redundant
  // since we already display sender/subject in the UI
  cleaned = cleaned.replace(/^((De|From|Envoyé(e)?|Sent|Objet|Sujet|Subject|Date|À|To|Cc|Cci|Bcc)\s*:.*(\n|$))+/im, '').trim();

  if (!cleaned) return '';

  // Strip double-underscore wrapping around URLs (__https://url__ → https://url)
  // Common in plain-text Google Docs/Sheets notification emails
  // Use non-greedy \S+? to allow underscores inside URLs (Google Docs URLs have them)
  cleaned = cleaned.replace(/__?(https?:\/\/\S+?)__(?=[\s).,;!?\]]|$)/g, '$1');

  // If plain text, convert URLs to links
  if (isPlainText(cleaned)) {
    const withLinks = convertUrlsToLinks(cleaned);
    return DOMPurify.sanitize(withLinks, {
      ALLOWED_TAGS: ['a', 'br'],
      ALLOWED_ATTR: ['href', 'target', 'rel'],
    });
  }

  // Otherwise, convert markdown to HTML and sanitize
  let htmlContent = markdownToHtml(cleaned);
  // Convert standalone URLs not already wrapped in <a> tags (markdown path misses these)
  htmlContent = htmlContent.replace(
    /(?<!href="|">)(https?:\/\/[^\s<>"[\]]+)(?![^<]*<\/a>)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
  );
  // Bare domains (e.g. docs.google.com/path) — the token-boundary lookbehind
  // (?<![\w@]) spares email-address domains (no mid-token / post-"@" matches).
  htmlContent = htmlContent.replace(
    /(?<!href="|">|\/\/)(?<![\w@])([a-zA-Z0-9][\w-]*\.(?:com|org|net|io|dev|co|ca|fr|be|ch|de|uk|eu|app|me|info|biz|tv|cc)(?:\.[\w]{2,3})?(?:\/[^\s<>"()[\]]*[^\s<>"()[\].,;:!?])?)(?![^<]*<\/a>)/g,
    '<a href="https://$1" target="_blank" rel="noopener noreferrer">$1</a>'
  );
  return upgradeInsecureImageSources(DOMPurify.sanitize(htmlContent, {
    ALLOWED_TAGS: ['p', 'br', 'div', 'span', 'a', 'strong', 'em', 'b', 'i', 'u', 'ul', 'ol', 'li', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'img'],
    ALLOWED_ATTR: ['href', 'target', 'rel', 'src', 'alt', 'width', 'height'],
  }));
}

/**
 * Separates the actual reply from quoted/cited content in plain-text emails.
 * Returns the clean body and the quoted portion (if any).
 */
export function stripQuotedContent(body: string | null | undefined): { clean: string; quoted: string | null } {
  if (!body) return { clean: '', quoted: null };
  const lines = body.split('\n');
  let cutIndex = -1;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();

    // "On DATE, NAME wrote:" or "Le DATE, NAME a écrit :"
    if (/^(On |Le ).+(wrote|a écrit)\s*:?\s*$/i.test(line)) {
      cutIndex = i; break;
    }
    // "-----Original Message-----" or "---------- Forwarded message ----------"
    if (/^-{3,}\s*(Original Message|Message transféré|Forwarded message)/i.test(line)) {
      cutIndex = i; break;
    }
    // Block of header lines mid-body (De:/From:/Sujet:/À:/Date:) preceded by empty line or another header
    if (i > 0 && /^(De|From|Envoyé|Sent|Objet|Sujet|Subject|Date|À|To|Cc|Cci|Bcc)\s*:/i.test(line)) {
      const prevLine = lines[i - 1].trim();
      if (prevLine === '' || /^(De|From|Envoyé|Sent|Objet|Sujet|Subject|Date|À|To|Cc|Cci|Bcc)\s*:/i.test(prevLine)) {
        cutIndex = i; break;
      }
    }
    // Lines starting with > (quoted text) preceded by empty line
    if (line.startsWith('>') && i > 0 && lines[i - 1].trim() === '') {
      cutIndex = i; break;
    }
  }

  if (cutIndex === -1) return { clean: body, quoted: null };

  const clean = lines.slice(0, cutIndex).join('\n').trim();
  const quoted = lines.slice(cutIndex).join('\n').trim();
  return { clean, quoted: quoted || null };
}

/**
 * Strips quoted/cited content from HTML emails (for thread view where context is
 * already visible in adjacent message cards).
 * Targets: Gmail's gmail_quote, Outlook's appendonsend, blockquote[type=cite], hr + headers.
 */
export function stripQuotedHtml(html: string): string {
  let cleaned = html;
  // Gmail: <div class="gmail_quote">...</div> (greedy to end). Modern Gmail
  // emits class="gmail_quote gmail_quote_container" on the wrapper, so the
  // class list may carry extra tokens around gmail_quote.
  cleaned = cleaned.replace(/<div[^>]*class=["'][^"']*\bgmail_quote\b[^"']*["'][^>]*>[\s\S]*$/i, '');
  // Gmail attribution line ("Le DATE, NAME a écrit :") right above the quote —
  // covers bodies where the wrapper div was dropped by an intermediate parser.
  cleaned = cleaned.replace(/<div[^>]*class=["'][^"']*\bgmail_attr\b[^"']*["'][^>]*>[\s\S]*$/i, '');
  // Outlook: <div id="appendonsend">...</div>
  cleaned = cleaned.replace(/<div[^>]*id="appendonsend"[^>]*>[\s\S]*$/i, '');
  // Generic: <blockquote type="cite">...</blockquote> (Apple Mail) or Gmail's
  // inner <blockquote class="gmail_quote"> when no wrapper matched above.
  cleaned = cleaned.replace(/<blockquote[^>]*(?:type=["']cite["']|class=["'][^"']*\bgmail_quote\b[^"']*["'])[^>]*>[\s\S]*$/i, '');
  // "-----Original Message-----" text divider
  cleaned = cleaned.replace(/-{3,}\s*(Original Message|Message transféré|Forwarded message)[\s\S]*$/i, '');
  // <hr> followed by header block (From/De/Sujet/Date/etc.)
  cleaned = cleaned.replace(/<hr[^>]*>\s*(<div[^>]*>.*?(From|De|Envoy|Sent|Sujet|Subject|Date|To|À)\s*:[\s\S]*)?$/i, '');
  return cleaned.trim();
}

/**
 * Detects content type for styling purposes.
 */
export function getContentType(body: string): 'html' | 'plaintext' | 'markdown' {
  if (isHtmlContent(body)) return 'html';
  if (isPlainText(body)) return 'plaintext';
  return 'markdown';
}

function safeFromCodePoint(cp: number): string {
  try {
    return Number.isFinite(cp) && cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : '';
  } catch {
    return '';
  }
}

/**
 * Decodes HTML character references. The input MUST already be free of real
 * tags (callers strip them first) so assigning to a detached <textarea> only
 * resolves entities — it never creates elements, fires `onerror`, or loads
 * remote resources. Falls back to a hand-rolled decoder when there is no DOM
 * (SSR / non-jsdom test envs).
 */
function decodeEntities(text: string): string {
  if (!text) return '';
  if (typeof document !== 'undefined') {
    const ta = document.createElement('textarea');
    ta.innerHTML = text;
    return ta.value;
  }
  return text
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&(?:apos|#0*39|#x0*27);/gi, "'")
    .replace(/&#x([0-9a-f]+);/gi, (_m, h: string) => safeFromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_m, d: string) => safeFromCodePoint(parseInt(d, 10)));
}

/**
 * Converts HTML (or already-plain text) into a clean preview string for list
 * rows / snippets. Single source of truth for the Inbox/Sent, Drafts and
 * Scheduled previews, which previously each hand-rolled a partial entity
 * decoder (so `&rsquo; &mdash; &#8217;` rendered literally) with inconsistent
 * behaviour.
 *
 * Safety: every tag (including `<img>`) is removed by regex BEFORE any DOM
 * parsing, so tracking pixels never load and `<img onerror>` never fires.
 * Truncation is code-point aware so emoji / surrogate pairs are never split
 * into a replacement character.
 */
export function htmlToPreviewText(
  html: string | null | undefined,
  opts: { preserveLineBreaks?: boolean; maxChars?: number } = {},
): string {
  if (!html) return '';
  const { preserveLineBreaks = false, maxChars } = opts;

  let text = html
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, ' ')
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ' ');

  if (preserveLineBreaks) {
    text = text
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/(?:p|div|li|h[1-6]|tr)>/gi, '\n');
  }

  // Remove every remaining tag so the decode step runs on tag-free text.
  text = text.replace(/<[^>]+>/g, preserveLineBreaks ? '' : ' ');
  text = decodeEntities(text);

  if (preserveLineBreaks) {
    text = text
      .replace(/[^\S\n]{2,}/g, ' ')
      .replace(/[ \t]*\n[ \t]*/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  } else {
    text = text.replace(/\s+/g, ' ').trim();
  }

  if (maxChars && maxChars > 0) {
    const chars = Array.from(text);
    if (chars.length > maxChars) {
      text = chars.slice(0, maxChars).join('').trimEnd() + '…';
    }
  }

  return text;
}
