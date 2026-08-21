/**
 * Accusé PARLÉ des commandes vocales — au volant l'écran n'est pas regardé,
 * le badge « ✓ SUIVANT » n'apprend donc rien à l'utilisateur.
 */

import fr from "../../src/i18n/locales/fr/drive.json";
import en from "../../src/i18n/locales/en/drive.json";
import {
  SPOKEN_ACK_COMMANDS,
  SPOKEN_ACK_MAX_AGE_MS,
  applySpokenAck,
  isSpokenAckCommand,
} from "../../src/lib/driveCommands";

describe("périmètre des commandes annoncées", () => {
  test("les commandes muettes (navigation, disposition) sont annoncées", () => {
    expect(isSpokenAckCommand("NEXT")).toBe(true);
    expect(isSpokenAckCommand("DELETE")).toBe(true);
    expect(isSpokenAckCommand("ARCHIVE")).toBe(true);
    expect(isSpokenAckCommand("PREVIOUS")).toBe(true);
  });

  test("les commandes qui parlent déjà ne sont PAS doublées", () => {
    // APPROVE dit « J'envoie. », STOP/PAUSE/REPEAT ont leur propre réponse :
    // les préfixer donnerait « Envoyé. J'envoie. »
    expect(isSpokenAckCommand("APPROVE")).toBe(false);
    expect(isSpokenAckCommand("STOP")).toBe(false);
    expect(isSpokenAckCommand("PAUSE")).toBe(false);
    expect(isSpokenAckCommand("REPEAT")).toBe(false);
    expect(isSpokenAckCommand("CANCEL_REPLY")).toBe(false);
  });

  // Panne silencieuse à éviter : une commande ajoutée à la liste sans son
  // libellé retomberait sur `defaultValue: ""` → aucun accusé, sans erreur.
  test.each(SPOKEN_ACK_COMMANDS)("%s a un libellé parlé en FR et en EN", (cmd) => {
    expect(fr.cmdAck[cmd as keyof typeof fr.cmdAck]).toBeTruthy();
    expect(en.cmdAck[cmd as keyof typeof en.cmdAck]).toBeTruthy();
  });
});

describe("applySpokenAck", () => {
  const NOW = 1_000_000;

  test("préfixe l'énoncé au lieu de le remplacer", () => {
    // Un « Supprimé. » dit à part serait tranché net par la lecture suivante.
    expect(applySpokenAck("De Marc, objet réunion.", { label: "Supprimé", at: NOW }, NOW))
      .toBe("Supprimé. De Marc, objet réunion.");
  });

  test("laisse l'énoncé intact sans accusé en attente", () => {
    expect(applySpokenAck("De Marc.", null, NOW)).toBe("De Marc.");
  });

  test("laisse l'énoncé intact si l'accusé est périmé", () => {
    // Cas réel : « précédent » sur le 1er email ne déclenche aucune lecture —
    // l'accusé orphelin ne doit pas resurgir collé à un énoncé sans rapport.
    const stale = { label: "Précédent", at: NOW - SPOKEN_ACK_MAX_AGE_MS - 1 };
    expect(applySpokenAck("J'écoute.", stale, NOW)).toBe("J'écoute.");
  });

  test("accepte un accusé juste sous la limite de péremption", () => {
    const fresh = { label: "Archivé", at: NOW - SPOKEN_ACK_MAX_AGE_MS };
    expect(applySpokenAck("De Léa.", fresh, NOW)).toBe("Archivé. De Léa.");
  });

  test("ignore un libellé vide (clé i18n manquante)", () => {
    expect(applySpokenAck("De Marc.", { label: "", at: NOW }, NOW)).toBe("De Marc.");
  });
});
