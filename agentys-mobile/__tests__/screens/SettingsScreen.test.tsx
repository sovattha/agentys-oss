/**
 * Tests de comportement de l'écran Réglages (#1128) :
 * rendu des sections, changement de langue, logout, a11y (#1127).
 */

import React from "react";
import { fireEvent, waitFor } from "@testing-library/react-native";
import { renderWithProviders } from "../support/renderWithProviders";
import { initI18n } from "../../src/i18n";
import SettingsScreen from "../../app/settings";

const mockBack = jest.fn();
const mockPush = jest.fn();
const mockSetLanguage = jest.fn();
const mockSetSpeechRate = jest.fn();
const mockSetAutoAdvance = jest.fn();
const mockLogout = jest.fn().mockResolvedValue(undefined);

jest.mock("expo-router", () => ({
  useRouter: () => ({ back: mockBack, push: mockPush, replace: jest.fn() }),
}));

jest.mock("../../src/hooks/useVoiceSettings", () => ({
  useVoiceSettings: () => ({
    availableVoices: [{ voice_id: "voice-1", name: "Aria", category: "premade" }],
    voicesLoading: false,
    voicesError: null,
    selectedVoice: "voice-1",
    speechRate: 1.0,
    autoAdvance: false,
    autoAdvanceDelay: 2,
    setVoice: jest.fn(),
    setSpeechRate: mockSetSpeechRate,
    setAutoAdvance: mockSetAutoAdvance,
    setAutoAdvanceDelay: jest.fn(),
    previewVoice: jest.fn(),
    refreshVoices: jest.fn(),
    cloneVoice: jest.fn(),
    deleteVoice: jest.fn(),
  }),
}));

jest.mock("../../src/hooks/useLanguageSync", () => ({
  useLanguage: () => ({ language: "fr", setLanguage: mockSetLanguage }),
}));

initI18n();

function renderSettings() {
  return renderWithProviders(<SettingsScreen />, { logout: mockLogout });
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("SettingsScreen", () => {
  it("rend les sections principales avec labels accessibles", () => {
    const { getByLabelText } = renderSettings();
    expect(getByLabelText("Langue")).toBeTruthy();
    expect(getByLabelText("Voix sélectionnée")).toBeTruthy();
    expect(getByLabelText("Se déconnecter")).toBeTruthy();
  });

  it("ouvre la liste des langues et applique un choix", async () => {
    const { getByLabelText } = renderSettings();

    fireEvent.press(getByLabelText("Langue"));
    fireEvent.press(getByLabelText("English"));

    await waitFor(() => expect(mockSetLanguage).toHaveBeenCalledWith("en"));
  });

  it("change la vitesse de lecture via les segments", async () => {
    const { getByLabelText } = renderSettings();
    fireEvent.press(getByLabelText("1.5×"));
    // onPress async (Haptics await avant setSpeechRate)
    await waitFor(() => expect(mockSetSpeechRate).toHaveBeenCalledWith(1.5));
  });

  it("bascule l'auto-avancement via le switch", () => {
    const { getByLabelText } = renderSettings();
    fireEvent(getByLabelText("Passer automatiquement"), "valueChange", true);
    expect(mockSetAutoAdvance).toHaveBeenCalledWith(true);
  });

  it("le bouton retour revient en arrière", () => {
    const { getByLabelText } = renderSettings();
    fireEvent.press(getByLabelText("Retour"));
    expect(mockBack).toHaveBeenCalled();
  });
});
