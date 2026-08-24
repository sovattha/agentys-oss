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

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { AutostartToggle } from "../components/AutostartToggle";

vi.mock("@tauri-apps/plugin-autostart", () => ({
  enable: vi.fn(),
  disable: vi.fn(),
  isEnabled: vi.fn(),
}));

import { enable, disable, isEnabled } from "@tauri-apps/plugin-autostart";

const mockIsEnabled = vi.mocked(isEnabled);
const mockEnable = vi.mocked(enable);
const mockDisable = vi.mocked(disable);

describe("AutostartToggle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Mock Tauri context so component renders
    (window as unknown as { __TAURI_INTERNALS__: boolean }).__TAURI_INTERNALS__ = true;
  });

  afterEach(() => {
    // Clean up Tauri mock
    delete (window as unknown as { __TAURI_INTERNALS__?: boolean }).__TAURI_INTERNALS__;
  });

  it("affiche l'état de chargement initial", () => {
    mockIsEnabled.mockImplementation(() => new Promise(() => {}));
    render(<AutostartToggle />);
    expect(screen.getByText("...")).toBeInTheDocument();
  });

  it("affiche le toggle désactivé quand autostart est off", async () => {
    mockIsEnabled.mockResolvedValue(false);
    render(<AutostartToggle />);

    await waitFor(() => {
      const checkbox = screen.getByRole("checkbox");
      expect(checkbox).not.toBeChecked();
    });
  });

  it("affiche le toggle activé quand autostart est on", async () => {
    mockIsEnabled.mockResolvedValue(true);
    render(<AutostartToggle />);

    await waitFor(() => {
      const checkbox = screen.getByRole("checkbox");
      expect(checkbox).toBeChecked();
    });
  });

  it("active l'autostart quand on clique sur un toggle désactivé", async () => {
    mockIsEnabled.mockResolvedValue(false);
    mockEnable.mockResolvedValue();
    render(<AutostartToggle />);

    await waitFor(() => {
      expect(screen.getByRole("checkbox")).toBeInTheDocument();
    });

    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);

    await waitFor(() => {
      expect(mockEnable).toHaveBeenCalledTimes(1);
      expect(checkbox).toBeChecked();
    });
  });

  it("désactive l'autostart quand on clique sur un toggle activé", async () => {
    mockIsEnabled.mockResolvedValue(true);
    mockDisable.mockResolvedValue();
    render(<AutostartToggle />);

    await waitFor(() => {
      expect(screen.getByRole("checkbox")).toBeInTheDocument();
    });

    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);

    await waitFor(() => {
      expect(mockDisable).toHaveBeenCalledTimes(1);
      expect(checkbox).not.toBeChecked();
    });
  });

  it("affiche une erreur si la vérification échoue", async () => {
    mockIsEnabled.mockRejectedValue(new Error("Test error"));
    render(<AutostartToggle />);

    await waitFor(() => {
      expect(
        screen.getByText("Impossible de vérifier le statut")
      ).toBeInTheDocument();
    });
  });

  it("affiche une erreur si l'activation échoue", async () => {
    mockIsEnabled.mockResolvedValueOnce(false);
    mockEnable.mockRejectedValue(new Error("Enable failed"));
    render(<AutostartToggle />);

    await waitFor(() => {
      expect(screen.getByRole("checkbox")).toBeInTheDocument();
    });

    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);

    await waitFor(() => {
      expect(mockEnable).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(screen.getByText(/Échec de la modification/)).toBeInTheDocument();
    });
  });

  it("accepte une className personnalisée", async () => {
    mockIsEnabled.mockResolvedValue(false);
    const { container } = render(<AutostartToggle className="custom-class" />);

    await waitFor(() => {
      const toggle = container.querySelector(".autostart-toggle");
      expect(toggle).toHaveClass("custom-class");
    });
  });
});
