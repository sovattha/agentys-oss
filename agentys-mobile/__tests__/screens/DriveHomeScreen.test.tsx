/**
 * Tests de comportement de l'écran home (#1128) :
 * compteurs affichés, état vide célébré, erreur de chargement, redirect login.
 */

import React from "react";
import { Animated } from "react-native";
import { waitFor } from "@testing-library/react-native";
import { renderWithProviders } from "../support/renderWithProviders";
import { initI18n } from "../../src/i18n";
import DriveHomeScreen from "../../app/index";

const mockReplace = jest.fn();
const mockGetLabelCounts = jest.fn();

jest.mock("expo-router", () => ({
  useRouter: () => ({ replace: mockReplace, push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({}),
}));

jest.mock("../../src/services/api", () => ({
  getEmails: jest.fn().mockResolvedValue({ emails: [] }),
  getLabelCounts: (...args: unknown[]) => mockGetLabelCounts(...args),
  getEmailIdsByLabel: jest.fn().mockResolvedValue({ email_ids: [], count: 0 }),
  getVoiceBriefing: jest.fn().mockResolvedValue({ text: "", source: "test" }),
  getUserName: jest.fn().mockResolvedValue(null),
}));

jest.mock("../../src/hooks/useWebSocket", () => ({
  useWebSocket: () => {},
}));

// Drive mode : état idle inerte — on teste le home, pas la session vocale.
jest.mock("../../src/hooks/useDriveMode", () => ({
  useDriveMode: () => ({
    state: "idle",
    replyMode: null,
    currentEmail: null,
    emails: [],
    currentIndex: 0,
    draftContent: null,
    error: null,
    isListening: false,
    transcript: "",
    commandRecognized: null,
    sessionStats: null,
    queuedCount: 0,
    generatingElapsedMs: 0,
    pendingResume: null,
    startSession: jest.fn(),
    resumeSession: jest.fn(),
    enqueueEmail: jest.fn(),
    next: jest.fn(),
    previous: jest.fn(),
    chooseReply: jest.fn(),
    approveContextual: jest.fn(),
    approveDraftAndNext: jest.fn(),
    rejectAndRelisten: jest.fn(),
    archiveAndNext: jest.fn(),
    deleteAndNext: jest.fn(),
    reset: jest.fn(),
    dismissResume: jest.fn(),
    sttAvailable: false,
    idleListening: false,
    startIdleSTT: jest.fn(),
    stopIdleSTT: jest.fn(),
    stopWithFarewell: jest.fn(),
    audioLevel: new (require("react-native").Animated.Value)(0),
    ttsState: "idle",
    interruptAndListen: jest.fn(),
    pendingActionCount: 0,
    undoLastAction: jest.fn(),
  }),
}));

jest.mock("../../src/hooks/useTts", () => ({
  useTts: () => ({
    state: "idle",
    error: null,
    speak: jest.fn(),
    stop: jest.fn().mockResolvedValue(undefined),
    pause: jest.fn(),
    resume: jest.fn(),
    toggle: jest.fn(),
    prefetch: jest.fn(),
  }),
}));

jest.mock("../../src/components/BreathingTriangle", () => ({
  BreathingTriangle: () => null,
}));
jest.mock("../../src/components/Greeting", () => ({
  Greeting: () => null,
}));
jest.mock("../../src/components/OnboardingTour", () => ({
  OnboardingTour: () => null,
  ONBOARDING_KEY: "onboarding_seen",
}));

initI18n();

beforeEach(() => {
  jest.clearAllMocks();
  const SecureStore = require("expo-secure-store");
  // Onboarding déjà vu (sinon l'écran rend l'OnboardingTour à la place du
  // home) ; pas de cache counts.
  (SecureStore.getItemAsync as jest.Mock).mockImplementation((key: string) =>
    Promise.resolve(key === "onboarding_seen" ? "true" : null)
  );
});

describe("DriveHomeScreen", () => {
  it("démarre direct sur le drive : vue de boot avec compteur, pas d'écran bouton", async () => {
    mockGetLabelCounts.mockResolvedValue({ counts: { Action: 5, FYI: 3 }, total: 8 });

    const { findByText, queryByText } = renderWithProviders(<DriveHomeScreen />);

    // Retour device 2026-07 : plus d'écran « Écouter mes messages » au boot —
    // la session auto-démarre, on n'affiche qu'une vue de préparation avec le
    // compteur. (Le hook drive est mocké inerte, donc on reste sur cette vue.)
    expect(await findByText("8 messages — démarrage…")).toBeTruthy();
    expect(queryByText("Écouter mes messages (8)")).toBeNull();
  });

  it("célèbre l'inbox zero (EmptyState) quand tout est traité", async () => {
    mockGetLabelCounts.mockResolvedValue({ counts: { Action: 0, FYI: 0 }, total: 0 });

    const { queryByText, findAllByText } = renderWithProviders(<DriveHomeScreen />);

    // Les cartes catégories ne doivent PAS être rendues…
    await waitFor(() => expect(queryByText("0")).toBeNull());
    // …au profit de l'EmptyState (dont le contenu varie — on vérifie juste
    // qu'aucune carte "Action" n'est présente).
    expect(queryByText(/Actions?/)).toBeNull();
    void findAllByText;
  });

  it("affiche l'erreur de chargement si le backend échoue", async () => {
    mockGetLabelCounts.mockRejectedValue(new Error("HTTP 503"));

    const { findByText } = renderWithProviders(<DriveHomeScreen />);
    const { t } = require("../../src/i18n").default;
    expect(await findByText(t("loadCountsError", { ns: "inbox" }))).toBeTruthy();
  });

  it("redirige vers /login si non authentifié", async () => {
    mockGetLabelCounts.mockResolvedValue({ counts: {}, total: 0 });

    renderWithProviders(<DriveHomeScreen />, { isAuthenticated: false });

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/login"));
  });
});
