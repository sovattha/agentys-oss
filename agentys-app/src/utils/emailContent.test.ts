import { describe, expect, it } from 'vitest';
import {
  sanitizeEmailBody,
  stripEmailTrackingResources,
  markdownToHtml,
  htmlToPreviewText,
  convertUrlsToLinks,
  getReadableTextColorForLowContrast,
  repairLowContrastEmailText,
  stripQuotedHtml,
  computeFitScale,
} from './emailContent';

describe('email tracking resource stripping', () => {
  it('removes Formspree open pixels', () => {
    const html = [
      '<p>Bonjour</p>',
      '<img src="https://click.formspree.io/wf/open?upn=abc123" width="1" height="1" alt="">',
    ].join('');

    const stripped = stripEmailTrackingResources(html);

    expect(stripped).toContain('Bonjour');
    expect(stripped).not.toContain('click.formspree.io/wf/open');
  });

  it('preserves normal remote images', () => {
    const html = '<img src="https://static.formspree.io/img/formspree-logo2x.png" width="240" height="80" alt="Formspree">';

    const stripped = stripEmailTrackingResources(html);

    expect(stripped).toContain('formspree-logo2x.png');
  });

  it('removes hidden 1x1 open pixels during sanitization', () => {
    const html = [
      '<p>Contenu visible</p>',
      '<img src="https://example.com/email/open.gif?id=42" width="1" height="1">',
      '<img src="https://example.com/assets/logo.png" width="120" height="40" alt="Logo">',
    ].join('');

    const sanitized = sanitizeEmailBody(html);

    expect(sanitized).toContain('Contenu visible');
    expect(sanitized).not.toContain('open.gif');
    expect(sanitized).toContain('logo.png');
  });
});

describe('insecure image upgrade (CSP only allows https: images)', () => {
  it('rewrites http:// img sources to https:// in HTML emails', () => {
    const html = [
      '<p>Hey savagecrypto,</p>',
      '<img src="http://cdn.mcauto-images-production.sendgrid.net/abc/550x254.png" width="550" height="254" alt="banner">',
    ].join('');

    const sanitized = sanitizeEmailBody(html);

    expect(sanitized).toContain('src="https://cdn.mcauto-images-production.sendgrid.net/abc/550x254.png"');
    expect(sanitized).not.toContain('src="http://');
  });

  it('leaves https images and http links untouched', () => {
    const html = [
      '<img src="https://example.com/logo.png" width="120" height="40" alt="Logo">',
      '<a href="http://example.com/unsubscribe">Unsubscribe</a>',
    ].join('');

    const sanitized = sanitizeEmailBody(html);

    expect(sanitized).toContain('src="https://example.com/logo.png"');
    expect(sanitized).toContain('href="http://example.com/unsubscribe"');
  });
});

describe('email HTML readability repair', () => {
  it('forces dark text on light colored cells when the email hardcodes white text', () => {
    expect(getReadableTextColorForLowContrast('rgb(255, 255, 255)', 'rgb(220, 252, 231)'))
      .toBe('#111827');
    expect(getReadableTextColorForLowContrast('rgb(255, 255, 255)', 'rgb(254, 215, 170)'))
      .toBe('#111827');
  });

  it('keeps already readable white text on dark colored cells', () => {
    expect(getReadableTextColorForLowContrast('rgb(255, 255, 255)', 'rgb(21, 128, 61)'))
      .toBeNull();
    expect(getReadableTextColorForLowContrast('rgb(255, 255, 255)', 'rgb(185, 28, 28)'))
      .toBeNull();
  });

  it('repairs unreadable text inside rendered HTML email fragments', () => {
    const host = document.createElement('div');
    host.innerHTML = [
      '<div data-testid="light" style="background-color: rgb(220, 252, 231); color: rgb(255, 255, 255)">Texte illisible</div>',
      '<div data-testid="dark" style="background-color: rgb(21, 128, 61); color: rgb(255, 255, 255)">Texte lisible</div>',
    ].join('');
    document.body.appendChild(host);

    try {
      expect(repairLowContrastEmailText(document, host)).toBe(1);
      expect(host.querySelector<HTMLElement>('[data-testid="light"]')?.style.getPropertyValue('color'))
        .toBe('rgb(17, 24, 39)');
      expect(host.querySelector<HTMLElement>('[data-testid="light"]')?.style.getPropertyPriority('color'))
        .toBe('important');
      expect(host.querySelector<HTMLElement>('[data-testid="dark"]')?.style.getPropertyPriority('color'))
        .toBe('');
    } finally {
      host.remove();
    }
  });
});

describe('email-address domains are not linkified (plain-text path)', () => {
  it('keeps "support@acme.com" intact instead of linking the acme.com tail', () => {
    const out = sanitizeEmailBody('Email us at support@acme.com for help.');
    expect(out).toContain('support@acme.com');
    expect(out).not.toContain('<a');
    expect(out).not.toContain('href="https://acme.com"');
  });

  it('still linkifies a genuine bare domain', () => {
    const out = sanitizeEmailBody('Visit acme.com for details.');
    expect(out).toContain('href="https://acme.com"');
  });

  it('convertUrlsToLinks: @-prefixed domain stays text, spaced domain links', () => {
    expect(convertUrlsToLinks('ping bob@startup.io now')).not.toContain('href');
    expect(convertUrlsToLinks('go to startup.io now')).toContain('href="https://startup.io"');
  });
});

describe('markdown emphasis no longer misfires', () => {
  it('does not italicise underscores inside snake_case identifiers', () => {
    expect(markdownToHtml('the field first_name_field is required')).not.toContain('<em>');
  });

  it('does not italicise asterisks flanked by whitespace (arithmetic)', () => {
    expect(markdownToHtml('total 2 * 3 * 4 units')).not.toContain('<em>');
  });

  it('still italicises real emphasis', () => {
    expect(markdownToHtml('this is _important_ today')).toContain('<em>important</em>');
    expect(markdownToHtml('a *strong* word')).toContain('<em>strong</em>');
  });

  it('still bolds **double markers**', () => {
    expect(markdownToHtml('**bold** here')).toContain('<strong>bold</strong>');
  });
});

describe('htmlToPreviewText (shared list-preview stripper)', () => {
  it('decodes named + numeric entities (no literal &entity; leak)', () => {
    const out = htmlToPreviewText('<p>Caf&eacute; &mdash; &rsquo;hi&rsquo; &#8217;yo&#8217;</p>');
    expect(out).toContain('Café');
    expect(out).toContain('—');
    expect(out).toContain('’');
    expect(out).not.toContain('&rsquo;');
    expect(out).not.toContain('&#8217;');
    expect(out).not.toContain('&mdash;');
  });

  it('removes tags (incl. <img onerror>) before any DOM parse', () => {
    expect(htmlToPreviewText('<img src="x" onerror="boom()">Hello <b>world</b>'))
      .toBe('Hello world');
  });

  it('truncates on code-point boundaries so emoji are never split', () => {
    const out = htmlToPreviewText('😀'.repeat(10), { maxChars: 5 });
    expect(Array.from(out)).toHaveLength(6); // 5 emoji + ellipsis
    expect(out.endsWith('…')).toBe(true);
    expect(out).not.toContain('�');
  });

  it('preserves line breaks when asked', () => {
    expect(htmlToPreviewText('L1<br>L2</p>L3', { preserveLineBreaks: true }))
      .toBe('L1\nL2\nL3');
  });

  it('returns empty string for nullish input', () => {
    expect(htmlToPreviewText('')).toBe('');
    expect(htmlToPreviewText(null)).toBe('');
    expect(htmlToPreviewText(undefined)).toBe('');
  });
});

describe('stripQuotedHtml (thread view quote dedup)', () => {
  it('strips the modern Gmail wrapper (class="gmail_quote gmail_quote_container")', () => {
    const html = [
      '<div dir="ltr">Bonjour Alexandre,<br><br>Félicitations pour le lancement !</div><br>',
      '<div class="gmail_quote gmail_quote_container">',
      '<div dir="ltr" class="gmail_attr">Le mer. 10 juin 2026 à 15:32, Crypto Université &lt;<a href="mailto:x@gmail.com">x@gmail.com</a>&gt; a écrit :<br></div>',
      '<blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex">Bonjour Alexandra, Je viens de lancer mon application Agentys…</blockquote>',
      '</div>',
    ].join('');

    const cleaned = stripQuotedHtml(html);

    expect(cleaned).toContain('Félicitations pour le lancement');
    expect(cleaned).not.toContain('a écrit :');
    expect(cleaned).not.toContain('Je viens de lancer mon application');
  });

  it('still strips the legacy Gmail wrapper (class="gmail_quote" alone)', () => {
    const html = '<div dir="ltr">Réponse</div><div class="gmail_quote">On Mon, Jan 5, 2026, John wrote:<blockquote>Old message</blockquote></div>';

    const cleaned = stripQuotedHtml(html);

    expect(cleaned).toContain('Réponse');
    expect(cleaned).not.toContain('Old message');
  });

  it('strips an orphan gmail_attr attribution line when the wrapper div is missing', () => {
    const html = '<div dir="ltr">Merci !</div><div dir="ltr" class="gmail_attr">Le lun. 5 janv. 2026 à 09:00, Jane a écrit :<br></div><blockquote class="gmail_quote">Ancien message</blockquote>';

    const cleaned = stripQuotedHtml(html);

    expect(cleaned).toContain('Merci !');
    expect(cleaned).not.toContain('a écrit :');
    expect(cleaned).not.toContain('Ancien message');
  });

  it('strips a bare <blockquote class="gmail_quote"> when no wrapper matched', () => {
    const html = '<div>Nouvelle réponse</div><blockquote class="gmail_quote" style="margin:0">Contenu cité</blockquote>';

    const cleaned = stripQuotedHtml(html);

    expect(cleaned).toContain('Nouvelle réponse');
    expect(cleaned).not.toContain('Contenu cité');
  });

  it('still strips Apple Mail <blockquote type="cite">', () => {
    const html = '<div>Reply text</div><blockquote type="cite">Quoted Apple Mail content</blockquote>';

    const cleaned = stripQuotedHtml(html);

    expect(cleaned).toContain('Reply text');
    expect(cleaned).not.toContain('Quoted Apple Mail content');
  });

  it('still strips the Outlook appendonsend block', () => {
    const html = '<div>Réponse Outlook</div><div id="appendonsend"></div><div>De : Jean<br>Envoyé : lundi</div>';

    const cleaned = stripQuotedHtml(html);

    expect(cleaned).toContain('Réponse Outlook');
    expect(cleaned).not.toContain('Envoyé : lundi');
  });

  it('leaves formatting blockquotes (newsletters) untouched', () => {
    const html = '<div>Intro</div><blockquote class="pullquote">Une citation éditoriale</blockquote><div>Suite</div>';

    const cleaned = stripQuotedHtml(html);

    expect(cleaned).toContain('Une citation éditoriale');
    expect(cleaned).toContain('Suite');
  });

  it('does not treat gmail_quote_container alone as a quote marker', () => {
    const html = '<div class="gmail_quote_container_like">Contenu légitime</div>';

    expect(stripQuotedHtml(html)).toContain('Contenu légitime');
  });
});

describe('computeFitScale (fit wide HTML emails into the reading pane)', () => {
  it('does not scale when content already fits', () => {
    expect(computeFitScale(600, 580)).toBe(1);
    expect(computeFitScale(600, 600)).toBe(1);
  });

  it('tolerates a 1px overshoot (sub-pixel rounding noise)', () => {
    expect(computeFitScale(600, 601)).toBe(1);
  });

  it('scales a fixed-width email down to fit a narrower pane', () => {
    // 600px email in a 400px pane → the "email coupé" case from Karine's screen.
    expect(computeFitScale(400, 600)).toBeCloseTo(2 / 3, 5);
    expect(computeFitScale(360, 720)).toBe(0.5);
  });

  it('fits realistic wide emails edge-to-edge without hitting the floor', () => {
    // A 1000px newsletter in a 360px pane still scales exactly (0.36 > 0.1 floor),
    // so the scaled width equals the pane width — no clipping.
    expect(computeFitScale(360, 1000)).toBeCloseTo(0.36, 5);
  });

  it('never shrinks below the floor for degenerate widths', () => {
    // 100 / 2000 = 0.05, clamped up to the 0.1 default floor.
    expect(computeFitScale(100, 2000)).toBe(0.1);
    // 400 / 2000 = 0.2 stays unclamped (still legible, fits edge-to-edge).
    expect(computeFitScale(400, 2000)).toBeCloseTo(0.2, 5);
    expect(computeFitScale(400, 2000, 0.5)).toBe(0.5);
  });

  it('returns 1 when the viewport is not measurable yet', () => {
    // First paint / detached iframe: clientWidth or scrollWidth read as 0.
    expect(computeFitScale(0, 600)).toBe(1);
    expect(computeFitScale(600, 0)).toBe(1);
    expect(computeFitScale(-5, 600)).toBe(1);
  });

  it('returns 1 for non-finite inputs (NaN / Infinity)', () => {
    expect(computeFitScale(Number.NaN, 600)).toBe(1);
    expect(computeFitScale(400, Number.POSITIVE_INFINITY)).toBe(1);
    expect(computeFitScale(400, Number.NaN)).toBe(1);
  });
});
