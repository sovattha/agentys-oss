import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { BeforeAfterComparison } from "../components/BeforeAfterComparison";

vi.stubGlobal('fetch', vi.fn());

const mockComparisonData = {
  comparisons: [
    {
      id: "1",
      email_subject: "Demande de devis",
      before: {
        date: "2026-01-02T10:00:00Z",
        response: "Bonjour, merci pour votre email. Nous reviendrons vers vous.",
        score: 2,
        issues: ["Trop générique", "Pas de signature"],
      },
      after: {
        date: "2026-01-04T10:00:00Z",
        response: "Bonjour Monsieur Dupont,\n\nMerci pour votre demande de devis. Je vous envoie notre proposition dans les 24h.\n\nCordialement,\nJean Martin",
        score: 5,
        improvements: ["Personnalisé", "Signature ajoutée", "Engagement clair"],
      },
    },
    {
      id: "2",
      email_subject: "Problème technique",
      before: {
        date: "2026-01-01T08:00:00Z",
        response: "Votre problème a été noté. Bonne journée.",
        score: 1,
        issues: ["Trop court", "Pas empathique", "Aucun suivi proposé"],
      },
      after: {
        date: "2026-01-04T14:00:00Z",
        response: "Bonjour,\n\nJe comprends votre frustration face à ce problème. Notre équipe technique est sur le coup et je vous tiens informé des avancées.\n\nN'hésitez pas à me contacter si besoin.\n\nBien cordialement,\nJean Martin",
        score: 4,
        improvements: ["Ton empathique", "Suivi proposé", "Contact direct"],
      },
    },
  ],
  improvement_summary: {
    average_score_before: 1.5,
    average_score_after: 4.5,
    improvement_percentage: 200,
    top_improvements: ["Personnalisation", "Signature", "Ton"],
  },
};

function mockFetchSuccess() {
  (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(mockComparisonData),
  });
}

function mockFetchEmpty() {
  (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({
      comparisons: [],
      improvement_summary: null,
    }),
  });
}

function mockFetchError() {
  (fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("Network error"));
}

describe("BeforeAfterComparison", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("affiche le titre de la section", async () => {
    mockFetchSuccess();
    render(<BeforeAfterComparison />);

    expect(screen.getByText(/avant.*apr/i)).toBeInTheDocument();
  });

  it("affiche un indicateur de chargement", () => {
    mockFetchSuccess();
    render(<BeforeAfterComparison />);

    expect(screen.getByText(/chargement/i)).toBeInTheDocument();
  });

  it("affiche les comparaisons une fois chargees", async () => {
    mockFetchSuccess();
    render(<BeforeAfterComparison />);

    await waitFor(() => {
      const subjectElement = screen.getByText(/E-mail\s*:/i).parentElement;
      expect(subjectElement).toHaveTextContent(/demande de devis/i);
    });
  });

  it("affiche le score avant et apres pour chaque comparaison", async () => {
    mockFetchSuccess();
    render(<BeforeAfterComparison />);

    await waitFor(() => {
      expect(screen.getAllByText(/2\/5/).length).toBeGreaterThan(0);
    });

    expect(screen.getAllByText(/5\/5/).length).toBeGreaterThan(0);
  });

  it("affiche les problemes identifies dans la version avant", async () => {
    mockFetchSuccess();
    render(<BeforeAfterComparison />);

    await waitFor(() => {
      expect(screen.getByText(/trop g[eé]n[eé]rique/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/pas de signature/i)).toBeInTheDocument();
  });

  it("affiche les ameliorations dans la version apres", async () => {
    mockFetchSuccess();
    const { container } = render(<BeforeAfterComparison />);

    // Wait for the component to finish loading and show the after-panel
    await waitFor(() => {
      // The after panel score (5/5) confirms data has loaded
      expect(screen.getAllByText(/5\/5/).length).toBeGreaterThan(0);
    }, { timeout: 3000 });

    // Verify improvement items are rendered in the after panel
    const afterPanel = container.querySelector('.after-panel');
    expect(afterPanel).toBeTruthy();
    const improvementsDiv = afterPanel?.querySelector('.before-after-panel-improvements');
    expect(improvementsDiv).toBeTruthy();
    expect(improvementsDiv?.textContent).toMatch(/Personnal/i);
    expect(improvementsDiv?.textContent).toMatch(/Signature/i);
  });

  it("affiche le resume des ameliorations globales", async () => {
    mockFetchSuccess();
    render(<BeforeAfterComparison />);

    await waitFor(() => {
      expect(screen.getByText(/200%/)).toBeInTheDocument();
    });

    expect(screen.getByText(/1\.5/)).toBeInTheDocument();
    expect(screen.getByText(/4\.5/)).toBeInTheDocument();
  });

  it("permet de naviguer entre les comparaisons", async () => {
    mockFetchSuccess();
    render(<BeforeAfterComparison />);

    await waitFor(() => {
      const subjectElement = screen.getByText(/E-mail\s*:/i).parentElement;
      expect(subjectElement).toHaveTextContent(/demande de devis/i);
    });

    const nextButton = screen.getByRole("button", { name: /suivant/i });
    fireEvent.click(nextButton);

    await waitFor(() => {
      const subjectElement = screen.getByText(/E-mail\s*:/i).parentElement;
      expect(subjectElement).toHaveTextContent(/Probl[eè]me technique/i);
    });
  });

  it("affiche un message si aucune comparaison disponible", async () => {
    mockFetchEmpty();
    render(<BeforeAfterComparison />);

    await waitFor(() => {
      expect(screen.getByText(/pas encore de comparaison/i)).toBeInTheDocument();
    });
  });

  it("affiche une erreur si le chargement échoue", async () => {
    mockFetchError();
    render(<BeforeAfterComparison />);

    await waitFor(() => {
      expect(screen.getByText(/erreur/i)).toBeInTheDocument();
    });
  });

  it("affiche le texte avant et apres", async () => {
    mockFetchSuccess();
    render(<BeforeAfterComparison />);

    await waitFor(() => {
      expect(screen.getByText(/merci pour votre email/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/merci pour votre demande de devis/i)).toBeInTheDocument();
  });

  it("affiche une indication visuelle du progres", async () => {
    mockFetchSuccess();
    render(<BeforeAfterComparison />);

    await waitFor(() => {
      expect(screen.getByTestId("improvement-arrow")).toBeInTheDocument();
    });
  });
});
