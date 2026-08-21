/**
 * frenchNumbers — #1134 : nombres en lettres pour éviter la normalisation
 * anglaise d'ElevenLabs (« 66 » → « sixty-six »).
 */
import { toFrenchWords, spellFrenchNumbers } from "../../src/lib/frenchNumbers";

describe("toFrenchWords", () => {
  it.each([
    [0, "zéro"],
    [1, "un"],
    [16, "seize"],
    [17, "dix-sept"],
    [21, "vingt-et-un"],
    [22, "vingt-deux"],
    [66, "soixante-six"],
    [70, "soixante-dix"],
    [71, "soixante-et-onze"],
    [79, "soixante-dix-neuf"],
    [80, "quatre-vingts"],
    [81, "quatre-vingt-un"],
    [90, "quatre-vingt-dix"],
    [91, "quatre-vingt-onze"],
    [99, "quatre-vingt-dix-neuf"],
    [100, "cent"],
    [101, "cent un"],
    [200, "deux cents"],
    [242, "deux cent quarante-deux"],
  ])("convertit %i → %s", (n, expected) => {
    expect(toFrenchWords(n)).toBe(expected);
  });

  it("laisse les nombres hors plage (>999) en chiffres", () => {
    expect(toFrenchWords(1000)).toBe("1000");
    expect(toFrenchWords(-3)).toBe("-3");
  });
});

describe("spellFrenchNumbers", () => {
  it("remplace le compteur du briefing (cas #1134)", () => {
    expect(spellFrenchNumbers("66 emails. C'est parti.")).toBe(
      "soixante-six emails. C'est parti.",
    );
  });

  it("remplace plusieurs nombres dans une phrase", () => {
    expect(spellFrenchNumbers("14 actions, 7 infos.")).toBe(
      "quatorze actions, sept infos.",
    );
  });

  it("laisse le texte sans nombre intact", () => {
    expect(spellFrenchNumbers("C'est parti.")).toBe("C'est parti.");
  });
});
