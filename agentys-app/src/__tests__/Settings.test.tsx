import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Settings } from "../components/Settings";

vi.mock("@tauri-apps/plugin-autostart", () => ({
  enable: vi.fn(),
  disable: vi.fn(),
  isEnabled: vi.fn().mockResolvedValue(false),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockRejectedValue(new Error("Tauri not available")),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
  emit: vi.fn().mockResolvedValue(undefined),
}));

const mockLocalStorage: Record<string, string> = {};
vi.stubGlobal("localStorage", {
  getItem: (key: string) => mockLocalStorage[key] ?? null,
  setItem: (key: string, value: string) => {
    mockLocalStorage[key] = value;
  },
  removeItem: (key: string) => {
    delete mockLocalStorage[key];
  },
  clear: () => {
    Object.keys(mockLocalStorage).forEach((key) => delete mockLocalStorage[key]);
  },
});

// TODO: update for new architecture — Settings UI restructured with new tab categories
describe.skip("Settings (Story 8-1)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.keys(mockLocalStorage).forEach((key) => delete mockLocalStorage[key]);
  });

  describe("Category Navigation (AC2, AC3)", () => {
    it("affiche les 4 catégories de navigation", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Paramètres", level: 2 })).toBeInTheDocument();
      });

      // Check all 4 categories are visible in navigation
      expect(screen.getByRole("tab", { name: /Compte/i })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /Notifications/i })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /Apparence/i })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /Avancé/i })).toBeInTheDocument();
    });

    it("affiche la catégorie Compte par défaut", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByRole("tab", { name: /Compte/i, selected: true })).toBeInTheDocument();
      });

      // Check Compte content is visible
      expect(screen.getByText("Comptes Email")).toBeInTheDocument();
    });

    it("change de catégorie au clic sur un onglet", async () => {
      const user = userEvent.setup();
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByRole("tab", { name: /Notifications/i })).toBeInTheDocument();
      });

      await user.click(screen.getByRole("tab", { name: /Notifications/i }));

      expect(screen.getByRole("tab", { name: /Notifications/i, selected: true })).toBeInTheDocument();
      expect(screen.getByText("Activer les notifications")).toBeInTheDocument();
    });

    it("persiste la catégorie active dans localStorage", async () => {
      const user = userEvent.setup();
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByRole("tab", { name: /Apparence/i })).toBeInTheDocument();
      });

      await user.click(screen.getByRole("tab", { name: /Apparence/i }));

      expect(mockLocalStorage["agentys_settings_category"]).toBe("apparence");
    });
  });

  describe("Search (AC5)", () => {
    it("affiche le champ de recherche", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByPlaceholderText("Rechercher un paramètre...")).toBeInTheDocument();
      });
    });
  });

  describe("Compte category", () => {
    it("affiche le bouton gérer les comptes email", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByText("Gérer mes comptes email")).toBeInTheDocument();
      });
    });

    it("appelle onOpenAccounts quand on clique sur gérer les comptes", async () => {
      const handleClose = vi.fn();
      const handleOpenAccounts = vi.fn();
      const user = userEvent.setup();
      render(<Settings onClose={handleClose} onOpenAccounts={handleOpenAccounts} />);

      await waitFor(() => {
        expect(screen.getByText("Gérer mes comptes email")).toBeInTheDocument();
      });

      await user.click(screen.getByText("Gérer mes comptes email"));

      expect(handleClose).toHaveBeenCalledTimes(1);
      expect(handleOpenAccounts).toHaveBeenCalledTimes(1);
    });
  });

  describe("Notifications category", () => {
    beforeEach(async () => {
      // Navigate to Notifications category
      mockLocalStorage["agentys_settings_category"] = "notifications";
    });

    it("affiche le toggle notifications", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByText("Activer les notifications")).toBeInTheDocument();
      });
    });

    it("active/désactive les notifications", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByText("Activer les notifications")).toBeInTheDocument();
      });

      const toggle = screen.getByRole("checkbox", { name: /activer les notifications/i });
      expect(toggle).toBeChecked();

      fireEvent.click(toggle);

      expect(toggle).not.toBeChecked();
      expect(mockLocalStorage["agentys_notifications_enabled"]).toBe("false");
    });

    it("active/désactive la restriction aux heures de travail", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByText("Uniquement aux heures de travail")).toBeInTheDocument();
      });

      const toggle = screen.getByRole("checkbox", { name: /uniquement aux heures de travail/i });
      expect(toggle).not.toBeChecked();

      fireEvent.click(toggle);

      expect(toggle).toBeChecked();
      expect(mockLocalStorage["agentys_work_hours_only"]).toBe("true");
    });

    it("affiche les heures de travail pour les notifications", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByText("Heures de travail")).toBeInTheDocument();
      });

      // There are multiple "Début" labels now (work hours and quiet hours), use getAllBy
      const startInputs = screen.getAllByLabelText("Début");
      const endInputs = screen.getAllByLabelText("Fin");
      expect(startInputs.length).toBeGreaterThan(0);
      expect(endInputs.length).toBeGreaterThan(0);
    });

    it("permet de configurer les heures de travail", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        // Wait for time inputs to be available
        expect(screen.getAllByLabelText("Début").length).toBeGreaterThan(0);
      });

      // Work hours is the first "Début" input
      const startInputs = screen.getAllByLabelText("Début");
      fireEvent.change(startInputs[0], { target: { value: "08:00" } });

      expect(mockLocalStorage["agentys_work_hours_start"]).toBe("08:00");
    });
  });

  describe("Apparence category", () => {
    beforeEach(async () => {
      // Navigate to Apparence category
      mockLocalStorage["agentys_settings_category"] = "apparence";
    });

    // Skip this test - autostart toggle is only visible in Tauri context
    it.skip("affiche le toggle autostart", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByText("Démarrer avec le système")).toBeInTheDocument();
      });
    });

    it("affiche le toggle infobulles", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByText("Afficher les infobulles")).toBeInTheDocument();
      });
    });

    it("affiche la section raccourcis clavier", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByText("Raccourcis clavier")).toBeInTheDocument();
      });
    });
  });

  describe("Avancé category", () => {
    beforeEach(async () => {
      // Navigate to Avancé category
      mockLocalStorage["agentys_settings_category"] = "avance";
    });

    it("affiche le sélecteur de polling interval", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByText("Intervalle de vérification")).toBeInTheDocument();
      });

      const select = screen.getByRole("combobox", { name: /intervalle/i });
      expect(select).toBeInTheDocument();
    });

    it("permet de changer l'intervalle de polling", async () => {
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByRole("combobox", { name: /intervalle/i })).toBeInTheDocument();
      });

      const select = screen.getByRole("combobox", { name: /intervalle/i });
      fireEvent.change(select, { target: { value: "120" } });

      expect(mockLocalStorage["agentys_polling_interval"]).toBe("120");
    });

    it("charge l'intervalle de polling depuis localStorage", async () => {
      mockLocalStorage["agentys_polling_interval"] = "300";

      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        const select = screen.getByRole("combobox", { name: /intervalle/i }) as HTMLSelectElement;
        expect(select.value).toBe("300");
      });
    });
  });

  describe("Auto-save (AC4)", () => {
    it("sauvegarde automatiquement les changements de notifications", async () => {
      mockLocalStorage["agentys_settings_category"] = "notifications";
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByRole("checkbox", { name: /activer les notifications/i })).toBeInTheDocument();
      });

      const toggle = screen.getByRole("checkbox", { name: /activer les notifications/i });
      fireEvent.click(toggle);

      // Verify auto-save (no explicit save button needed)
      expect(mockLocalStorage["agentys_notifications_enabled"]).toBe("false");
    });

    it("sauvegarde automatiquement les changements d'intervalle", async () => {
      mockLocalStorage["agentys_settings_category"] = "avance";
      render(<Settings onClose={() => {}} />);

      await waitFor(() => {
        expect(screen.getByRole("combobox", { name: /intervalle/i })).toBeInTheDocument();
      });

      const select = screen.getByRole("combobox", { name: /intervalle/i });
      fireEvent.change(select, { target: { value: "600" } });

      // Verify auto-save
      expect(mockLocalStorage["agentys_polling_interval"]).toBe("600");
    });
  });

  describe("Confidentialité / Sentry opt-out", () => {
    const navigateToGeneral = async (user: ReturnType<typeof userEvent.setup>) => {
      render(<Settings onClose={() => {}} />);
      await waitFor(() => {
        expect(screen.getByRole("tab", { name: /Général/i })).toBeInTheDocument();
      });
      await user.click(screen.getByRole("tab", { name: /Général/i }));
      await waitFor(() => {
        expect(screen.getByText("Confidentialité")).toBeInTheDocument();
      });
    };

    it("affiche le toggle rapports d'erreurs dans la section Général", async () => {
      const user = userEvent.setup();
      await navigateToGeneral(user);

      expect(screen.getByText("Rapports d'erreurs")).toBeInTheDocument();
      expect(screen.getByRole("checkbox", { name: /rapports d'erreurs anonymes/i })).toBeInTheDocument();
    });

    it("est activé par défaut (aucune clé dans localStorage)", async () => {
      const user = userEvent.setup();
      await navigateToGeneral(user);

      const toggle = screen.getByRole("checkbox", { name: /rapports d'erreurs anonymes/i });
      expect(toggle).toBeChecked();
    });

    it("est désactivé si sentry_opt_out=true dans localStorage", async () => {
      mockLocalStorage["sentry_opt_out"] = "true";
      const user = userEvent.setup();
      await navigateToGeneral(user);

      const toggle = screen.getByRole("checkbox", { name: /rapports d'erreurs anonymes/i });
      expect(toggle).not.toBeChecked();
    });

    it("désactiver le toggle écrit sentry_opt_out=true dans localStorage", async () => {
      const user = userEvent.setup();
      await navigateToGeneral(user);

      const toggle = screen.getByRole("checkbox", { name: /rapports d'erreurs anonymes/i });
      expect(toggle).toBeChecked();

      fireEvent.click(toggle);

      expect(mockLocalStorage["sentry_opt_out"]).toBe("true");
      expect(toggle).not.toBeChecked();
    });

    it("réactiver le toggle écrit sentry_opt_out=false dans localStorage", async () => {
      mockLocalStorage["sentry_opt_out"] = "true";
      const user = userEvent.setup();
      await navigateToGeneral(user);

      const toggle = screen.getByRole("checkbox", { name: /rapports d'erreurs anonymes/i });
      expect(toggle).not.toBeChecked();

      fireEvent.click(toggle);

      expect(mockLocalStorage["sentry_opt_out"]).toBe("false");
      expect(toggle).toBeChecked();
    });
  });

  describe("Close button", () => {
    it("appelle onClose quand on clique sur le bouton fermer", async () => {
      const handleClose = vi.fn();
      render(<Settings onClose={handleClose} />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /fermer les paramètres/i })).toBeInTheDocument();
      });

      const closeButton = screen.getByRole("button", { name: /fermer les paramètres/i });
      fireEvent.click(closeButton);

      expect(handleClose).toHaveBeenCalledTimes(1);
    });
  });
});
