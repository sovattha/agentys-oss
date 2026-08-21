/**
 * Tests de comportement du composer vocal (#1128).
 *
 * Le flux complet est une machine à états vocale (greeting → dictée →
 * confirmation) ; ici on couvre le filet de sécurité tactile : boutons
 * back/annuler/envoyer, garde canSend, abandon avec contenu.
 */

import React from "react";
import { Alert } from "react-native";
import { fireEvent, waitFor } from "@testing-library/react-native";
import { renderWithProviders } from "../support/renderWithProviders";
import { initI18n } from "../../src/i18n";
import ComposeScreen from "../../app/compose";

const mockBack = jest.fn();
const mockTtsStop = jest.fn().mockResolvedValue(undefined);
// speak n'appelle JAMAIS onDone → la machine à états vocale reste en
// greeting_recipients, l'écran est stable pour tester les boutons.
const mockSpeak = jest.fn();

jest.mock("expo-router", () => ({
  useRouter: () => ({ back: mockBack, push: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
}));

jest.mock("../../src/hooks/useTts", () => ({
  useTts: () => ({
    state: "idle",
    error: null,
    speak: mockSpeak,
    stop: mockTtsStop,
    pause: jest.fn(),
    resume: jest.fn(),
    toggle: jest.fn(),
    prefetch: jest.fn(),
  }),
}));

// Partagé entre les renders pour être pilotable/assertable par test.
// Défaut : jamais résolu — machine inerte (tests tactiles historiques).
const mockListen = jest.fn((..._args: unknown[]) => new Promise(() => {}));
jest.mock("../../src/hooks/useVoiceDictation", () => ({
  useVoiceDictation: () => ({
    state: "idle",
    listen: mockListen,
    cancel: jest.fn().mockResolvedValue(undefined),
  }),
}));

const mockPlayEarcon = jest.fn();
jest.mock("../../src/hooks/useEarcons", () => ({
  useEarcons: () => ({ play: mockPlayEarcon }),
}));

jest.mock("../../src/services/api", () => ({
  autocompleteContacts: jest.fn().mockResolvedValue([]),
  parseComposeUtterance: jest.fn(),
  polishComposeBody: jest.fn((t: string) => Promise.resolve(t)),
  transcribeAudio: jest.fn(),
  voiceIntent: jest.fn(),
}));

jest.mock("../../src/lib/sendQueue", () => ({
  sendNewEmailSafe: jest.fn(),
}));

jest.mock("../../src/components/VoiceVisualizer", () => ({
  VoiceVisualizer: () => null,
}));
jest.mock("../../src/components/SpeakerChip", () => ({
  SpeakerChip: () => null,
}));

initI18n();

beforeEach(() => {
  jest.clearAllMocks();
  // Reset complet (implémentations + files mockResolvedValueOnce d'un test
  // précédent), puis défaut inerte pour les tests tactiles.
  mockListen.mockReset();
  mockListen.mockImplementation(() => new Promise(() => {}));
});

describe("ComposeScreen — filet de sécurité tactile", () => {
  it("rend back, annuler et envoyer avec labels accessibles", () => {
    const { getByLabelText, getAllByLabelText } = renderWithProviders(<ComposeScreen />);
    expect(getAllByLabelText("Retour").length).toBeGreaterThanOrEqual(1);
    expect(getByLabelText("annuler")).toBeTruthy();
    expect(getByLabelText("envoyer")).toBeTruthy();
  });

  it("envoyer est désactivé sans destinataire ni corps", () => {
    const { getByLabelText } = renderWithProviders(<ComposeScreen />);
    const send = getByLabelText("envoyer");
    expect(send.props.accessibilityState?.disabled).toBe(true);
  });

  it("back sans contenu quitte directement (pas d'alerte d'abandon)", async () => {
    const alertSpy = jest.spyOn(Alert, "alert");
    const { getAllByLabelText } = renderWithProviders(<ComposeScreen />);

    fireEvent.press(getAllByLabelText("Retour")[0]);

    await waitFor(() => expect(mockBack).toHaveBeenCalled());
    expect(alertSpy).not.toHaveBeenCalled();
    expect(mockTtsStop).toHaveBeenCalled(); // coupe le TTS avant de quitter
  });

  it("le greeting vocal démarre au mount", () => {
    renderWithProviders(<ComposeScreen />);
    expect(mockSpeak).toHaveBeenCalled();
  });

  it("earcon « tick » d'ouverture au mount (avant la première question TTS)", () => {
    renderWithProviders(<ComposeScreen />);
    expect(mockPlayEarcon).toHaveBeenCalledWith("tick");
  });
});

describe("ComposeScreen — flux vocal (device 2026-08-03, « Alexandre » perdu)", () => {
  it("destinataire introuvable → suggère des contacts fréquents ET ré-arme le micro", async () => {
    // Demande device 2026-08-04 : « si tu ne trouves pas le destinataire,
    // propose-moi des contacts que tu connais ». En prime, ce chemin avait le
    // même dead-end setPhase(valeur courante) → micro jamais ré-armé.
    const api = require("../../src/services/api");
    mockSpeak.mockImplementation((_text: string, onDone?: () => void) => { onDone?.(); });
    api.transcribeAudio.mockResolvedValue({ text: "Alexandre" });
    api.autocompleteContacts.mockImplementation((q: string) =>
      Promise.resolve(
        q === ""
          ? [{ name: "Marie Tremblay", email: "marie@x.co" }, { name: "Paul", email: "paul@x.co" }]
          : [], // « alexandre » : aucun contact
      ),
    );
    mockListen
      .mockResolvedValueOnce({ kind: "ok", uri: "fake://u1" } as never)
      .mockImplementation(() => new Promise(() => {}));

    renderWithProviders(<ComposeScreen />);

    // Suggestions PARLÉES avec le « je ne trouve pas »…
    await waitFor(() => {
      const texts = (mockSpeak.mock.calls as unknown[][]).map((c) => String(c[0]));
      expect(texts.some((t) => t.includes("Marie Tremblay"))).toBe(true);
    }, { timeout: 4000 });
    // …et le micro est ré-armé (pas de dead-end).
    await waitFor(() => expect(mockListen).toHaveBeenCalledTimes(2), { timeout: 4000 });
  });

  it("la relecture contient le CORPS interpolé (pas le gabarit {{body}})", async () => {
    // Device 2026-08-04 : ElevenLabs a prononcé littéralement
    // « Ton message pour X : accolade accolade body… » — recapShort avait
    // gagné {{body}} dans le template mais l'appel ne passait que {name}.
    const api = require("../../src/services/api");
    mockSpeak.mockImplementation((_text: string, onDone?: () => void) => { onDone?.(); });
    api.transcribeAudio
      .mockResolvedValueOnce({ text: "Alexandre" })
      .mockResolvedValueOnce({ text: "nouveau test depuis Agentys" });
    api.autocompleteContacts.mockImplementation((q: string) =>
      Promise.resolve(
        q === "" ? [] : [{ name: "Alexandre Avian", email: "alex@x.co" }],
      ),
    );
    mockListen
      .mockResolvedValueOnce({ kind: "ok", uri: "fake://u1" } as never)
      .mockResolvedValueOnce({ kind: "ok", uri: "fake://u2" } as never)
      .mockImplementation(() => new Promise(() => {}));

    renderWithProviders(<ComposeScreen />);

    await waitFor(() => {
      const texts = (mockSpeak.mock.calls as unknown[][]).map((c) => String(c[0]));
      const recap = texts.find((t) => t.includes("J'envoie"));
      expect(recap).toBeDefined();
      expect(recap).toContain("nouveau test depuis Agentys");
      expect(recap).not.toContain("{{");
    }, { timeout: 4000 });
  });

  it("no_voice → « je n'ai rien entendu » → le micro est RÉ-ARMÉ (pas de dead-end)", async () => {
    // Bug device : setPhase(greeting_recipients) alors que la phase est DÉJÀ
    // greeting_recipients → même valeur, pas de re-render, l'effet [phase] ne
    // se relance pas → plus jamais d'écoute. Le 2e « Alexandre » parlait à un
    // micro mort.
    mockSpeak.mockImplementation((_text: string, onDone?: () => void) => { onDone?.(); });
    mockListen
      .mockResolvedValueOnce({ kind: "no_voice" } as never)
      .mockImplementation(() => new Promise(() => {}));

    renderWithProviders(<ComposeScreen />);

    await waitFor(() => expect(mockListen).toHaveBeenCalledTimes(2), { timeout: 4000 });
  });

  it("l'écoute est séquentielle SANS AEC ni seuil anti-écho (#1134 règle 4)", async () => {
    // L'AEC (voiceChat) écrase le gain du micro (« Alexandre » à -25 dB sous
    // le seuil -28 anti-écho du barge-in). Aligné sur le drive : TTS d'abord,
    // puis écoute batch avec le seuil adaptatif du hook.
    mockSpeak.mockImplementation((_text: string, onDone?: () => void) => { onDone?.(); });

    renderWithProviders(<ComposeScreen />);

    await waitFor(() => expect(mockListen).toHaveBeenCalled());
    const opts = (mockListen.mock.calls[0][0] ?? {}) as Record<string, unknown>;
    expect(opts.useVoiceChat).toBe(false);
    expect(opts.voiceThresholdDb).toBeUndefined();
    // Sans grace, le seuil adaptatif ne calibre jamais le plancher ambiant :
    // à -26 dB ambiants avec seuil fixe -42, tout est « voix » et la fin de
    // parole par silence ne se déclenche jamais (device 2026-08-03).
    expect(opts.graceMs).toBe(600);
    // Signal de tour : earcon « à toi » entre la question et l'ouverture du
    // micro (sinon impossible de savoir quand parler — device 2026-08-03).
    expect(mockPlayEarcon).toHaveBeenCalledWith("turn");
  });
});
