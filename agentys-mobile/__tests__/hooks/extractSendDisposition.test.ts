/**
 * Step 3 — extractSendDisposition : détecte un verbe d'envoi EXPLICITE en fin
 * de dictée ("…et envoie") pour router vers l'envoi auto (fenêtre d'annulation)
 * et retire ce verbe du corps. Doit être STRICT : jamais de faux positif sur
 * un corps qui mentionne "envoyer" en son milieu.
 */
import { extractSendDisposition } from '../../src/hooks/useDriveMode';

describe('extractSendDisposition', () => {
  describe('détecte un envoi explicite en fin (connecteur)', () => {
    const sendCases: Array<[string, string]> = [
      ['réponds que je serai là à 15h, et envoie', 'réponds que je serai là à 15h'],
      ["réponds que j'accepte le budget et envoie", "réponds que j'accepte le budget"],
      ['dis-lui que je confirme puis envoie', 'dis-lui que je confirme'],
      ['reply that I will be late and send it', 'reply that I will be late'],
      ['tell him the meeting is at 3 and send', 'tell him the meeting is at 3'],
      ['confirme ma présence et envoie-le', 'confirme ma présence'],
    ];
    it.each(sendCases)('%s → send', (input, expectedBody) => {
      const r = extractSendDisposition(input);
      expect(r.send).toBe(true);
      expect(r.body).toBe(expectedBody);
    });
  });

  describe('détecte un envoi explicite en fin (ponctuation)', () => {
    it('point + verbe', () => {
      const r = extractSendDisposition("réponds que j'accepte. Envoie.");
      expect(r.send).toBe(true);
      expect(r.body).toBe("réponds que j'accepte");
    });
  });

  describe('homophones FR du suffixe (Deepgram choisit la graphie au hasard)', () => {
    // Retour device 2026-07-28 : « Ok merci, envoyez. » bufferisé comme
    // contenu — le suffixe ne couvrait que envoie/envoyer/send, pas la
    // famille [ɑ̃vwaje] déjà admise par isSendUtterance.
    const homophoneCases: Array<[string, string]> = [
      ['Ok merci, envoyez.', 'Ok merci'],
      ['je serai là à 15h. Envoyé.', 'je serai là à 15h'],
      ['confirme la réunion et envoyez', 'confirme la réunion'],
      ['merci beaucoup, envoi', 'merci beaucoup'],
    ];
    it.each(homophoneCases)('%s → send', (input, expectedBody) => {
      const r = extractSendDisposition(input);
      expect(r.send).toBe(true);
      expect(r.body).toBe(expectedBody);
    });
  });

  describe('PAS de faux positif (verbe au milieu / commande seule / trop court)', () => {
    const noSend = [
      "dis-lui d'envoyer le contrat avant lundi", // "envoyer" au milieu
      'demande à Paul de tout envoyer demain',     // verbe non terminal
      'envoie',                                     // commande seule
      'send it',                                    // commande seule
      'envoie-le',                                  // commande seule
      'ok, envoie',                                 // corps "ok" < 3 chars
      'rappelle-moi demain matin',                  // aucun verbe d'envoi
      '',                                           // vide
    ];
    it.each(noSend)('%s → pas d\'envoi', (input) => {
      const r = extractSendDisposition(input);
      expect(r.send).toBe(false);
      expect(r.body).toBe((input || '').trim());
    });
  });
});
