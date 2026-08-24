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

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MyStyle } from "../components/MyStyle";

vi.stubGlobal('fetch', vi.fn());

const mockLearningStats = {
  total_feedback: 42,
  positive_feedback: 35,
  negative_feedback: 7,
  patterns_count: 8,
  last_learning_date: "2026-01-04T10:30:00Z",
  validation_rate: 83.3,
};

const mockLearningPatterns = {
  count: 3,
  patterns: [
    {
      id: "1",
      pattern_type: "signature",
      description: "Signature formelle avec poste",
      confidence: 0.95,
      examples: ["Cordialement,", "Bien cordialement,"],
      created_at: "2026-01-02T08:00:00Z",
    },
    {
      id: "2",
      pattern_type: "greeting",
      description: "Salutation vouvoiement",
      confidence: 0.88,
      examples: ["Bonjour,", "Madame, Monsieur,"],
      created_at: "2026-01-03T14:00:00Z",
    },
    {
      id: "3",
      pattern_type: "tone",
      description: "Ton professionnel",
      confidence: 0.72,
      examples: [],
      created_at: "2026-01-04T09:00:00Z",
    },
  ],
};

function mockFetchSuccess() {
  (fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url.includes("/learning/stats")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockLearningStats),
      });
    }
    if (url.includes("/learning/patterns")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockLearningPatterns),
      });
    }
    return Promise.reject(new Error("Unknown URL"));
  });
}

function mockFetchError() {
  (fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("Network error"));
}

describe("MyStyle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("affiche le titre et le bouton fermer", async () => {
    mockFetchSuccess();
    render(<MyStyle onClose={() => {}} />);

    expect(screen.getByText("Mon Style")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /fermer/i })).toBeInTheDocument();
  });

  it("appelle onClose quand on clique sur fermer", async () => {
    mockFetchSuccess();
    const handleClose = vi.fn();
    render(<MyStyle onClose={handleClose} />);

    const closeButton = screen.getByRole("button", { name: /fermer/i });
    fireEvent.click(closeButton);

    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it("affiche un indicateur de chargement", () => {
    mockFetchSuccess();
    render(<MyStyle onClose={() => {}} />);

    expect(screen.getByText(/chargement/i)).toBeInTheDocument();
  });

  it("affiche les statistiques une fois chargees", async () => {
    mockFetchSuccess();
    render(<MyStyle onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("Statistiques")).toBeInTheDocument();
    });

    expect(screen.getByText(/42/)).toBeInTheDocument();
    expect(screen.getByText(/83/)).toBeInTheDocument();
    // patterns_count (8) and its label are rendered in separate spans
    expect(screen.getAllByText('8').length).toBeGreaterThan(0);
  });

  it("affiche la jauge de maturite IA", async () => {
    mockFetchSuccess();
    render(<MyStyle onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText(/maturit/i)).toBeInTheDocument();
    });

    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });

  it("affiche les patterns appris", async () => {
    mockFetchSuccess();
    render(<MyStyle onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("Patterns appris")).toBeInTheDocument();
    });

    expect(screen.getByText("Signature")).toBeInTheDocument();
    expect(screen.getByText("Salutation")).toBeInTheDocument();
    expect(screen.getByText("Ton professionnel")).toBeInTheDocument();
  });

  it("affiche les exemples pour chaque pattern", async () => {
    mockFetchSuccess();
    render(<MyStyle onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText(/"Cordialement,"/)).toBeInTheDocument();
    });

    expect(screen.getByText(/"Bonjour,"/)).toBeInTheDocument();
  });

  it("affiche le niveau de confiance pour chaque pattern", async () => {
    mockFetchSuccess();
    render(<MyStyle onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText(/95%/)).toBeInTheDocument();
    });

    expect(screen.getByText(/88%/)).toBeInTheDocument();
    expect(screen.getByText(/72%/)).toBeInTheDocument();
  });

  it("affiche une erreur si le chargement échoue", async () => {
    mockFetchError();
    render(<MyStyle onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText(/erreur/i)).toBeInTheDocument();
    });
  });

  it("affiche un message si aucun pattern n'est disponible", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes("/learning/stats")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ ...mockLearningStats, patterns_count: 0 }),
        });
      }
      if (url.includes("/learning/patterns")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ count: 0, patterns: [] }),
        });
      }
      return Promise.reject(new Error("Unknown URL"));
    });

    render(<MyStyle onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText(/aucun pattern/i)).toBeInTheDocument();
    });
  });

  it("affiche la section timeline avec la date du dernier apprentissage", async () => {
    mockFetchSuccess();
    render(<MyStyle onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText(/timeline/i)).toBeInTheDocument();
    });

    // Date is formatted as ISO compact date "2026-01-04" by formatCompactDate
    expect(screen.getByText(/2026-01-04/)).toBeInTheDocument();
  });
});
