import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { enable, disable, isEnabled } from "@tauri-apps/plugin-autostart";
import './AutostartToggle.css';

// Détecte si on est dans un contexte Tauri (app native) ou navigateur web
const isTauriContext = () => {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
};

interface AutostartToggleProps {
  className?: string;
}

export function AutostartToggle({ className = "" }: AutostartToggleProps) {
  const { t } = useTranslation('common');
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isTauri] = useState(isTauriContext);

  const checkStatus = useCallback(async () => {
    // En mode navigateur, ne pas afficher d'erreur - la fonctionnalité n'est pas disponible
    if (!isTauri) {
      setLoading(false);
      return;
    }
    try {
      const status = await isEnabled();
      setEnabled(status);
      setError(null);
    } catch (err) {
      // En mode Tauri, afficher l'erreur seulement si c'est un vrai problème
      setError(t('autostart_check_error'));
      console.error("Autostart check error:", err);
    } finally {
      setLoading(false);
    }
  }, [isTauri]);

  useEffect(() => {
    checkStatus();
  }, [checkStatus]);

  const handleToggle = async () => {
    setLoading(true);
    setError(null);
    try {
      if (enabled) {
        await disable();
        setEnabled(false);
      } else {
        await enable();
        setEnabled(true);
      }
    } catch (err) {
      console.error("Autostart toggle error:", err);
      try {
        const status = await isEnabled();
        setEnabled(status);
      } catch {
        // Ignore check error, keep original state
      }
      setError(t('autostart_toggle_error'));
    } finally {
      setLoading(false);
    }
  };

  // En mode navigateur, masquer le composant (fonctionnalité non disponible)
  if (!isTauri) {
    return null;
  }

  if (loading) {
    return (
      <div className={`autostart-toggle ${className}`}>
        <span className="autostart-label">{t('autostart_label')}</span>
        <span className="autostart-loading">...</span>
      </div>
    );
  }

  return (
    <div className={`autostart-toggle ${className}`}>
      <label className="autostart-container">
        <span className="autostart-label">{t('autostart_system')}</span>
        <input
          type="checkbox"
          checked={enabled}
          onChange={handleToggle}
          disabled={loading}
          aria-label={t('autostart_aria')}
        />
        <span className="autostart-switch" />
      </label>
      {error && <span className="autostart-error">{error}</span>}
    </div>
  );
}
