/**
 * isSendUtterance — ordre d'envoi vocal, tolérant aux homophones FR.
 *
 * Régression device 2026-07 : « envoyer » dit après la dictée était transcrit
 * « Envoyé. » par Deepgram (homophone [ɑ̃vwaje]) et le matcher infinitif-only
 * le versait dans le buffer de dictée au lieu d'envoyer.
 */
import { isSendUtterance } from '../../src/lib/driveCommands';

describe('isSendUtterance', () => {
  it.each([
    'envoyer', 'Envoyer.', 'Envoyé.', 'envoyée', 'Envoyez !', 'Envoi.',
    'envoie', 'Envoies.', "J'envoie.", 'envoie-le', 'envoie ça', 'Envoyé-moi',
    'send', 'Send it.', 'send-it',
  ])('accepte %j (famille homophone / clitiques)', (u) => {
    expect(isSendUtterance(u)).toBe(true);
  });

  it.each([
    // Contenu de dictée mentionnant le verbe — ne doit JAMAIS envoyer.
    "dis-lui d'envoyer le contrat",
    'et envoie-lui aussi la facture',
    "tu peux envoyer le rapport demain",
    "l'envoi est prévu lundi",
    // Autres commandes / bruit.
    'archiver', 'suivant', 'oui', '', '   ',
  ])('refuse %j (contenu ou autre commande)', (u) => {
    expect(isSendUtterance(u)).toBe(false);
  });
});

// Famille « annuler » en énoncé ENTIER (device 2026-08-04 : « Annulé. » en
// relecture regénérait le brouillon avec "Annulé" comme instruction, et le
// second « Annulé » mourait en silence).
import { isCancelUtterance } from '../../src/lib/driveCommands';

describe('isCancelUtterance', () => {
  it.each([
    'annule', 'Annule.', 'Annulé.', 'Annulé', 'annuler', 'Annuler.',
    'Annulez !', "J'annule.", 'annule tout', 'annule ça',
    'cancel', 'Cancel it.', 'laisse tomber', 'abandonne',
  ])('accepte %j (famille homophone)', (u) => {
    expect(isCancelUtterance(u)).toBe(true);
  });

  it.each([
    // Contenu mentionnant le verbe — ne doit JAMAIS annuler.
    'annule mon vol de demain',
    'peux-tu annuler la réunion',
    "dis-lui que j'annule le rendez-vous",
    // Autres commandes / bruit.
    'envoyer', 'suivant', 'oui', '', '   ',
  ])('refuse %j (contenu ou autre commande)', (u) => {
    expect(isCancelUtterance(u)).toBe(false);
  });
});
