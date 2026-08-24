/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

import { describe, it, expect } from 'vitest';
import { isFreeBusyCompatible, buildDescriptionWithLabels, parseDescriptionAndLabels, stripExternalMeetingMetadata, formatOrganizer, applyLabelPrefix, computePopoverPosition } from '../components/Calendar/QuickEventPopover';

describe('isFreeBusyCompatible', () => {
  // ── Aucun participant ────────────────────────────────────────────────────────
  it('retourne false quand aucun participant', () => {
    expect(isFreeBusyCompatible([], 'gmail')).toBe(false);
    expect(isFreeBusyCompatible([], 'outlook')).toBe(false);
    expect(isFreeBusyCompatible([], undefined)).toBe(false);
  });

  // ── Même provider ────────────────────────────────────────────────────────────
  it('retourne true : gmail → @gmail.com', () => {
    expect(isFreeBusyCompatible(['alice@gmail.com'], 'gmail')).toBe(true);
  });

  it('retourne true : gmail → @googlemail.com', () => {
    expect(isFreeBusyCompatible(['bob@googlemail.com'], 'gmail')).toBe(true);
  });

  it('retourne true : outlook → @outlook.com', () => {
    expect(isFreeBusyCompatible(['charlie@outlook.com'], 'outlook')).toBe(true);
  });

  it('retourne true : outlook → @hotmail.com', () => {
    expect(isFreeBusyCompatible(['dan@hotmail.com'], 'outlook')).toBe(true);
  });

  it('retourne true : outlook → @live.com', () => {
    expect(isFreeBusyCompatible(['eve@live.com'], 'outlook')).toBe(true);
  });

  it('retourne true : outlook → @hotmail.fr', () => {
    expect(isFreeBusyCompatible(['fra@hotmail.fr'], 'outlook')).toBe(true);
  });

  // ── Cross-provider ───────────────────────────────────────────────────────────
  it('retourne false : gmail + participant @outlook.com', () => {
    expect(isFreeBusyCompatible(['alice@outlook.com'], 'gmail')).toBe(false);
  });

  it('retourne false : gmail + participant @hotmail.com', () => {
    expect(isFreeBusyCompatible(['bob@hotmail.com'], 'gmail')).toBe(false);
  });

  it('retourne false : gmail + participant @live.com', () => {
    expect(isFreeBusyCompatible(['carol@live.com'], 'gmail')).toBe(false);
  });

  it('retourne false : gmail + participant @msn.com', () => {
    expect(isFreeBusyCompatible(['dave@msn.com'], 'gmail')).toBe(false);
  });

  it('retourne false : gmail + participant @hotmail.fr', () => {
    expect(isFreeBusyCompatible(['ema@hotmail.fr'], 'gmail')).toBe(false);
  });

  it('retourne false : gmail + participant @live.fr', () => {
    expect(isFreeBusyCompatible(['fab@live.fr'], 'gmail')).toBe(false);
  });

  it('retourne false : outlook + participant @gmail.com', () => {
    expect(isFreeBusyCompatible(['gus@gmail.com'], 'outlook')).toBe(false);
  });

  it('retourne false : outlook + participant @googlemail.com', () => {
    expect(isFreeBusyCompatible(['hel@googlemail.com'], 'outlook')).toBe(false);
  });

  // ── Domaine corporate inconnu (optimiste) ────────────────────────────────────
  it('retourne true : gmail + domaine corporate inconnu', () => {
    expect(isFreeBusyCompatible(['alice@acme.com'], 'gmail')).toBe(true);
  });

  it('retourne true : outlook + domaine corporate inconnu', () => {
    expect(isFreeBusyCompatible(['bob@mycompany.io'], 'outlook')).toBe(true);
  });

  it('retourne true : provider inconnu + n\'importe quel domaine', () => {
    expect(isFreeBusyCompatible(['alice@gmail.com'], undefined)).toBe(true);
    expect(isFreeBusyCompatible(['bob@outlook.com'], undefined)).toBe(true);
  });

  // ── Mixte : un participant OK + un participant cross-provider ────────────────
  it('retourne false : gmail + mix @gmail.com + @outlook.com', () => {
    expect(isFreeBusyCompatible(['alice@gmail.com', 'bob@outlook.com'], 'gmail')).toBe(false);
  });

  it('retourne true : gmail + plusieurs participants @gmail.com', () => {
    expect(isFreeBusyCompatible(['alice@gmail.com', 'carol@googlemail.com'], 'gmail')).toBe(true);
  });

  // ── Emails malformés (sans @) ────────────────────────────────────────────────
  it('retourne true : email sans @ traité comme domaine corporate (optimiste)', () => {
    expect(isFreeBusyCompatible(['not-an-email'], 'gmail')).toBe(true);
    expect(isFreeBusyCompatible(['not-an-email'], 'outlook')).toBe(true);
  });

  // ── Casse ────────────────────────────────────────────────────────────────────
  it('retourne false : domaine en majuscules (OUTLOOK.COM) → cross-provider détecté', () => {
    expect(isFreeBusyCompatible(['alice@OUTLOOK.COM'], 'gmail')).toBe(false);
  });
});

describe('buildDescriptionWithLabels', () => {
  it('retourne "" si notes vides et aucun label', () => {
    expect(buildDescriptionWithLabels('', [])).toBe('');
  });

  it('retourne les notes seules si aucun label', () => {
    expect(buildDescriptionWithLabels('Réunion hebdo', [])).toBe('Réunion hebdo');
  });

  it('retourne le tag seul si notes vides et labels présents', () => {
    expect(buildDescriptionWithLabels('', ['projet-alpha', 'projet-beta'])).toBe('[tags:projet-alpha,projet-beta]');
  });

  it('concatène notes + newline + tag si les deux présents', () => {
    expect(buildDescriptionWithLabels('Ordre du jour', ['projet-x'])).toBe('Ordre du jour\n[tags:projet-x]');
  });

  it('encode un seul label sans virgule trailing', () => {
    expect(buildDescriptionWithLabels('', ['mon-projet'])).toBe('[tags:mon-projet]');
  });

  it('encode les virgules dans les noms de labels (F1)', () => {
    const result = buildDescriptionWithLabels('', ['Projet A,B']);
    expect(result).toBe('[tags:Projet%20A%2CB]');
    expect(result).not.toContain('Projet A,B');
  });

  it('round-trip : buildDescriptionWithLabels → parseDescriptionAndLabels', () => {
    const notes = 'Ordre du jour';
    const labels = ['projet-alpha', 'Projet A,B'];
    const desc = buildDescriptionWithLabels(notes, labels);
    const parsed = parseDescriptionAndLabels(desc);
    expect(parsed.notes).toBe(notes);
    expect(parsed.labels).toEqual(labels);
  });
});

describe('parseDescriptionAndLabels', () => {
  it('retourne la description inchangée si pas de [tags:]', () => {
    const result = parseDescriptionAndLabels('Notes normales');
    expect(result.notes).toBe('Notes normales');
    expect(result.labels).toEqual([]);
  });

  it('extrait les labels et les notes', () => {
    const result = parseDescriptionAndLabels('Réunion\n[tags:projet-x,projet-y]');
    expect(result.notes).toBe('Réunion');
    expect(result.labels).toEqual(['projet-x', 'projet-y']);
  });

  it('gère description avec seulement un tag', () => {
    const result = parseDescriptionAndLabels('[tags:mon-projet]');
    expect(result.notes).toBe('');
    expect(result.labels).toEqual(['mon-projet']);
  });

  it('décode les labels encodés (encodeURIComponent)', () => {
    const result = parseDescriptionAndLabels('[tags:Projet%20A%2CB]');
    expect(result.labels).toEqual(['Projet A,B']);
  });

  // 2026-06-01: full path used by the event modal — Acuity blob is trimmed to header
  it('nettoie une description Acuity (notes = en-tête contact uniquement)', () => {
    const acuity = '2 juin 2026 11:30 EDT Calendar: Karine Morel Nom: Corinne Dumas Téléphone: +15144394720 E-mail: corinnedumas77@gmail.com Prix : 333,00 $CA Lieu ============ Cliquez pour rejoindre la réunion : https://app.acuityscheduling.com/schedule.php?owner=28130519 Infolettre ============ Merci pour ta confiance!';
    const result = parseDescriptionAndLabels(acuity);
    expect(result.notes).toContain('Corinne Dumas');
    expect(result.notes).toContain('corinnedumas77@gmail.com');
    expect(result.notes).not.toContain('Infolettre');
    expect(result.notes).not.toContain('acuityscheduling');
    expect(result.notes).not.toContain('============');
  });
});

describe('stripExternalMeetingMetadata — Acuity / structured exports (2026-06-01)', () => {
  it('coupe au premier "Lieu ============" (format inline) et avale le mot-en-tête', () => {
    const inline = '2 juin 2026 11:30 EDT Calendar: Karine Morel Nom: Corinne Dumas Téléphone: +15144394720 E-mail: corinnedumas77@gmail.com Prix : 333,00 $CA Payé en Ligne : 333,00 $CA Lieu ============ Cliquez pour rejoindre la réunion : https://app.acuityscheduling.com/schedule.php?owner=28130519 Infolettre ============ Merci!';
    expect(stripExternalMeetingMetadata(inline)).toBe(
      '2 juin 2026 11:30 EDT Calendar: Karine Morel Nom: Corinne Dumas Téléphone: +15144394720 E-mail: corinnedumas77@gmail.com Prix : 333,00 $CA Payé en Ligne : 333,00 $CA'
    );
  });

  it('coupe au premier "Lieu\\n============" (format multi-lignes) et avale le mot-en-tête', () => {
    const lines = [
      'Nom: Corinne Dumas',
      'E-mail: corinnedumas77@gmail.com',
      '',
      'Lieu',
      '============',
      'Cliquez pour rejoindre la réunion : https://app.acuityscheduling.com/schedule.php?owner=28130519',
      '',
      'Infolettre',
      '============',
      'Merci pour ta confiance!',
    ].join('\n');
    expect(stripExternalMeetingMetadata(lines)).toBe(
      'Nom: Corinne Dumas\nE-mail: corinnedumas77@gmail.com'
    );
  });

  it('retombe sur le lien Acuity si la règle "=" est absente', () => {
    const noRule = 'Nom: Jean Dupont https://app.acuityscheduling.com/schedule.php?owner=1 du blabla';
    expect(stripExternalMeetingMetadata(noRule)).toBe('Nom: Jean Dupont');
  });

  it('ne coupe PAS une note normale avec un seul "=" ou de courtes suites', () => {
    expect(stripExternalMeetingMetadata('Budget = 5000, marge = 20%')).toBe('Budget = 5000, marge = 20%');
    expect(stripExternalMeetingMetadata('comparer x === y et a == b')).toBe('comparer x === y et a == b');
  });

  it('préserve le comportement existant (règle Teams en underscores)', () => {
    expect(stripExternalMeetingMetadata('Ordre du jour\n____________________\nMicrosoft Teams')).toBe('Ordre du jour');
  });
});

describe('formatOrganizer (2026-06-01 — masque les id de calendrier opaques)', () => {
  it('laisse passer un vrai email', () => {
    expect(formatOrganizer('karine@gmail.com')).toBe('karine@gmail.com');
  });

  it('laisse passer un nom affichable', () => {
    expect(formatOrganizer('Karine Morel')).toBe('Karine Morel');
  });

  it('masque un id de calendrier secondaire @group.calendar.google.com', () => {
    expect(formatOrganizer('47f9e61e4f267a2cb9173be1af598ec880047dbffc92938ac687d7f9375960@group.calendar.google.com')).toBeNull();
  });

  it('masque un calendrier de ressource/vacances @*.calendar.google.com', () => {
    expect(formatOrganizer('fr.french#holiday@group.v.calendar.google.com')).toBeNull();
  });

  it('masque un hash hex nu (domaine tronqué/absent)', () => {
    expect(formatOrganizer('47f9e61e4f267a2cb9173be1af598ec880047dbffc92938ac687d7f9375960')).toBeNull();
  });

  it('retourne null pour vide / null / espaces', () => {
    expect(formatOrganizer('')).toBeNull();
    expect(formatOrganizer(null)).toBeNull();
    expect(formatOrganizer(undefined)).toBeNull();
    expect(formatOrganizer('   ')).toBeNull();
  });

  it('trim un vrai email entouré d\'espaces', () => {
    expect(formatOrganizer('  karine@gmail.com  ')).toBe('karine@gmail.com');
  });
});

describe('applyLabelPrefix', () => {
  // ── Sélection d'un label avec préfixe ──────────────────────────────────────
  it('titre vide → préfixe appliqué avec espace final', () => {
    expect(applyLabelPrefix('', '888 Agentys -', null)).toBe('888 Agentys - ');
  });

  it('titre vide → préfixe déjà terminé par espace', () => {
    expect(applyLabelPrefix('', '888 Agentys - ', null)).toBe('888 Agentys - ');
  });

  it('titre = ancien préfixe → remplacé par nouveau préfixe', () => {
    expect(applyLabelPrefix('888 Agentys - ', '999 Autre -', '888 Agentys -')).toBe('999 Autre - ');
  });

  it('titre = ancien préfixe + contenu → nouveau préfixe + contenu préservé', () => {
    expect(applyLabelPrefix('888 Agentys - Ma réunion', '999 Autre -', '888 Agentys -')).toBe('999 Autre - Ma réunion');
  });

  it('titre tapé manuellement (sans préfixe actif) → non écrasé', () => {
    expect(applyLabelPrefix('Titre personnalisé', '888 Agentys -', null)).toBe('Titre personnalisé');
  });

  it('titre avec espaces seuls → préfixe appliqué sans espaces parasites', () => {
    expect(applyLabelPrefix('   ', '888 Agentys -', null)).toBe('888 Agentys - ');
  });

  it('label sans subject_prefix → titre inchangé', () => {
    expect(applyLabelPrefix('', null, null)).toBe('');
    expect(applyLabelPrefix('Mon titre', null, null)).toBe('Mon titre');
  });

  // ── Désélection d'un label ─────────────────────────────────────────────────
  it('désélection → préfixe retiré si titre commence par lui', () => {
    expect(applyLabelPrefix('888 Agentys - Ma réunion', null, '888 Agentys -')).toBe('Ma réunion');
  });

  it('désélection → titre vide si seul le préfixe était présent', () => {
    expect(applyLabelPrefix('888 Agentys - ', null, '888 Agentys -')).toBe('');
  });

  it('désélection → titre inchangé si ne commence pas par le préfixe', () => {
    expect(applyLabelPrefix('Autre titre', null, '888 Agentys -')).toBe('Autre titre');
  });

  // ── Changement de label ────────────────────────────────────────────────────
  it('changement de label → préfixe remplacé, contenu préservé', () => {
    const result = applyLabelPrefix('Agentys - Sprint review', 'ACME -', 'Agentys -');
    expect(result).toBe('ACME - Sprint review');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// computePopoverPosition — positionnement du popover
// Viewport référence : 1366×768, popover : 520px de haut (état par défaut)
// ────────────────────────────────────────────────────────────────────────────
describe('computePopoverPosition', () => {
  const W = 1366;  // largeur typique laptop
  const H = 768;   // hauteur typique laptop
  const PH = 520;  // hauteur popover (contenu standard)

  // ── Positionnement horizontal ─────────────────────────────────────────────

  it('se place à droite de l\'ancre si la place est suffisante', () => {
    // Slot en milieu de grille (~col lundi)
    const anchor = { top: 300, left: 200, right: 400 };
    const { left } = computePopoverPosition(anchor, W, H, PH);
    expect(left).toBe(400 + 12); // right + gap
  });

  it('bascule à gauche si dépasse le bord droit', () => {
    // Slot sur la dernière colonne (vendredi/samedi)
    const anchor = { top: 300, left: 1050, right: 1200 };
    const { left } = computePopoverPosition(anchor, W, H, PH);
    // 1200 + 12 + 480 = 1692 > 1366-20 → bascule à gauche
    expect(left).toBe(1050 - 480 - 12);
  });

  it('clamp à 20px si déborde à gauche même après basculement', () => {
    // Slot très à gauche, ancre étroite
    const anchor = { top: 300, left: 10, right: 50 };
    // 50 + 12 + 480 = 542 < 1366-20 → reste à droite : left = 62. OK > 20.
    const { left } = computePopoverPosition(anchor, W, H, PH);
    expect(left).toBeGreaterThanOrEqual(20);
  });

  it('clamp à 20px si ancre très à gauche ET basculement sort à gauche', () => {
    // Viewport très étroit (mobile-like 400px), ancre à gauche
    const anchor = { top: 300, left: 5, right: 40 };
    // 40 + 12 + 480 = 532 > 400-20=380 → bascule : 5 - 480 - 12 = -487 → clamp 20
    const { left } = computePopoverPosition(anchor, 400, H, PH);
    expect(left).toBe(20);
  });

  // ── Plages horaires — positionnement vertical ─────────────────────────────

  it('tôt le matin (08h00) : top normal, non clampé', () => {
    // Slot ~08h00 → anchorRect.top ≈ 100px dans la grille
    const anchor = { top: 100, left: 300, right: 500 };
    const { top } = computePopoverPosition(anchor, W, H, PH);
    // 100 - 20 = 80 ≥ 20, et maxTop = 768-520-20 = 228, 80 < 228 → pas de clamp
    expect(top).toBe(80);
  });

  it('clamp min=20 si ancre très haute (avant 08h, scroll en haut)', () => {
    const anchor = { top: 10, left: 300, right: 500 };
    const { top } = computePopoverPosition(anchor, W, H, PH);
    // 10 - 20 = -10 < 20 → clamp 20
    expect(top).toBe(20);
  });

  it('midi (12h00) : top inchangé, dans les bornes', () => {
    // Slot ~12h00 → anchorRect.top ≈ 350px
    const anchor = { top: 350, left: 300, right: 500 };
    const { top } = computePopoverPosition(anchor, W, H, PH);
    // 350 - 20 = 330. maxTop = 228. 330 > 228 → clamp 228
    expect(top).toBe(228);
  });

  it('fin d\'après-midi (17h00) : clamp maxTop', () => {
    // Slot ~17h00 → anchorRect.top ≈ 550px
    const anchor = { top: 550, left: 300, right: 500 };
    const { top } = computePopoverPosition(anchor, W, H, PH);
    // 550 - 20 = 530 > maxTop=228 → clamp 228
    expect(top).toBe(228);
  });

  it('fin de soirée (23h00) : clamp maxTop', () => {
    // Slot ~23h00 → anchorRect.top ≈ 700px (en bas de grille)
    const anchor = { top: 700, left: 300, right: 500 };
    const { top } = computePopoverPosition(anchor, W, H, PH);
    expect(top).toBe(228); // maxTop = 768-520-20
  });

  // ── Popover plus grand (contenu enrichi : labels + groupes + scheduler) ───

  it('popover long (680px) : maxTop réduit proportionnellement', () => {
    const anchor = { top: 400, left: 300, right: 500 };
    // maxTop = 768 - 680 - 20 = 68
    const { top } = computePopoverPosition(anchor, W, H, 680);
    expect(top).toBe(68);
  });

  it('popover long (680px) tôt le matin (top=80) : reste dans la fenêtre', () => {
    const anchor = { top: 80, left: 300, right: 500 };
    // top = 80-20 = 60. maxTop = 68. 60 < 68 → pas de clamp maxTop. 60 ≥ 20 → ok.
    const { top } = computePopoverPosition(anchor, W, H, 680);
    expect(top).toBe(60);
    expect(top + 680).toBeLessThanOrEqual(H); // ne dépasse pas la fenêtre
  });

  it('popover plus grand que la fenêtre : clamp à 20 (overflow géré par CSS max-height)', () => {
    // Viewport très petit (400×500), popover 600px
    const anchor = { top: 200, left: 150, right: 300 };
    // maxTop = 500 - 600 - 20 = -120. top = 200-20=180 > -120 → clamp -120. -120 < 20 → clamp 20.
    const { top } = computePopoverPosition(anchor, 400, 500, 600);
    expect(top).toBe(20);
  });

  // ── Invariants : top toujours dans [20, viewportHeight) ──────────────────

  it.each([
    ['08h00', 100], ['09h00', 150], ['10h00', 200], ['11h00', 250],
    ['12h00', 300], ['13h00', 350], ['14h00', 400], ['15h00', 450],
    ['16h00', 500], ['17h00', 550], ['18h00', 600], ['19h00', 650],
    ['20h00', 700], ['21h00', 720], ['22h00', 740], ['23h00', 755],
  ])('invariant top ≥ 20 — %s (anchorTop=%i)', (_label, anchorTop) => {
    const anchor = { top: anchorTop, left: 300, right: 500 };
    const { top } = computePopoverPosition(anchor, W, H, PH);
    expect(top).toBeGreaterThanOrEqual(20);
  });

  it.each([
    ['08h00', 100], ['12h00', 300], ['17h00', 550], ['23h00', 755],
  ])('invariant top + hauteur ≤ viewport (ou CSS scroll) — %s', (_label, anchorTop) => {
    const anchor = { top: anchorTop, left: 300, right: 500 };
    const { top } = computePopoverPosition(anchor, W, H, PH);
    // Le popover ne doit pas commencer au-delà de la limite basse
    expect(top).toBeLessThanOrEqual(H - PH - 20 + 1); // +1 pour tolérance arrondi
  });
});

