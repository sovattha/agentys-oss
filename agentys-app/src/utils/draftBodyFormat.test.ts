import { describe, it, expect } from 'vitest';
import {
  looksLikeHtmlBody,
  htmlBodyToPlainText,
  isBodyBlank,
  toHtmlEmailBody,
  signatureToHtml,
} from './draftBodyFormat';

// Parité compose (2026-06-09) : le body Drafts vit désormais dans le
// DraftEditor TipTap — ces helpers font le pont entre les drafts legacy en
// texte brut et les drafts édités en HTML.

describe('looksLikeHtmlBody', () => {
  it('détecte le HTML TipTap et laisse passer le texte brut', () => {
    expect(looksLikeHtmlBody('<p>Bonjour</p>')).toBe(true);
    expect(looksLikeHtmlBody('Bonjour,\n\nMerci.')).toBe(false);
    expect(looksLikeHtmlBody('a < b et b > c')).toBe(false);
  });
});

describe('htmlBodyToPlainText', () => {
  it('strippe les balises pour les chemins LLM (même règle que ReplyComposer)', () => {
    expect(htmlBodyToPlainText('<p>Bonjour <strong>Alex</strong></p><p>À demain</p>'))
      .toBe('Bonjour Alex À demain');
  });

  it('laisse le texte brut intact (trim seulement)', () => {
    expect(htmlBodyToPlainText('  Bonjour,\n\nMerci.  ')).toBe('Bonjour,\n\nMerci.');
  });
});

describe('isBodyBlank', () => {
  it.each([
    ['vide', ''],
    ['éditeur TipTap vidé', '<p></p>'],
    ['paragraphes vides + br', '<p><br></p><p></p>'],
    ['nbsp seulement', '<p>&nbsp;</p>'],
    ['espaces', '   \n  '],
  ])('considère %s comme vide', (_label, html) => {
    expect(isBodyBlank(html)).toBe(true);
  });

  it.each([
    ['texte brut', 'Bonjour'],
    ['HTML avec contenu', '<p>Bonjour</p>'],
  ])('considère %s comme non vide', (_label, html) => {
    expect(isBodyBlank(html)).toBe(false);
  });
});

describe('toHtmlEmailBody', () => {
  it('sépare les paragraphes sur double saut de ligne sans <p> vide', () => {
    expect(toHtmlEmailBody('Bonjour,\n\nMerci.')).toBe('<p>Bonjour,</p><p>Merci.</p>');
  });

  it('convertit les sauts simples en <br> dans un même paragraphe', () => {
    expect(toHtmlEmailBody('Ligne 1\nLigne 2\n\nLigne 3')).toBe('<p>Ligne 1<br>Ligne 2</p><p>Ligne 3</p>');
  });

  it('laisse le HTML existant intact', () => {
    const html = '<p>Bonjour <strong>Alex</strong></p>';
    expect(toHtmlEmailBody(html)).toBe(html);
  });
});

describe('signatureToHtml', () => {
  it('échappe le HTML et convertit les lignes en <br>', () => {
    expect(signatureToHtml('Alexandre Simon\nCo-fondateur <Agentys & Cie>'))
      .toBe('<p>Alexandre Simon<br>Co-fondateur &lt;Agentys &amp; Cie&gt;</p>');
  });

  it("n'échappe pas les apostrophes (les signatures FR en sont pleines)", () => {
    expect(signatureToHtml("Co-fondateur d'Agentys")).toBe("<p>Co-fondateur d'Agentys</p>");
  });
});
