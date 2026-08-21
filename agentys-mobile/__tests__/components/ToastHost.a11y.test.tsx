/**
 * A11y ToastHost (#1127) : les toasts sont annoncés aux lecteurs d'écran
 * (announceForAccessibility) et exposés en role=alert avec label + hint.
 */

import React from "react";
import { AccessibilityInfo } from "react-native";
import { act, waitFor } from "@testing-library/react-native";
import { renderWithProviders } from "../support/renderWithProviders";
import { ToastHost } from "../../src/components/ToastHost";
import { toast } from "../../src/lib/toast";

describe("ToastHost — accessibilité", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("annonce le texte du toast via announceForAccessibility", async () => {
    const announceSpy = jest
      .spyOn(AccessibilityInfo, "announceForAccessibility")
      .mockImplementation(() => {});

    renderWithProviders(<ToastHost />);
    act(() => {
      toast.error("Backend indisponible");
    });

    await waitFor(() =>
      expect(announceSpy).toHaveBeenCalledWith("Backend indisponible")
    );
  });

  it("expose le toast en role alert avec le texte en label", async () => {
    const { findByRole } = renderWithProviders(<ToastHost />);
    act(() => {
      toast.info("Brouillon prêt");
    });

    const alert = await findByRole("alert");
    expect(alert.props.accessibilityLabel).toBe("Brouillon prêt");
    expect(alert.props.accessibilityHint).toBeTruthy();
  });
});
