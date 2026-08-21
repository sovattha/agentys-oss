import { useState, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { ContactStyleEditor } from './ContactStyleEditor';
import { API_URL } from '../config';
import { getAuthHeaders } from '../services/authToken';
import { useOptimisticMutation, okOrThrow } from '../hooks/useOptimisticMutation';
import { appEvents, ACCOUNT_CHANGED } from '../lib/appEvents';
import { buildFormatPreviewEmail } from '../utils/formatPreview';
import type { ProfileTone, ContactRule, KnowledgeContact } from '../types/onboarding';
import type { ContactStyleProfile, FormalityLevel, LanguageVariant } from '../types/training';
import './TrainingCommon.css';
import './PillarStyle.css';
import './onboarding/LearningInsights.css';

interface PillarStyleReadOnlyProps {
  tone: ProfileTone;
  contactRules: ContactRule[];
  contacts?: KnowledgeContact[];
}

// ── Data mapping helpers ──

type LengthValue = 'concis' | 'moyen' | 'detaille';
type ComplexityValue = 'accessible' | 'standard' | 'elabore';

function mapResponseLength(avgLength?: string): LengthValue {
  if (!avgLength) return 'moyen';
  const v = avgLength.toLowerCase();
  if (v === 'short') return 'concis';
  if (v === 'long' || v === 'medium-long') return 'detaille';
  return 'moyen';
}

function mapToneToComplexity(tone?: string): ComplexityValue {
  if (!tone) return 'standard';
  const v = tone.toLowerCase();
  if (v === 'formal') return 'elabore';
  if (v === 'casual') return 'accessible';
  return 'standard';
}

// Issue #187: mapToneToFormalityValue supprimé — les sliders Formalité/Émotion
// ne sont plus affichés car le ton est inféré automatiquement depuis l'outbox.

function mapToneToFormality(tone?: string): FormalityLevel | null {
  if (!tone) return null;
  const v = tone.toLowerCase();
  if (v === 'formal' || v === 'formel') return 'formal';
  if (v === 'casual' || v === 'décontracté' || v === 'decontracte') return 'casual';
  if (v === 'semi-formal' || v === 'semi-formel' || v === 'professionnel' || v === 'mixed') return 'mixed';
  return null;
}

// ── Read-only SegmentedControl ──

interface SegmentOption { value: string; labelKey: string }

function ReadOnlySegmentedControl({ options, value, t }: { options: SegmentOption[]; value: string; t: (k: string) => string }) {
  return (
    <div className="style-emotion-control style-emotion-control--readonly">
      {options.map(opt => (
        <span key={opt.value} className={`style-emotion-option${value === opt.value ? ' active' : ''}`}>
          {t(opt.labelKey)}
        </span>
      ))}
    </div>
  );
}

// ── Email preview examples ──
// The localized preview body/greeting/closing live in the `agents` i18n
// namespace and are assembled by buildFormatPreviewEmail (shared with
// FormatSection so the two previews never drift).

const LENGTH_OPTIONS: SegmentOption[] = [
  { value: 'concis', labelKey: 'format_length_concis' },
  { value: 'moyen', labelKey: 'format_length_moyen' },
  { value: 'detaille', labelKey: 'format_length_detaille' },
];

const COMPLEXITY_OPTIONS: SegmentOption[] = [
  { value: 'accessible', labelKey: 'format_complexity_accessible' },
  { value: 'standard', labelKey: 'format_complexity_standard' },
  { value: 'elabore', labelKey: 'format_complexity_elabore' },
];

/**
 * Style pillar for onboarding results — mirrors Settings layout:
 * 1. Format de rédaction (read-only segmented controls + preview)
 * 2. Style d'écriture par contact (expandable + editable via ContactStyleEditor)
 */
export function PillarStyleReadOnly({ tone, contactRules, contacts }: PillarStyleReadOnlyProps) {
  const { t } = useTranslation('onboarding');
  const { t: tAgents } = useTranslation('agents');

  const longueur = mapResponseLength(tone.average_response_length);
  const complexite = mapToneToComplexity(tone.default_tone);
  const preview = buildFormatPreviewEmail(tAgents, longueur, complexite, tone.closing_style ?? null);

  // Seed from the onboarding wizard props (first paint, before the backend
  // fetch returns). Backend is the source of truth — `loadContactStyles` will
  // REPLACE this entirely on mount and after each save. See P1 in plan: merging
  // caused stale wizard contacts (from a previous onboarding on a different
  // mailbox) to linger in the Training UI.
  const buildSeedFromProps = useCallback((): ContactStyleProfile[] => {
    const ruleMap = new Map<string, ContactRule>();
    for (const r of contactRules) {
      if (!r?.contact_email) continue;
      ruleMap.set(r.contact_email.toLowerCase(), r);
    }
    const seen = new Set<string>();
    const profiles: ContactStyleProfile[] = [];
    if (contacts) {
      for (const c of contacts) {
        if (!c?.email) continue;
        const key = c.email.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        const rule = ruleMap.get(key);
        profiles.push({
          email: c.email,
          formality_override: mapToneToFormality(rule?.tone || c.preferred_tone),
          preferred_greeting: rule?.greeting || null,
          preferred_closing: rule?.closing || null,
          langue_variante: null,
          langue: c.preferred_language || rule?.language || null,
          nickname: c.name && c.name !== c.email.split('@')[0] ? c.name : null,
        });
      }
    }
    for (const r of contactRules) {
      if (!r?.contact_email) continue;
      const key = r.contact_email.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      profiles.push({
        email: r.contact_email,
        formality_override: mapToneToFormality(r.tone),
        preferred_greeting: r.greeting || null,
        preferred_closing: r.closing || null,
        langue_variante: null,
        langue: r.language || null,
        nickname: null,
      });
    }
    return profiles;
  }, [contacts, contactRules]);

  const [contactStyles, setContactStyles] = useState<ContactStyleProfile[]>(buildSeedFromProps);

  // Fetch persisted WritingStyleProfile contacts. REPLACE local state —
  // never merge. If the backend response includes an account_id that differs
  // from the prop-seeded one (switch de compte), we still replace: the backend
  // knows which account is active.
  const loadContactStyles = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/writing-style/contacts`, { headers: getAuthHeaders() });
      if (!res.ok) return;
      const json = await res.json();
      const saved: Array<{
        email: string;
        formality_override?: string | null;
        preferred_greeting?: string | null;
        preferred_closing?: string | null;
        langue_variante?: string | null;
        langue?: string | null;
        nickname?: string | null;
      }> = json?.contacts ?? [];

      // Backend returned a response (even empty) → it IS the source of truth.
      // Replace, don't merge.
      const nextContacts: ContactStyleProfile[] = saved
        .filter(s => s?.email)
        .map(s => ({
          email: s.email,
          formality_override: (s.formality_override ?? null) as FormalityLevel | null,
          preferred_greeting: s.preferred_greeting ?? null,
          preferred_closing: s.preferred_closing ?? null,
          langue_variante: (s.langue_variante ?? null) as LanguageVariant | null,
          langue: s.langue ?? null,
          nickname: s.nickname ?? null,
        }));

      // Only replace seed data if the backend has real contacts — otherwise
      // onboarding-extracted contacts would be wiped by an empty response
      // (bidirectional filter removes all contacts before any email sync runs).
      // Nicknames are now a field on ContactStyleProfile (saved via setContactStyles),
      // not a separate map — fix branch retired the dedicated nicknames state.
      if (nextContacts.length > 0) {
        setContactStyles(nextContacts);
      }
    } catch {
      /* silent — keep onboarding seed as fallback on network error */
    }
  }, []);

  useEffect(() => {
    loadContactStyles();
  }, [loadContactStyles]);

  // On account switch, clear local state immediately (avoid flashing contacts
  // from the previous account) then refetch for the new one.
  useEffect(() => {
    const onAccountChange = () => {
      setContactStyles([]);
      loadContactStyles();
    };
    appEvents.addEventListener(ACCOUNT_CHANGED, onAccountChange);
    return () => appEvents.removeEventListener(ACCOUNT_CHANGED, onAccountChange);
  }, [loadContactStyles]);

  // Save contact style to backend. Writes nickname/tier/etc., then refetches
  // the persisted list so the UI is guaranteed to match the server.
  const handleSaveContactStyle = useCallback(async (data: {
    contact_email: string;
    formality_override: FormalityLevel | null;
    preferred_greeting: string | null;
    preferred_closing: string | null;
    langue_variante?: LanguageVariant | null;
    langue?: string | null;
    nickname?: string | null;
    // `true` when the user touched the formality chip (manual edit
    // locks the field so post-send auto-derivation won't overwrite it).
    // `false` is the explicit "Back to auto" affordance.
    formality_locked?: boolean;
  }): Promise<{ error?: string }> => {
    try {
      const res = await fetch(`${API_URL}/api/writing-style/contact-style`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(data),
      });
      const json = await res.json().catch(() => ({ error: `Server error (${res.status})` }));
      if (!res.ok) {
        const err = json?.error || `Server error (${res.status})`;
        console.error('[PillarStyleReadOnly] save failed:', err, data);
        if (res.status === 401) return { error: 'Session expired — please reconnect' };
        return { error: err };
      }

      // Optimistic local update so the UI reflects the change immediately,
      // even before the refetch returns. We persist `formality_locked` +
      // `formality_updated_at` (the latter is set server-side; we cheat
      // by using `now()` locally and let the next refetch reconcile).
      setContactStyles(prev => {
        const idx = prev.findIndex(c => c.email.toLowerCase() === data.contact_email.toLowerCase());
        const previous = idx >= 0 ? prev[idx] : null;
        const formalityChanged =
          previous?.formality_override !== data.formality_override;
        const updated: ContactStyleProfile = {
          email: data.contact_email,
          formality_override: data.formality_override,
          preferred_greeting: data.preferred_greeting,
          preferred_closing: data.preferred_closing,
          langue_variante: data.langue_variante || null,
          langue: data.langue || null,
          nickname: data.nickname ?? null,
          formality_locked:
            data.formality_locked ?? previous?.formality_locked ?? false,
          formality_updated_at:
            formalityChanged || data.formality_locked === true
              ? new Date().toISOString()
              : previous?.formality_updated_at ?? null,
        };
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = updated;
          return next;
        }
        return [...prev, updated];
      });

      // Refetch to align with server truth.
      loadContactStyles();
      return {};
    } catch (e) {
      console.error('[PillarStyleReadOnly] network error:', e);
      return { error: 'Network error' };
    }
  }, [loadContactStyles]);

  // Audit Cluster D (2026-05-17) F-10 / #330: previously a fire-and-forget
  // DELETE with no res.ok check, no rollback, no toast — the card would
  // resurrect on the next onboarding reload. Helper surfaces the failure
  // and restores the optimistic UI.
  //
  // Audit regressions (2026-05-17 batch4) F-05: rollback now re-adds ONLY
  // the failed item (id-keyed, idempotent) — see TrainingPage.handleDeleteRule
  // for the rationale. Whole-array `prev` snapshot resurrected successfully-
  // deleted siblings under rapid concurrent clicks.
  const runDeleteContactStyle = useOptimisticMutation<void>({
    scope: 'pillar-style-delete-contact',
    i18nKey: 'toasts.learning_delete_failed',
  });
  const handleDeleteContactStyle = useCallback(async (email: string) => {
    const normalizedEmail = email.toLowerCase();
    const removed = contactStyles.find(c => c.email.toLowerCase() === normalizedEmail);
    setContactStyles(p => p.filter(c => c.email.toLowerCase() !== normalizedEmail));
    await runDeleteContactStyle(
      async () => {
        okOrThrow(await fetch(`${API_URL}/api/writing-style/contact-style`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ contact_email: email }),
        }));
      },
      () => {
        if (!removed) return;
        setContactStyles(p => (p.some(c => c.email.toLowerCase() === normalizedEmail) ? p : [...p, removed]));
      },
    );
  }, [contactStyles, runDeleteContactStyle]);

  return (
    <div className="pillar-style">
      {/* Section 1 : Format de rédaction */}
      <div className="pillar-section-header">
        <span className="pillar-section-title">{t('step3_section_format')}</span>
        <span className="pillar-section-subtitle">{t('step3_section_format_hint')}</span>
      </div>

      <div className="style-settings">
        <div className="pillar-field">
          <label className="pillar-field-label">{tAgents('format_length')}</label>
          <ReadOnlySegmentedControl options={LENGTH_OPTIONS} value={longueur} t={tAgents} />
          <span className="pillar-field-hint">{tAgents('format_length_hint')}</span>
        </div>

        <div className="pillar-field">
          <label className="pillar-field-label">{tAgents('format_complexity')}</label>
          <ReadOnlySegmentedControl options={COMPLEXITY_OPTIONS} value={complexite} t={tAgents} />
          <span className="pillar-field-hint">{tAgents('format_complexity_hint')}</span>
        </div>

        {/* Aperçu email */}
        <div className="format-preview">
          <span className="format-preview-label">{tAgents('format_preview_label')}</span>
          <div className="format-preview-question">
            {tAgents('format_preview_question')}
          </div>
          <div className="format-preview-answer">
            {preview.split('\n').map((line, i) => (
              <span key={i}>{line}<br /></span>
            ))}
          </div>
        </div>
      </div>

      {/* Section 2 : Style d'écriture par défaut */}
      <div className="pillar-style-divider" />
      <div className="pillar-section-header">
        <span className="pillar-section-title">{tAgents('style_section_settings')}</span>
      </div>

      <div className="style-settings">
        {/* Issue #187: Formalité et Niveau d'émotion retirés — le ton est
            inféré automatiquement depuis l'outbox et exposé via
            StyleObservedFromOutbox dans les paramètres éditables. */}

        {/* Addressing (tu/vous) — French corpora only */}
        {tone.addressing && (
          <div className="pillar-field">
            <label className="pillar-field-label">{t('insights_field_addressing')}</label>
            <div className="pillar-field-readonly">{t(`addressing_${tone.addressing}`, tone.addressing)}</div>
          </div>
        )}

        {/* Salutation + Clôture */}
        {(tone.greeting_style || tone.closing_style) && (
          <div className="pillar-field-row">
            {tone.greeting_style && (
              <div className="pillar-field">
                <label className="pillar-field-label">{tAgents('style_greeting_formal')}</label>
                <div className="pillar-field-readonly">{tone.greeting_style}</div>
              </div>
            )}
            {tone.closing_style && (
              <div className="pillar-field">
                <label className="pillar-field-label">{tAgents('style_closing_formal')}</label>
                <div className="pillar-field-readonly">{tone.closing_style}</div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Section 3 : Style par contact (expandable + editable) */}
      <div className="pillar-style-divider" />
      <div className="pillar-section-header">
        <span className="pillar-section-title">{t('step3_section_contact_styles')}</span>
      </div>
      <ContactStyleEditor
        contacts={contactStyles}
        onSave={handleSaveContactStyle}
        onDelete={handleDeleteContactStyle}
      />
    </div>
  );
}
