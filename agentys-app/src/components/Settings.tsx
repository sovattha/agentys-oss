import { useState, useCallback, useEffect, useMemo, useRef, Component, type ReactNode, type ErrorInfo } from "react";
import { createPortal } from "react-dom";

// BUG-Q007 fix: lightweight error boundary so the Automation tab can fail gracefully
// instead of crashing the entire app and triggering a full reload + renderer freeze.
class SectionErrorBoundary extends Component<{ children: ReactNode; label: string }, { error: Error | null }> {
  constructor(props: { children: ReactNode; label: string }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[Settings:${this.props.label}] section crashed`, error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: '24px', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          <p style={{ marginBottom: 8, fontWeight: 600 }}>⚠ This section failed to load.</p>
          <p style={{ marginBottom: 12, opacity: 0.7 }}>{this.state.error.message}</p>
          <button
            style={{ padding: '6px 14px', borderRadius: 6, cursor: 'pointer', border: '1px solid currentColor', background: 'transparent', color: 'inherit' }}
            onClick={() => this.setState({ error: null })}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
import { useTranslation } from "react-i18next";
import { BrainIcon } from "./icons/AgentysIcons";
import { AutostartToggle } from "./AutostartToggle";
import { ReferralPanel } from "./ReferralPanel";
// MonthlySummary import removed — used via lazy load
// LLMSettings import removed: AI Provider section is hidden in the UI;
// re-add this import along with the commented-out section below if the
// multi-provider picker becomes user-facing again.
// import { LLMSettings } from "./LLMSettings";
import { SignatureModal } from "./SignatureModal";
import { CleanInboxModal, type CleanInboxOptions } from "./CleanInboxModal";

import { NewslettersModal } from "./NewslettersModal";
import { ContactAutocomplete } from "./compose/ContactAutocomplete";
import { ContactGroupsManager } from "./settings/ContactGroupsManager";
import { BackgroundTasksModal } from "./settings/BackgroundTasksModal";
import { QuickActionsModal } from "./settings/QuickActionsModal";
import { QuickStepCard } from "./settings/QuickStepsManager";
import { useQuickSteps, patchCachedStep } from "../hooks/useQuickSteps";
import { updateQuickStep } from "../services/api";
import { BookingLinkPanel } from "./BookingLinkPanel";
import { useBookingUrlSetting } from "../hooks/useBookingUrlSetting";
import { SttKeytermsModal } from "./settings/SttKeytermsModal";
import { useToast, ToastContainer } from "./Toast";
import { useTooltipSettings } from "../hooks/useTooltipSettings.js";
import { cleanInbox } from "../api/emails";
import { getBlockedSenders, unblockSender, blockSender } from "../services/api";
import { fetchSettingsCached } from "../hooks/useSettingsCache";
import { invalidateAuthMeCache } from "../services/bootstrapCache";
import { stripeService, type BillingCreditUsage, type BillingEntitlement, type StripeCheckoutInterval, type StripeCheckoutPlan } from "../services/subscription";
import { formatHourMinute, formatShortDateFromDate } from "../utils/dateFormat";

// Feature flag — Monthly Recap button.
// Hidden 2026-05-11 in the Inbox settings while the feature is finalised.
// Set to `true` to expose the entry-point again. The `onOpenRecap` prop and
// its parent handler remain wired so flipping this back is a one-line change.
const ENABLE_MONTHLY_RECAP = false;

// Feature flag — Skills (Specialties) entry on the IA tab.
// Hidden 2026-05-11 while these surfaces are being finalised. Underlying
// component, modal and i18n strings remain wired; flip to `true`
// to expose the entry-point again.
const ENABLE_SKILLS_CARD = false;
import { AutoReplyModal } from "./AutoReplyModal";
import { useHideNoiseSetting } from "../hooks/useHideNoiseSetting";
import { useAutoReminderOnCommitment } from "../hooks/useAutoReminderOnCommitment";
import { useAutoEmptyTrashSetting } from "../hooks/useAutoEmptyTrashSetting";
import { useAutoEmptySpamSetting } from "../hooks/useAutoEmptySpamSetting";
import { useAutoDeleteNoiseSetting } from "../hooks/useAutoDeleteNoiseSetting";
import { useBatchScheduleSetting } from "../hooks/useBatchScheduleSetting";
import { useTheme, type ThemeId } from "../hooks/useTheme";
import { useZoom, ZOOM_LEVELS, DEFAULT_ZOOM } from "../hooks/useZoom";
import { useEmailViewMode, type EmailViewMode } from "../hooks/useEmailViewMode";
import { useUISounds } from "../hooks/useUISounds";
import { useMeetingReminderSettings } from "../hooks/useMeetingReminderSettings";

import { SpecialtiesSection } from "./specialties/SpecialtiesSection";
import { LanguageSelector } from "./LanguageSelector";
import { useComposeFontPrefs, FONT_FAMILY_MAP, FONT_FAMILY_OPTIONS, FONT_SIZE_MAP, type ComposeFontSize } from "../hooks/useComposeFontPrefs";
import { ChevronLeftIcon, ChevronRightIcon, CloseIcon, EditIcon } from "./icons/ActionIcons";
import "./Settings.css";

const ChevronRight = () => (
  <span className="settings-link-chevron">
    <ChevronRightIcon size={16} />
  </span>
);

type SectionId = 'compte' | 'ia' | 'outils' | 'productivite' | 'automatisation' | 'general';
type BillingBusyState = `${StripeCheckoutPlan}-${StripeCheckoutInterval}` | 'portal' | null;
type BillingPlanCredits = {
  dictationDailyMinutes: number;
  dictationActiveDaysPerMonth: number | null;
  dictationMonthlyMinutes: number | null;
  llmMonthlyBudgetUsd: number;
};

const BILLING_PRICE_LINES: Record<StripeCheckoutPlan, { yearly: string; monthly: string; yearlyTotal: string }> = {
  starter: {
    yearly: '$17.00',
    monthly: '$23.99',
    yearlyTotal: '$204.00',
  },
  professional: {
    yearly: '$24.80',
    monthly: '$29.76',
    yearlyTotal: '$297.60',
  },
};

// Mirrors the backend STRIPE_TRIAL_DAYS default — the Stripe checkout opens a
// trial of this length, so the upgrade CTA advertises it ("Start free trial · 7 days").
const BILLING_TRIAL_DAYS = 7;

// Provider glyphs for the trial CTA (Gmail + Outlook) — mirror LoginPage's
// brand marks so the button reads "works with Gmail & Outlook".
const GmailGlyph = () => (
  <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
  </svg>
);
const OutlookGlyph = () => (
  <svg viewBox="0 0 21 21" width="14" height="14" aria-hidden="true">
    <rect x="1" y="1" width="9" height="9" fill="#f25022" />
    <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
    <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
    <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
  </svg>
);

// Lineup « votre plan dans la gamme » : Free est une colonne comme les autres
// pour que le chemin d'upgrade se lise de gauche à droite.
type BillingLineupPlan = 'free' | StripeCheckoutPlan;
const BILLING_LINEUP_ORDER: BillingLineupPlan[] = ['free', 'starter', 'professional'];
const BILLING_LINEUP_RANK: Record<BillingLineupPlan, number> = { free: 0, starter: 1, professional: 2 };
const LLM_CREDITS_PER_USD = 100;
const DICTATION_CREDITS_PER_MINUTE = 10;

const BILLING_PLAN_CREDITS: Record<StripeCheckoutPlan, BillingPlanCredits> = {
  starter: {
    dictationDailyMinutes: 1,
    dictationActiveDaysPerMonth: null,
    dictationMonthlyMinutes: null,
    llmMonthlyBudgetUsd: 3.5,
  },
  professional: {
    dictationDailyMinutes: 20,
    dictationActiveDaysPerMonth: 20,
    dictationMonthlyMinutes: 400,
    llmMonthlyBudgetUsd: 7,
  },
};

function formatCreditNumber(value: number): string {
  return value.toLocaleString('fr-FR', {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

function dictationCreditsFromMinutes(minutes: number): number {
  return Math.round(minutes * DICTATION_CREDITS_PER_MINUTE);
}

function llmCreditsFromBudget(credits: BillingPlanCredits): number {
  return Math.round(credits.llmMonthlyBudgetUsd * LLM_CREDITS_PER_USD);
}

function billingPlanLabel(plan: string | undefined, t: (key: string, options?: Record<string, string>) => string): string {
  if (plan === 'starter') return t('billing_plan_starter', { defaultValue: 'Starter' });
  if (plan === 'professional' || plan === 'pro') return t('billing_plan_professional', { defaultValue: 'Professional' });
  return t('billing_plan_free', { defaultValue: 'Free' });
}

function normalizeBillingPlan(plan: string | undefined): StripeCheckoutPlan | null {
  if (plan === 'starter') return 'starter';
  if (plan === 'professional' || plan === 'pro') return 'professional';
  return null;
}

function creditsForBilling(billing: BillingEntitlement | null): BillingPlanCredits {
  const plan = normalizeBillingPlan(billing?.plan);
  const defaults = plan ? BILLING_PLAN_CREDITS[plan] : {
    dictationDailyMinutes: 0,
    dictationActiveDaysPerMonth: 0,
    dictationMonthlyMinutes: 0,
    llmMonthlyBudgetUsd: 0,
  };
  return {
    dictationDailyMinutes: billing?.limits?.deepgram_minutes_per_day ?? defaults.dictationDailyMinutes,
    dictationActiveDaysPerMonth: billing?.limits?.deepgram_active_days_per_month ?? defaults.dictationActiveDaysPerMonth,
    dictationMonthlyMinutes: billing?.limits?.deepgram_minutes_per_month ?? defaults.dictationMonthlyMinutes,
    llmMonthlyBudgetUsd: billing?.limits?.llm_monthly_budget_usd ?? defaults.llmMonthlyBudgetUsd,
  };
}

function billingLineupTagline(plan: BillingLineupPlan, t: (key: string, options?: Record<string, string>) => string): string {
  // Mêmes descriptions que les cartes de plans du site web.
  if (plan === 'starter') return t('billing_plan_starter_tagline', { defaultValue: 'Pour ceux qui reprennent le contrôle de leur boîte mail.' });
  if (plan === 'professional') return t('billing_plan_professional_tagline', { defaultValue: 'Pour les professionnels qui vivent dans leur boîte mail.' });
  return t('billing_plan_free_tagline', { defaultValue: 'Essayez Agentys gratuitement, aussi longtemps que vous voulez.' });
}

// Sous-titre affiché au-dessus des fonctionnalités (Professional uniquement) :
// « TOUT STARTER, ET EN PLUS », comme sur les cartes de prix du site.
function billingFeaturesHeader(plan: BillingLineupPlan, t: (key: string, options?: Record<string, string>) => string): string | null {
  if (plan === 'professional') return t('billing_feat_everything_starter', { defaultValue: 'TOUT STARTER, ET EN PLUS' });
  return null;
}

// Listes de fonctionnalités calquées sur les cartes de prix du site web
// (descriptifs identiques demandés). Texte marketing volontairement figé,
// découplé des crédits internes (BILLING_PLAN_CREDITS) qui alimentent l'écran
// « Crédits ».
function billingLineupFeatures(plan: BillingLineupPlan, t: (key: string, options?: Record<string, string>) => string): string[] {
  const smartSorting = t('billing_feat_smart_sorting', { defaultValue: 'Tri intelligent de la boîte de réception' });
  const automation = t('billing_feat_automation', { defaultValue: 'Outils d’automatisation personnalisés' });
  const oneInbox = t('billing_feat_one_inbox', { defaultValue: '1 boîte de réception (Gmail ou Outlook)' });
  if (plan === 'free') {
    return [smartSorting, automation, oneInbox];
  }
  if (plan === 'starter') {
    return [
      t('billing_feat_starter_replies', { defaultValue: '500 brouillons de réponse IA / mois' }),
      t('billing_feat_starter_dictation', { defaultValue: 'Dictée au microphone · 1 min/jour' }),
      smartSorting,
      t('billing_feat_learning', { defaultValue: 'Système d’apprentissage IA avancé' }),
      automation,
      oneInbox,
    ];
  }
  // Professional : « tout Starter, et en plus » (le sous-titre est rendu à part).
  return [
    t('billing_feat_pro_replies', { defaultValue: '2 000 brouillons de réponse IA / mois' }),
    t('billing_feat_pro_dictation', { defaultValue: 'Dictée au microphone · 500 min/mois' }),
    t('billing_feat_pro_tokens', { defaultValue: 'Tarif préférentiel sur les tokens' }),
  ];
}

function useSidebarItems(t: (key: string, options?: Record<string, string>) => string): { id: SectionId; label: string; icon: React.ReactNode }[] {
  return [
  {
    id: 'compte',
    label: t('section_account'),
    icon: (
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
        <circle cx="12" cy="7" r="4" />
      </svg>
    ),
  },
  {
    id: 'ia',
    label: t('section_ai'),
    icon: (
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="6" width="20" height="14" rx="2" />
        <path d="M16 6V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2" />
        <path d="M12 12h.01" />
        <path d="M22 13a18.15 18.15 0 0 1-20 0" />
      </svg>
    ),
  },
  {
    id: 'outils',
    label: t('section_tools'),
    icon: (
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
      </svg>
    ),
  },
  {
    id: 'productivite',
    label: t('section_productivity'),
    icon: (
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
      </svg>
    ),
  },
  {
    id: 'automatisation',
    label: t('section_automation'),
    icon: (
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="17 1 21 5 17 9" />
        <path d="M3 11V9a4 4 0 0 1 4-4h14" />
        <polyline points="7 23 3 19 7 15" />
        <path d="M21 13v2a4 4 0 0 1-4 4H3" />
      </svg>
    ),
  },
  {
    id: 'general',
    label: t('section_general'),
    icon: (
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <line x1="4" y1="6" x2="20" y2="6" />
        <line x1="4" y1="12" x2="20" y2="12" />
        <line x1="4" y1="18" x2="20" y2="18" />
        <line x1="8" y1="6" x2="8" y2="6" strokeWidth="3" strokeLinecap="round" />
        <line x1="16" y1="12" x2="16" y2="12" strokeWidth="3" strokeLinecap="round" />
        <line x1="10" y1="18" x2="10" y2="18" strokeWidth="3" strokeLinecap="round" />
      </svg>
    ),
  },
  ];
}

interface SettingsProps {
  onClose: () => void;
  onOpenAccounts?: () => void;
  onOpenLabelLibrary?: () => void;
  onOpenSnippets?: () => void;
  onOpenRecap?: () => void;
  onOpenTraining?: () => void;
  onOpenShortcuts?: () => void;
  onOpenDeepWork?: () => void;
  onOpenMeetingReminders?: () => void;
  onOpenLearning?: () => void;
  onStartGuidedTour?: () => void;
  onLogout?: () => void;
  accountId?: number;
  /** Deep Work is configured (≥1 sub-mode on) or a focus session is live.
   *  Sourced from App's canonical timer so it tracks panel toggles instantly. */
  deepWorkActive?: boolean;
  /** Deep-link from the inbox padlock (free plan): open the plan-chooser
   *  window immediately on mount instead of landing on the Account section. */
  openBilling?: boolean;
}

export function Settings({ onClose, onOpenAccounts, onOpenLabelLibrary, onOpenSnippets, onOpenRecap, onOpenTraining, onOpenShortcuts, onOpenDeepWork, onOpenMeetingReminders, onStartGuidedTour: _onStartGuidedTour, onLogout, accountId, deepWorkActive, openBilling }: SettingsProps) {
  const { t, i18n } = useTranslation('settings');
  const { t: tc } = useTranslation('common');
  const sidebarItems = useSidebarItems(t);
  const [showCleanInboxModal, setShowCleanInboxModal] = useState(false);
  const [showSignatureModal, setShowSignatureModal] = useState(false);

  const [showNewslettersModal, setShowNewslettersModal] = useState(false);
  const [showContactGroups, setShowContactGroups] = useState(false);
  const [showAutoReplyModal, setShowAutoReplyModal] = useState(false);
  const [showBlockedSenders, setShowBlockedSenders] = useState(false);
  // Abonnement & Crédits : lignes du panneau Compte ouvrant chacune leur
  // fenêtre (même pattern que Blocked senders) — remplace l'ancien panneau
  // billing inline et l'ancienne section sidebar "Crédits".
  const [showBillingModal, setShowBillingModal] = useState(false);
  const [showCreditsModal, setShowCreditsModal] = useState(false);
  const [showSttKeyterms, setShowSttKeyterms] = useState(false);
  const [showQuickActions, setShowQuickActions] = useState(false);
  const [showBookingLink, setShowBookingLink] = useState(false);
  const [showBgTasks, setShowBgTasks] = useState(false);
  const [activeSection, setActiveSection] = useState<SectionId>('compte');
  const [billing, setBilling] = useState<BillingEntitlement | null>(null);
  // Valeur de chargement plus affichée depuis le retrait du bandeau/refresh
  // (2026-06-11) — on garde le setter pour les flux existants.
  const [, setBillingLoading] = useState(false);
  const [billingBusy, setBillingBusy] = useState<BillingBusyState>(null);
  const [billingError, setBillingError] = useState<string | null>(null);
  // Annuel par défaut : c'est l'option mise en avant (« -29% ») dans le lineup.
  const [billingInterval, setBillingInterval] = useState<StripeCheckoutInterval>('yearly');
  const [creditUsage, setCreditUsage] = useState<BillingCreditUsage | null>(null);
  const [creditUsageLoading, setCreditUsageLoading] = useState(false);
  const [creditUsageError, setCreditUsageError] = useState<string | null>(null);
  const handledBillingReturnRef = useRef(false);

  // Quick Actions discovery surface — show the recommended starter rules inline in
  // Settings → Automation so they're discoverable next to the legacy toggles.
  // Identification by exact name match is intentionally fragile: when we add
  // a stable ``template_key`` to the QuickStep schema, swap this for that.
  const { steps: allQuickSteps } = useQuickSteps();
  const discoverableQuickSteps = useMemo(() => {
    const targetNames = ['Follow-up new thread', 'Follow-up existing thread', 'Accept meeting invitation', 'Archive after reply'];
    const out = [];
    for (const name of targetNames) {
      const found = allQuickSteps.find(s => (s.name ?? '').trim().toLowerCase() === name.toLowerCase());
      if (found) out.push(found);
    }
    return out;
  }, [allQuickSteps]);

  const { toasts, addToast, dismissToast } = useToast();

  const refreshBilling = useCallback(async (fresh = false, sessionId?: string | null) => {
    if (fresh) {
      invalidateAuthMeCache();
    }
    setBillingLoading(true);
    setBillingError(null);
    try {
      const nextBilling = await stripeService.getBilling({ fresh, sessionId });
      setBilling(nextBilling);
      window.dispatchEvent(new CustomEvent('agentys:billing-updated', { detail: nextBilling }));
    } catch (err) {
      console.error('[Settings] failed to load billing status', err);
      setBillingError(t('billing_load_error', { defaultValue: 'Impossible de charger votre abonnement.' }));
    } finally {
      setBillingLoading(false);
    }
  }, [t]);

  const refreshCreditUsage = useCallback(async () => {
    setCreditUsageLoading(true);
    setCreditUsageError(null);
    try {
      const usage = await stripeService.getCreditUsage();
      setCreditUsage(usage);
    } catch (err) {
      console.error('[Settings] failed to load credit usage', err);
      setCreditUsageError(t('credits_usage_load_error', { defaultValue: 'Impossible de charger l’utilisation des crédits.' }));
    } finally {
      setCreditUsageLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (activeSection === 'compte' || showBillingModal || showCreditsModal) {
      void refreshBilling();
    }
  }, [activeSection, showBillingModal, showCreditsModal, refreshBilling]);

  useEffect(() => {
    if (!showCreditsModal) return;
    if (billing?.ai_enabled !== true) {
      setCreditUsage(null);
      setCreditUsageError(null);
      return;
    }
    void refreshCreditUsage();
  }, [showCreditsModal, billing?.ai_enabled, refreshCreditUsage]);

  // Escape ferme la fenêtre Abonnement/Crédits (même garde input que
  // BlockedSendersModal) sans toucher au reste de Settings.
  useEffect(() => {
    if (!showBillingModal && !showCreditsModal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const tgt = e.target as HTMLElement | null;
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable)) {
        return;
      }
      setShowBillingModal(false);
      setShowCreditsModal(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [showBillingModal, showCreditsModal]);

  useEffect(() => {
    if (handledBillingReturnRef.current) return;
    const params = new URLSearchParams(window.location.search);
    const isBillingReturn = window.location.pathname === '/settings/billing' || params.has('billing');
    if (!isBillingReturn) return;

    handledBillingReturnRef.current = true;
    setActiveSection('compte');
    // Le panneau Abonnement vit désormais dans sa propre fenêtre : l'ouvrir
    // au retour de Stripe pour que l'utilisateur voie le statut se vérifier.
    setShowBillingModal(true);
    stripeService.clearCheckoutPending();

    const status = params.get('billing');
    const sessionId = params.get('session_id');
    if (status === 'cancelled') {
      void refreshBilling(true);
      addToast(t('billing_checkout_cancelled', { defaultValue: 'Paiement annulé.' }), 'info');
    } else {
      void refreshBilling(true, sessionId);
      addToast(t('billing_checkout_returned', { defaultValue: 'Retour de Stripe reçu. Vérification de l’abonnement…' }), 'info');
    }
    window.history.replaceState({}, document.title, '/');
  }, [addToast, refreshBilling, t]);

  // Deep-link from the inbox padlock (free plan): jump straight to the
  // plan-chooser window. Settings remounts on each open, so reading the prop
  // once on mount is enough; App resets the flag when Settings closes.
  useEffect(() => {
    if (!openBilling) return;
    setActiveSection('compte');
    setShowBillingModal(true);
  }, [openBilling]);

  const handleStartCheckout = useCallback(async (plan: StripeCheckoutPlan, interval: StripeCheckoutInterval) => {
    const busyKey: BillingBusyState = `${plan}-${interval}`;
    setBillingBusy(busyKey);
    setBillingError(null);
    try {
      const checkout = await stripeService.createCheckoutSession('', { plan, interval });
      window.location.assign(checkout.checkoutUrl);
    } catch (err) {
      console.error('[Settings] failed to create Stripe checkout session', err);
      const message = t('billing_checkout_error', { defaultValue: 'Impossible d’ouvrir le paiement Stripe.' });
      setBillingError(message);
      addToast(message, 'error');
    } finally {
      setBillingBusy(null);
    }
  }, [addToast, t]);

  const handleOpenBillingPortal = useCallback(async () => {
    setBillingBusy('portal');
    setBillingError(null);
    try {
      await stripeService.openCustomerPortal();
    } catch (err) {
      console.error('[Settings] failed to open Stripe customer portal', err);
      const message = t('billing_portal_error', { defaultValue: 'Impossible d’ouvrir le portail Stripe.' });
      setBillingError(message);
      addToast(message, 'error');
    } finally {
      setBillingBusy(null);
    }
  }, [addToast, t]);

  // Inline enable/disable toggle on the embedded card. Optimistically patches
  // the shared cache so the switch flips instantly, then PATCHes the backend
  // and rolls back on failure.
  const handleToggleEmbeddedQuickStep = useCallback(async (stepId: string, prevEnabled: boolean, next: boolean) => {
    patchCachedStep(stepId, { enabled: next });
    try {
      await updateQuickStep(stepId, { enabled: next });
      window.dispatchEvent(new CustomEvent('agentys:quicksteps-changed'));
    } catch (e) {
      patchCachedStep(stepId, { enabled: prevEnabled });
      console.error('[Settings] failed to toggle embedded Quick Step', e);
      addToast(t('error_save', { defaultValue: 'Enregistrement échoué' }), 'error');
    }
  }, [addToast, t]);
  const [blockedSendersSourceSection, setBlockedSendersSourceSection] = useState<SectionId>('compte');

  useTooltipSettings();
  const [autoReplyActive, setAutoReplyActive] = useState(false);
  // Refresh auto-reply status when section opens or modal closes
  useEffect(() => {
    if (activeSection === 'compte' || !showAutoReplyModal) {
      fetchSettingsCached(accountId).then((s) => {
        setAutoReplyActive(!!s.auto_reply_enabled);
      }).catch(() => {});
    }
  }, [accountId, activeSection, showAutoReplyModal]);
  const { hideNoise, toggleHideNoise } = useHideNoiseSetting(accountId);
  const { autoReminderOnCommitment, toggleAutoReminderOnCommitment } = useAutoReminderOnCommitment(accountId);
  const { bookingUrl } = useBookingUrlSetting(accountId);
  const { autoEmptyTrash, toggleAutoEmptyTrash } = useAutoEmptyTrashSetting(accountId);
  const { autoEmptySpam, toggleAutoEmptySpam } = useAutoEmptySpamSetting(accountId);
  const { autoDeleteNoise, toggleAutoDeleteNoise } = useAutoDeleteNoiseSetting(accountId);
  const { theme, setTheme } = useTheme();
  const { viewMode: emailViewMode, setViewMode: setEmailViewMode } = useEmailViewMode();
  const { fontFamily, fontSize, setFontFamily, setFontSize } = useComposeFontPrefs();
  const { zoom, setZoom, resetZoom } = useZoom();
  useUISounds();
  // Deep Work badge state comes from the `deepWorkActive` prop (App's canonical
  // timer), not a local useDeepWorkSetting — a second instance here went stale
  // after panel toggles and showed a phantom "Activé".
  // Le state est lu pour afficher le badge "Activé" sur le link button
  // Productivité → Rappels de réunions ; les setters vivent dans la modale.
  const { settings: meetingReminderSettings } = useMeetingReminderSettings();

  // Heures creuses — hook conservé pour la logique backend, UI masquée
  useBatchScheduleSetting(accountId);

  // Booking URL — chargée depuis les settings au montage. Uses the static
  // import (already at the top of the file) — no need for a dynamic import.
  useEffect(() => {
    fetchSettingsCached().catch(() => {});
  }, []);

  // Silent-failure fix (issue #316) : notifier selon le succès RÉEL du PATCH
  // plutôt que d'afficher 'saved' systématiquement. `toggle()` renvoie
  // maintenant Promise<boolean> — true = succès, false = rollback déjà appliqué.
  const notifySaveResult = useCallback((ok: boolean) => {
    if (ok) {
      addToast(t('saved'), 'success');
    } else {
      addToast(t('error_save', { defaultValue: 'Enregistrement échoué' }), 'error');
    }
  }, [t, addToast]);

  const handleToggleAutoEmptyTrash = useCallback(async () => {
    const ok = await toggleAutoEmptyTrash();
    notifySaveResult(ok);
  }, [toggleAutoEmptyTrash, notifySaveResult]);

  const handleToggleAutoEmptySpam = useCallback(async () => {
    const ok = await toggleAutoEmptySpam();
    notifySaveResult(ok);
  }, [toggleAutoEmptySpam, notifySaveResult]);

  const handleToggleAutoDeleteNoise = useCallback(async () => {
    const ok = await toggleAutoDeleteNoise();
    notifySaveResult(ok);
  }, [toggleAutoDeleteNoise, notifySaveResult]);

  // Audit U-01 / REGRESSION #324 (2026-05-12): the four toggles below were
  // wired directly to their hook's `toggle` function, which already rolls
  // back on PATCH failure but never told the user. Wrap them through
  // notifySaveResult so a failed save is visible — same pattern as the
  // three handlers above.
  const handleToggleHideNoise = useCallback(async () => {
    const ok = await toggleHideNoise();
    notifySaveResult(ok);
  }, [toggleHideNoise, notifySaveResult]);

  const handleToggleAutoReminderOnCommitment = useCallback(async () => {
    const ok = await toggleAutoReminderOnCommitment();
    notifySaveResult(ok);
  }, [toggleAutoReminderOnCommitment, notifySaveResult]);

  const handleOpenAccounts = useCallback(() => {
    onClose();
    onOpenAccounts?.();
  }, [onClose, onOpenAccounts]);


  const handleOpenCleanInbox = useCallback(() => {
    setShowCleanInboxModal(true);
  }, []);

  const handleCloseCleanInbox = useCallback(() => {
    setShowCleanInboxModal(false);
  }, []);

  const handleCleanInbox = useCallback(async (options: CleanInboxOptions) => {
    const res = await cleanInbox(options);
    if (res.mode === 'async') {
      addToast(
        t('clean_queued', {
          count: res.target_total,
          defaultValue: 'Archiving {{count}} emails in background — see Background tasks',
        }),
        'success',
      );
    } else {
      addToast(
        t('clean_done', {
          count: res.archived_count,
          defaultValue: 'Archived {{count}} emails',
        }),
        'success',
      );
    }
  }, [addToast, t]);

  const handleOpenSignature = useCallback(() => {
    setShowSignatureModal(true);
  }, []);

  const handleCloseSignature = useCallback(() => {
    setShowSignatureModal(false);
  }, []);

  const handleOpenLabelLibrary = useCallback(() => {
    onClose();
    onOpenLabelLibrary?.();
  }, [onClose, onOpenLabelLibrary]);

  const handleOpenSnippets = useCallback(() => {
    onClose();
    onOpenSnippets?.();
  }, [onClose, onOpenSnippets]);

  const handleOpenNewsletters = useCallback(() => {
    setShowNewslettersModal(true);
  }, []);

  const handleCloseNewsletters = useCallback(() => {
    setShowNewslettersModal(false);
  }, []);

  const activeIndex = sidebarItems.findIndex((item) => item.id === activeSection);
  const billingIsActive = billing?.ai_enabled === true;
  const billingCurrentPlanLabel = billingPlanLabel(billing?.plan, t);
  const billingLineupCurrent: BillingLineupPlan = (billingIsActive ? normalizeBillingPlan(billing?.plan) : null) ?? 'free';
  const currentCredits = creditsForBilling(billing);
  const llmCreditUsage = creditUsage?.llm ?? null;
  const dictationCreditUsage = creditUsage?.dictation ?? null;
  const llmCreditUsagePercent = llmCreditUsage && llmCreditUsage.included_credits > 0
    ? Math.min(100, Math.round((llmCreditUsage.used_credits / llmCreditUsage.included_credits) * 100))
    : 0;
  const dictationCreditUsagePercent = dictationCreditUsage && dictationCreditUsage.included_credits > 0
    ? Math.min(100, Math.round((dictationCreditUsage.used_credits / dictationCreditUsage.included_credits) * 100))
    : 0;
  // Quand ça reset : date + heure explicites sur chaque ligne. Sans resets_at
  // (gratuit / chargement) : minuit prochain pour la dictée journalière,
  // 1er du mois suivant pour les périodes mensuelles.
  const creditResetStamp = (value: string | Date | null | undefined): { date: string; time: string } | null => {
    if (!value) return null;
    const d = typeof value === 'string' ? new Date(value) : value;
    if (Number.isNaN(d.getTime())) return null;
    return { date: formatShortDateFromDate(d, i18n.language), time: formatHourMinute(d, i18n.language) };
  };
  const creditResetNow = new Date();
  const nextMidnight = new Date(creditResetNow);
  nextMidnight.setHours(24, 0, 0, 0);
  const firstOfNextMonth = new Date(creditResetNow.getFullYear(), creditResetNow.getMonth() + 1, 1, 0, 0, 0, 0);
  const dictationResetStamp = creditResetStamp(dictationCreditUsage?.resets_at)
    ?? creditResetStamp(dictationCreditUsage?.window === 'month' ? firstOfNextMonth : nextMidnight);
  const llmResetStamp = creditResetStamp(llmCreditUsage?.resets_at) ?? creditResetStamp(firstOfNextMonth);
  // Quiet rows : valeurs numériques brutes (gros chiffre restant + « sur N »).
  // Sans données d'usage (gratuit ou chargement), retombe sur les crédits du plan.
  const dictationIncludedCredits = dictationCreditUsage?.included_credits ?? dictationCreditsFromMinutes(currentCredits.dictationDailyMinutes);
  const dictationRemainingCredits = dictationCreditUsage?.remaining_credits ?? dictationIncludedCredits;
  const llmIncludedCredits = llmCreditUsage?.included_credits ?? llmCreditsFromBudget(currentCredits);
  const llmRemainingCredits = llmCreditUsage?.remaining_credits ?? llmIncludedCredits;
  // billingStatusLabel / billingPeriodEndLabel supprimés (2026-06-11) : la
  // chip Settings affiche le PLAN (billingCurrentPlanLabel) et le bandeau
  // « Plan actuel / statut » du modal Billing a été retiré.
  // Titres courts : la période (jour/mois) est déjà portée par le sous-titre de reset.
  const dictationRowTitle = t('credits_row_dictation', { defaultValue: 'Dictée' });
  const aiCreditsRowTitle = t('credits_row_ai', { defaultValue: 'Crédits IA' });
  const dictationRowSub = creditUsageLoading && billingIsActive && !dictationCreditUsage
    ? t('credits_usage_loading', { defaultValue: 'Chargement de l’utilisation…' })
    : dictationResetStamp
      ? t('credits_row_resets_at', { date: dictationResetStamp.date, time: dictationResetStamp.time, defaultValue: 'Réinitialisation le {{date}} à {{time}}' })
      : '';
  const llmRowSub = creditUsageLoading && billingIsActive && !llmCreditUsage
    ? t('credits_usage_loading', { defaultValue: 'Chargement de l’utilisation…' })
    : llmResetStamp
      ? t('credits_row_resets_at', { date: llmResetStamp.date, time: llmResetStamp.time, defaultValue: 'Réinitialisation le {{date}} à {{time}}' })
      : '';

  return (
    <div className="settings">
      <div className="settings-header">
        <h2>{t('title')}</h2>
        <button
          className="settings-close"
          onClick={onClose}
          aria-label={t('close')}
          data-testid="settings-close"
        >
          <CloseIcon />
        </button>
      </div>

      <div className="settings-body">
        {/* ── Sidebar verticale ── */}
        <div
          className="settings-sidebar"
          role="tablist"
          aria-label={t('sections_aria')}
          style={{ '--active-index': activeIndex } as React.CSSProperties}
        >
          {sidebarItems.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={activeSection === item.id}
              aria-controls="settings-content"
              className={`settings-sidebar-item${activeSection === item.id ? ' active' : ''}`}
              onClick={() => setActiveSection(item.id)}
            >
              <span className="settings-sidebar-icon">{item.icon}</span>
              <span className="settings-sidebar-label">{item.label}</span>
            </button>
          ))}
          {onLogout && (
            <button
              type="button"
              className="settings-logout-btn"
              onClick={onLogout}
            >
              <span className="settings-logout-icon" aria-hidden="true">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                  <polyline points="16 17 21 12 16 7" />
                  <line x1="21" y1="12" x2="9" y2="12" />
                </svg>
              </span>
              <span className="settings-logout-label">{t('logout')}</span>
            </button>
          )}
        </div>

        {/* ── Panneau de contenu scrollable ── */}
        <div
          className="settings-content-panel"
          id="settings-content"
          role="tabpanel"
          tabIndex={0}
          aria-label={activeSection}
        >
          <div key={activeSection} className="settings-content-inner">

          {/* ── COMPTE ── */}
          {activeSection === 'compte' && (
            <>
              <section className="settings-section">

                <div className="settings-link-group">
                  <button className="settings-link-btn" onClick={handleOpenAccounts} type="button">
                    <span className="settings-link-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                    </span>
                    <span>{t('account_user')}</span>
                    <ChevronRight />
                  </button>
                  <button className="settings-link-btn" onClick={() => setShowBillingModal(true)} type="button">
                    <span className="settings-link-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>
                    </span>
                    <span>{t('billing_title', { defaultValue: 'Facturation' })}</span>
                    {/* Chip = le PLAN (Starter/Professional), pas le statut :
                        un abonnement Stripe démarre en `trialing` et la chip
                        affichait « Essai gratuit » alors que l'utilisateur
                        venait de prendre Starter (rapport 2026-06-11). */}
                    {billingIsActive && <span className="settings-link-badge">{billingCurrentPlanLabel}</span>}
                    <ChevronRight />
                  </button>
                  <button className="settings-link-btn" onClick={() => setShowCreditsModal(true)} type="button">
                    <span className="settings-link-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><line x1="4" y1="20" x2="20" y2="20"/><line x1="7" y1="16" x2="7" y2="20"/><line x1="12" y1="8" x2="12" y2="20"/><line x1="17" y1="12" x2="17" y2="20"/></svg>
                    </span>
                    <span>{t('credits_title', { defaultValue: 'Utilisation' })}</span>
                    <ChevronRight />
                  </button>
                  <button className="settings-link-btn" onClick={handleOpenSignature} type="button">
                    <span className="settings-link-icon">
                      <EditIcon size={16} />
                    </span>
                    <span>{t('account_signature')}</span>
                    <ChevronRight />
                  </button>
                  <button className="settings-link-btn" onClick={() => setShowAutoReplyModal(true)} type="button">
                    <span className="settings-link-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>
                    </span>
                    <span>{t('account_auto_reply')}</span>
                    {autoReplyActive && <span className="settings-link-badge">{t('common:active', 'Activé')}</span>}
                    <ChevronRight />
                  </button>
                  <button className="settings-link-btn" onClick={() => { setBlockedSendersSourceSection(activeSection); setShowBlockedSenders(true); }} type="button">
                    <span className="settings-link-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/></svg>
                    </span>
                    <span>{t('blocked_senders')}</span>
                    <ChevronRight />
                  </button>
                  {/* Monthly Recap — gated on ENABLE_MONTHLY_RECAP. See top of file. */}
                  {ENABLE_MONTHLY_RECAP && (
                    <button className="settings-link-btn" onClick={onOpenRecap} type="button">
                      <span className="settings-link-icon">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                      </span>
                      <span>{t('monthly_recap')}</span>
                      <ChevronRight />
                    </button>
                  )}
                </div>
              </section>

            </>
          )}

          {/* ── ABONNEMENT : ligne du panneau Compte → fenêtre dédiée ── */}
          {showBillingModal && createPortal(
            /* data-escape-owner : le host (useAppShortcuts) diffère son Escape
               tant que cette fenêtre est ouverte — contrat utils/escapeOwner.ts */
            <div className="settings-modal-overlay" data-escape-owner="" onClick={() => setShowBillingModal(false)}>
              <div className="settings-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 720, width: '92%' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid var(--border-color, #e5e7eb)', flexShrink: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <button onClick={() => setShowBillingModal(false)} type="button" aria-label={t('common:back', 'Back')} title={t('common:back', 'Back')} style={{ width: 32, height: 32, border: 'none', padding: 0, background: 'none', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', cursor: 'pointer', flexShrink: 0, transition: 'all 0.15s' }}>
                      <ChevronLeftIcon size={20} />
                    </button>
                    <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>{t('billing_title', { defaultValue: 'Facturation' })}</h3>
                  </div>
                  <button onClick={() => setShowBillingModal(false)} type="button" aria-label={t('label_close')} style={{ width: 28, height: 28, border: 'none', padding: 0, background: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 6 }}>
                    <CloseIcon />
                  </button>
                </div>
                <div style={{ overflowY: 'auto', padding: '16px 20px 20px' }}>
                  <div className="settings-billing-panel">
                    {/* Bandeau « Plan actuel : X / statut » retiré (demande
                        2026-06-11) — la carte du plan porte déjà « Plan
                        actuel » via son CTA. */}
                    {billingError && (
                      <div className="settings-billing-error" role="alert">{billingError}</div>
                    )}

                    <div className="settings-billing-toggle-row">
                      <div className="settings-billing-toggle" role="group" aria-label={t('billing_interval_aria', { defaultValue: 'Période de facturation' })}>
                        <button
                          type="button"
                          className={billingInterval === 'monthly' ? 'on' : ''}
                          aria-pressed={billingInterval === 'monthly'}
                          onClick={() => setBillingInterval('monthly')}
                        >
                          {t('billing_interval_monthly', { defaultValue: 'Mensuel' })}
                        </button>
                        <button
                          type="button"
                          className={billingInterval === 'yearly' ? 'on' : ''}
                          aria-pressed={billingInterval === 'yearly'}
                          onClick={() => setBillingInterval('yearly')}
                        >
                          {t('billing_interval_annual', { defaultValue: 'Annuel' })}
                        </button>
                      </div>
                      <span className={`settings-billing-save-badge${billingInterval === 'monthly' ? ' settings-billing-save-badge--off' : ''}`}>
                        {t('billing_save_badge', { defaultValue: 'Économisez jusqu’à 29%' })}
                      </span>
                    </div>

                    <div className="settings-billing-lineup">
                      {BILLING_LINEUP_ORDER.map((plan) => {
                        const isCurrent = plan === billingLineupCurrent;
                        const isUpgrade = BILLING_LINEUP_RANK[plan] > BILLING_LINEUP_RANK[billingLineupCurrent];
                        // A free (non-subscribed) user picking a paid plan starts a
                        // Stripe checkout that opens a 7-day trial — surface that as a
                        // "Start free trial · 7 days" CTA with the provider marks
                        // (active subscribers go through the portal, so keep their label).
                        const isTrialStart = !isCurrent && !billingIsActive && plan !== 'free';
                        const highlighted = plan === 'professional';
                        const prices = plan === 'free' ? null : BILLING_PRICE_LINES[plan];
                        const ctaBusy = plan !== 'free' && billingBusy === `${plan}-${billingInterval}`;
                        const ctaLabel = ctaBusy
                          ? t('billing_opening_portal', { defaultValue: 'Ouverture…' })
                          : isCurrent
                            ? t('billing_cta_current', { defaultValue: 'Plan actuel' })
                            : isUpgrade
                              ? t('billing_cta_upgrade', { defaultValue: 'Mettre à niveau' })
                              : t('billing_cta_downgrade', { defaultValue: 'Rétrograder' });
                        return (
                          <article key={plan} className={`settings-billing-card${plan === 'free' ? ' free' : ''}${highlighted ? ' highlighted' : ''}`}>
                            {highlighted && (
                              <span className="settings-billing-card-badge">
                                {t('billing_tag_best_value', { defaultValue: 'MEILLEURE OFFRE' })}
                              </span>
                            )}
                            <div className="settings-billing-card-title">
                              <span className="settings-billing-card-name">{billingPlanLabel(plan === 'free' ? undefined : plan, t)}</span>
                              {isCurrent && (
                                <span className="settings-billing-card-tag">
                                  {t('billing_tag_your_plan', { defaultValue: 'VOTRE PLAN' })}
                                </span>
                              )}
                            </div>
                            <p className="settings-billing-card-tagline">{billingLineupTagline(plan, t)}</p>
                            <div className="settings-billing-card-price">
                              {prices === null ? (
                                <>
                                  <span className="settings-billing-card-amount">$0</span>
                                  <span className="settings-billing-card-period">{t('billing_monthly', { defaultValue: '/mois' })}</span>
                                </>
                              ) : (
                                <>
                                  {billingInterval === 'yearly' && highlighted && (
                                    <s className="settings-billing-card-strike">{prices.monthly}</s>
                                  )}
                                  <span className="settings-billing-card-amount">{billingInterval === 'yearly' ? prices.yearly : prices.monthly}</span>
                                  <span className="settings-billing-card-period">{t('billing_monthly', { defaultValue: '/mois' })}</span>
                                </>
                              )}
                            </div>
                            {/* Free : « sans carte ». Payant mensuel : nbsp pour garder l'alignement des 3 colonnes. */}
                            <p className="settings-billing-card-billed">
                              {prices === null
                                ? t('billing_free_no_card', { defaultValue: 'Gratuit pour toujours — sans carte bancaire' })
                                : billingInterval === 'yearly'
                                ? t('billing_billed_annually', { total: prices.yearlyTotal, defaultValue: 'Facturé annuellement ({{total}}/an)' })
                                : ' '}
                            </p>
                            {billingFeaturesHeader(plan, t) && (
                              <p className="settings-billing-card-features-header">{billingFeaturesHeader(plan, t)}</p>
                            )}
                            <ul className="settings-billing-card-features">
                              {billingLineupFeatures(plan, t).map((line) => (
                                <li key={line}>{line}</li>
                              ))}
                            </ul>
                            <button
                              type="button"
                              className={`settings-billing-cta${isTrialStart ? ' trial' : isCurrent ? ' current' : isUpgrade ? ' primary' : ' outline'}`}
                              onClick={() => {
                                if (isCurrent) return;
                                // Abonné actif : tout changement de plan passe par le portail Stripe.
                                if (billingIsActive) { void handleOpenBillingPortal(); return; }
                                if (plan !== 'free') void handleStartCheckout(plan, billingInterval);
                              }}
                              disabled={isCurrent || billingBusy !== null}
                            >
                              {isTrialStart && !ctaBusy ? (
                                <>
                                  <span className="settings-billing-cta-label">
                                    {t('billing_cta_trial', { days: BILLING_TRIAL_DAYS, defaultValue: 'Start free trial · {{days}} days' })}
                                  </span>
                                  <span className="settings-billing-cta-providers" aria-hidden="true">
                                    <GmailGlyph />
                                    <OutlookGlyph />
                                  </span>
                                </>
                              ) : (
                                ctaLabel
                              )}
                            </button>
                          </article>
                        );
                      })}
                    </div>

                    {/* « Voir les crédits » + « Actualiser » retirés (demande
                        2026-06-11) — l'utilisation a sa propre entrée Settings
                        et le billing se rafraîchit seul au retour de Stripe. */}
                    {billingIsActive && (
                      <div className="settings-billing-actions">
                        <button
                          type="button"
                          className="settings-billing-primary"
                          onClick={() => void handleOpenBillingPortal()}
                          disabled={billingBusy !== null}
                        >
                          {billingBusy === 'portal'
                            ? t('billing_opening_portal', { defaultValue: 'Ouverture…' })
                            : t('billing_manage_portal', { defaultValue: 'Gérer sur Stripe' })}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>,
            document.body,
          )}

          {/* ── CRÉDITS : déplacé dans sa fenêtre (voir le portal Crédits en bas du composant) ── */}
          {showCreditsModal && createPortal(
            <div className="settings-modal-overlay" data-escape-owner="" onClick={() => setShowCreditsModal(false)}>
              <div className="settings-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 640, width: '92%' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid var(--border-color, #e5e7eb)', flexShrink: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <button onClick={() => setShowCreditsModal(false)} type="button" aria-label={t('common:back', 'Back')} title={t('common:back', 'Back')} style={{ width: 32, height: 32, border: 'none', padding: 0, background: 'none', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', cursor: 'pointer', flexShrink: 0, transition: 'all 0.15s' }}>
                      <ChevronLeftIcon size={20} />
                    </button>
                    <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>{t('credits_title', { defaultValue: 'Utilisation' })}</h3>
                  </div>
                  <button onClick={() => setShowCreditsModal(false)} type="button" aria-label={t('label_close')} style={{ width: 28, height: 28, border: 'none', padding: 0, background: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 6, flexShrink: 0 }}>
                    <CloseIcon />
                  </button>
                </div>
                <div style={{ overflowY: 'auto', padding: '16px 20px 20px' }}>
              <section className="settings-section">
                <div className="settings-credit-rows">
                  <div className="settings-credit-row">
                    <div className="settings-credit-row-copy">
                      <span className="settings-credit-row-title">{dictationRowTitle}</span>
                      <span className="settings-credit-row-sub">{dictationRowSub}</span>
                    </div>
                    <div
                      className="settings-credit-row-bar"
                      role="meter"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={dictationCreditUsagePercent}
                      aria-label={dictationRowTitle}
                    >
                      <span style={{ width: `${dictationCreditUsagePercent}%` }} />
                    </div>
                    <div className="settings-credit-row-value">
                      <strong>{t('credits_usage_percent', { percent: String(dictationCreditUsagePercent), defaultValue: '{{percent}} % utilisés' })}</strong>
                      <span>{formatCreditNumber(dictationRemainingCredits)} {t('credits_row_remaining_of', { included: formatCreditNumber(dictationIncludedCredits), defaultValue: 'sur {{included}} restants' })}</span>
                    </div>
                  </div>
                  <div className="settings-credit-row">
                    <div className="settings-credit-row-copy">
                      <span className="settings-credit-row-title">{aiCreditsRowTitle}</span>
                      <span className="settings-credit-row-sub">{llmRowSub}</span>
                    </div>
                    <div
                      className="settings-credit-row-bar"
                      role="meter"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={llmCreditUsagePercent}
                      aria-label={aiCreditsRowTitle}
                    >
                      <span style={{ width: `${llmCreditUsagePercent}%` }} />
                    </div>
                    <div className="settings-credit-row-value">
                      <strong>{t('credits_usage_percent', { percent: String(llmCreditUsagePercent), defaultValue: '{{percent}} % utilisés' })}</strong>
                      <span>{formatCreditNumber(llmRemainingCredits)} {t('credits_row_remaining_of', { included: formatCreditNumber(llmIncludedCredits), defaultValue: 'sur {{included}} restants' })}</span>
                    </div>
                  </div>
                </div>
              </section>

              <section className="settings-section">
                {creditUsageError && (
                  <p className="settings-credit-usage-error" role="alert">{creditUsageError}</p>
                )}

                {billingLineupCurrent !== 'professional' && (
                  <div className="settings-credits-upsell">
                    <span>{t('credits_upsell_question', { defaultValue: 'Besoin de plus de marge ?' })}</span>
                    <button
                      type="button"
                      className="settings-credits-upsell-cta"
                      onClick={() => { setShowCreditsModal(false); setShowBillingModal(true); }}
                    >
                      {t('credits_upsell_cta', { defaultValue: 'Voir Professional' })}
                    </button>
                  </div>
                )}

                <p className="settings-credits-note">
                  {t('credits_conversion_note', { defaultValue: 'Les crédits LLM couvrent les fonctionnalités IA.' })}
                  {' '}
                  {billing?.usage_billing_enabled
                    ? t('credits_usage_billing_enabled', { defaultValue: 'Après les crédits inclus, l’usage LLM supplémentaire est facturé à l’usage.' })
                    : t('credits_usage_billing_disabled', { defaultValue: 'Quand les crédits LLM sont épuisés, les fonctions IA se mettent en pause jusqu’au renouvellement.' })}
                </p>
              </section>
                </div>
              </div>
            </div>,
            document.body,
          )}

          {/* ── IA ── */}
          {activeSection === 'ia' && (
            <>
              <section className="settings-section">
                <button
                  className="settings-training-card"
                  onClick={onOpenTraining}
                  type="button"
                >
                  <span className="training-card-icon">
                    <BrainIcon size={24} />
                    <span className="training-card-pulse" />
                  </span>
                  <span className="training-card-body">
                    <span className="training-card-title">{t('ai_training')}</span>
                    <span className="training-card-desc">{t('ai_training_sub')}</span>
                  </span>
                  <span className="training-card-arrow">
                    <ChevronRightIcon size={16} />
                  </span>
                </button>
              </section>

              {/* Skills (Specialties) — gated on ENABLE_SKILLS_CARD. See top of file. */}
              {ENABLE_SKILLS_CARD && <SpecialtiesSection />}

              <section className="settings-section">
                <button
                  className="settings-training-card"
                  onClick={() => setShowSttKeyterms(true)}
                  type="button"
                >
                  <span className="training-card-icon">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                    <span className="training-card-pulse" />
                  </span>
                  <span className="training-card-body">
                    <span className="training-card-title">{t('ai_dictation')}</span>
                    <span className="training-card-desc">{t('ai_dictation_sub')}</span>
                  </span>
                  <span className="training-card-arrow">
                    <ChevronRightIcon size={16} />
                  </span>
                </button>
              </section>

            </>
          )}

          {/* ── OUTILS ── */}
          {activeSection === 'outils' && (
            <section className="settings-section">
              <div className="settings-link-group">
                <button className="settings-link-btn" onClick={handleOpenLabelLibrary} type="button">
                  <span className="settings-link-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
                  </span>
                  <span>{t('tools_labels')}</span>
                  <ChevronRight />
                </button>
                <button className="settings-link-btn" onClick={handleOpenSnippets} type="button">
                  <span className="settings-link-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M9 4H7a2 2 0 0 0-2 2v3a2 2 0 0 1-2 2 2 2 0 0 1 2 2v3a2 2 0 0 0 2 2h2"/><path d="M15 4h2a2 2 0 0 1 2 2v3a2 2 0 0 0 2 2 2 2 0 0 0-2 2v3a2 2 0 0 1-2 2h-2"/></svg>
                  </span>
                  <span>{t('tools_snippets')}</span>
                  <ChevronRight />
                </button>
                <button className="settings-link-btn" onClick={() => setShowContactGroups(true)} type="button">
                  <span className="settings-link-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                  </span>
                  <span>{t('tools_contact_groups')}</span>
                  <ChevronRight />
                </button>
                <button className="settings-link-btn" onClick={handleOpenCleanInbox} type="button">
                  <span className="settings-link-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" y1="2" x2="22" y2="22"/></svg>
                  </span>
                  <span>{t('tools_clean_inbox')}</span>
                  <ChevronRight />
                </button>
                <button className="settings-link-btn" onClick={handleOpenNewsletters} type="button">
                  <span className="settings-link-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/></svg>
                  </span>
                  <span>{t('tools_newsletters')}</span>
                  <ChevronRight />
                </button>
              </div>

            </section>
          )}

          {/* ── PRODUCTIVITÉ ── */}
          {activeSection === 'productivite' && (
            <>
              <section className="settings-section">
                <div className="settings-link-group">
                  <button className="settings-link-btn" onClick={onOpenDeepWork} type="button">
                    <span className="settings-link-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                    </span>
                    <span>{t('productivity_focus')}</span>
                    {deepWorkActive && <span className="settings-link-badge">{tc('active', 'Activé')}</span>}
                    <ChevronRight />
                  </button>
                  <button className="settings-link-btn" onClick={onOpenShortcuts} type="button">
                    <span className="settings-link-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.001M10 8h.001M14 8h.001M18 8h.001M8 12h.001M12 12h.001M16 12h.001M7 16h10"/></svg>
                    </span>
                    <span>{t('productivity_shortcuts')}</span>
                    <ChevronRight />
                  </button>
                  <button className="settings-link-btn" onClick={onOpenMeetingReminders} type="button" disabled={!onOpenMeetingReminders}>
                    <span className="settings-link-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
                    </span>
                    <span>{t('productivity_meeting_reminders')}</span>
                    {(meetingReminderSettings.imminentBanner || meetingReminderSettings.soundBuzzer || meetingReminderSettings.leadMinutes > 0) && <span className="settings-link-badge">{tc('active', 'Activé')}</span>}
                    <ChevronRight />
                  </button>
                  {/* Removed 2026-05-13: Quick Actions entry-point lives in
                      Settings → Automation now (3 embedded cards + manage link).
                      Productivity no longer duplicates it. */}
                  <button className="settings-link-btn" onClick={() => setShowBookingLink(true)} type="button">
                    <span className="settings-link-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
                    </span>
                    <span>{t('booking_url')}</span>
                    {bookingUrl && <span className="settings-link-badge">{tc('active', 'Activé')}</span>}
                    <ChevronRight />
                  </button>
                </div>
              </section>
            </>
          )}

          {/* ── AUTOMATISATION ── */}
          {activeSection === 'automatisation' && (
            <SectionErrorBoundary label="automatisation">
            <section className="settings-section">

              <h4 className="settings-subtitle">
                {t('automatic_rules_section_label', { defaultValue: 'Automatic rules' })}
              </h4>

              <div className="settings-quicksteps-discovery">
                <div className="quickstep-card quickstep-card--static" data-embedded>
                  <div className="quickstep-card__main">
                    <div className="quickstep-card__header">
                      <span className="quickstep-card__name">
                        {t('auto_reminder_on_commitment')}
                      </span>
                      <span
                        className="quickstep-card__badge quickstep-card__badge--auto"
                        title={t('quicksteps_auto_badge', { defaultValue: 'Déclenchement automatique actif' })}
                      >
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true">
                          <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />
                        </svg>
                        {t('quicksteps_auto_badge_label', { defaultValue: 'Auto' })}
                      </span>
                    </div>
                    <div className="quickstep-card__summary">
                      {t('auto_reminder_on_commitment_desc', {
                        defaultValue: 'Programme automatiquement un rappel quand un engagement est détecté dans votre brouillon.',
                      })}
                    </div>
                  </div>
                  <div className="quickstep-card__meta">
                    <label className="quickstep-card__toggle">
                      <input
                        type="checkbox"
                        checked={autoReminderOnCommitment}
                        onChange={handleToggleAutoReminderOnCommitment}
                        aria-label={t('auto_reminder_on_commitment_aria')}
                      />
                      <span className="quickstep-card__switch" />
                    </label>
                  </div>
                </div>

                {discoverableQuickSteps.map(step => (
                  <QuickStepCard
                    key={step.id}
                    step={step}
                    embedded
                    onEdit={() => setShowQuickActions(true)}
                    onToggleEnabled={(next) => handleToggleEmbeddedQuickStep(step.id, step.enabled, next)}
                  />
                ))}
                <button
                  type="button"
                  className="settings-link-btn"
                  onClick={() => setShowQuickActions(true)}
                >
                  <span className="settings-link-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><polyline points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                  </span>
                  <span>{t('quicksteps_section_label', { defaultValue: 'Quick actions' })}</span>
                  <ChevronRight />
                </button>
              </div>

              <h4 className="settings-subtitle">{t('auto_delete')}</h4>

              <div className="settings-toggle-group">
                <label className="settings-toggle">
                  <span className="settings-label">{t('trash_after_30')}</span>
                  <input
                    type="checkbox"
                    checked={autoEmptyTrash}
                    onChange={handleToggleAutoEmptyTrash}
                    aria-label={t('trash_after_30_aria')}
                  />
                  <span className="settings-switch" />
                </label>

                <label className="settings-toggle">
                  <span className="settings-label">{t('spam_after_30')}</span>
                  <input
                    type="checkbox"
                    checked={autoEmptySpam}
                    onChange={handleToggleAutoEmptySpam}
                    aria-label={t('spam_after_30_aria')}
                  />
                  <span className="settings-switch" />
                </label>

                <label className="settings-toggle">
                  <span className="settings-label">{t('noise_after_30')}</span>
                  <input
                    type="checkbox"
                    checked={autoDeleteNoise}
                    onChange={handleToggleAutoDeleteNoise}
                    aria-label={t('noise_after_30_aria')}
                  />
                  <span className="settings-switch" />
                </label>
              </div>

            </section>
            </SectionErrorBoundary>
          )}

          {/* ── GÉNÉRAL ── */}
          {activeSection === 'general' && (
            <>
              <section className="settings-section">

                <h4 className="settings-subtitle settings-subtitle--first">{t('general_group_display')}</h4>

                <LanguageSelector />

                <div className="settings-theme-picker">
                  <span className="settings-label">{t('theme')}</span>
                  <div className="settings-theme-options">
                    {([
                      { id: 'default' as ThemeId, label: 'Clarity', gradient: 'linear-gradient(135deg, #f8f9fa, #0d9488)' },
                    ]).map((t) => (
                      <button
                        key={t.id}
                        className={`theme-option-card ${theme === t.id ? 'active' : ''}`}
                        onClick={() => setTheme(t.id)}
                        type="button"
                      >
                        <span className="theme-option-preview" style={{ background: t.gradient }} />
                        <span className="theme-option-label">{t.label}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="settings-font-picker">
                  <span className="settings-label">{t('compose_font')}</span>
                  <div className="settings-font-options">
                    {FONT_FAMILY_OPTIONS.map((f) => (
                      <button
                        key={f.id}
                        className={`font-option-card${fontFamily === f.id ? ' active' : ''}`}
                        onClick={() => setFontFamily(f.id)}
                        type="button"
                      >
                        <span className="font-option-sample" style={{ fontFamily: FONT_FAMILY_MAP[f.id] }}>Aa</span>
                        <span className="font-option-label">{f.label}</span>
                      </button>
                    ))}
                  </div>
                  <span className="settings-label">{t('compose_font_size')}</span>
                  <div className="settings-font-size-options">
                    {(['small', 'medium', 'large', 'xlarge'] as ComposeFontSize[]).map((id) => (
                      <button
                        key={id}
                        className={`font-size-option${fontSize === id ? ' active' : ''}`}
                        onClick={() => setFontSize(id)}
                        type="button"
                      >
                        {FONT_SIZE_MAP[id]}
                      </button>
                    ))}
                  </div>
                  {/* Caption disambiguating this from "Interface zoom" below:
                      this size applies only to the email body you compose. */}
                  <div className="settings-zoom-hint">{t('compose_font_size_hint', { defaultValue: 'Font size for emails you write' })}</div>
                  <span className="settings-label">{t('compose_font_preview')}</span>
                  <div
                    className="settings-font-preview"
                    style={{ fontFamily: FONT_FAMILY_MAP[fontFamily] }}
                    aria-label={t('compose_font_preview_aria', { defaultValue: 'Font preview' })}
                  >
                    <div className="settings-font-preview-meta">
                      {t('compose_font_preview_subject', { defaultValue: 'Re: Q3 forecast review' })}
                    </div>
                    <div
                      className="settings-font-preview-body"
                      style={{ fontSize: FONT_SIZE_MAP[fontSize] }}
                    >
                      {t('compose_font_preview_body', { defaultValue: 'Hi Jordan — thanks for the thoughtful proposal. I’ll review the numbers tonight and send feedback by 9am tomorrow.' })}
                    </div>
                  </div>
                </div>

                <div className="settings-zoom-picker">
                  <div className="settings-zoom-header">
                    <span className="settings-label">{t('app_zoom')}</span>
                  </div>
                  <div className="settings-zoom-options">
                    {ZOOM_LEVELS.map((lvl) => (
                      <button
                        key={lvl}
                        type="button"
                        className={`zoom-option${zoom === lvl ? ' active' : ''}`}
                        onClick={() => setZoom(lvl)}
                        aria-pressed={zoom === lvl}
                      >
                        {Math.round(lvl * 100)}%
                      </button>
                    ))}
                    {zoom !== DEFAULT_ZOOM && (
                      <button
                        type="button"
                        className="zoom-reset"
                        onClick={resetZoom}
                      >
                        {t('app_zoom_reset')}
                      </button>
                    )}
                  </div>
                  <p className="settings-zoom-hint">{t('app_zoom_hint')}</p>
                </div>

                {/* Email list density — reuses .settings-zoom-picker styling
                    so the three preferences (zoom %, view mode, language)
                    read as a coherent group of display controls. The hook
                    was wired in EmailList / SwipeableEmailItem from day 1
                    but never had a UI control; restored here 2026-05-13. */}
                <div className="settings-zoom-picker">
                  <div className="settings-zoom-header">
                    <span className="settings-label">{t('email_view_mode_label', { defaultValue: 'Densité de la liste' })}</span>
                  </div>
                  <div className="settings-zoom-options">
                    {(['compact', 'balanced', 'comfortable'] as EmailViewMode[]).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        className={`zoom-option${emailViewMode === mode ? ' active' : ''}`}
                        onClick={() => setEmailViewMode(mode)}
                        aria-pressed={emailViewMode === mode}
                      >
                        {t(`email_view_mode_${mode}`, {
                          defaultValue:
                            mode === 'compact' ? 'Compact'
                            : mode === 'balanced' ? 'Équilibré'
                            : 'Confortable',
                        })}
                      </button>
                    ))}
                  </div>
                  <p className="settings-zoom-hint">
                    {t('email_view_mode_hint', {
                      defaultValue: 'Confortable affiche l\'avatar, le destinataire et un aperçu sur 3 lignes. Compact tient plus d\'emails à l\'écran.',
                    })}
                  </p>
                </div>

                {/* Inbox display preferences — moved from Automation 2026-05-13
                    because hiding noise-labeled emails is a view filter, not
                    an automation that acts on emails. */}
                <div className="settings-toggle-group">
                  <label className="settings-toggle">
                    <span className="settings-label">{t('hide_noise')}</span>
                    <input
                      type="checkbox"
                      checked={hideNoise}
                      onChange={handleToggleHideNoise}
                      aria-label={t('hide_noise_aria')}
                    />
                    <span className="settings-switch" />
                  </label>
                </div>

                <h4 className="settings-subtitle">{t('general_group_app')}</h4>
                <AutostartToggle />

                <div className="settings-replay-tour">
                  <div className="settings-replay-tour-main">
                    <span className="settings-link-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                        <path d="M3 3v5h5"/>
                      </svg>
                    </span>
                    <div className="settings-replay-tour-text">
                      <span className="settings-label">{t('replay_v2_title')}</span>
                      <span className="settings-replay-tour-desc">{t('replay_v2_desc')}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="settings-replay-tour-btn"
                    onClick={() => {
                      onClose()
                      window.dispatchEvent(new CustomEvent('onboarding-v2:replay'))
                    }}
                  >
                    {t('replay_v2_btn')}
                  </button>
                </div>
              </section>

              {/* AI Provider section hidden — Claude is the default and the
                  picker confuses non-power users. Re-enable by removing this
                  comment block if multi-provider config becomes user-facing. */}
              {/*
              <section className="settings-section">
                <h4 className="settings-subtitle">{t('ai_provider')}</h4>
                <LLMSettings />
              </section>
              */}

              <section className="settings-section">
                <button className="settings-link-btn" onClick={() => setShowBgTasks(true)} type="button">
                  <span className="settings-link-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
                  </span>
                  <span>{t('bulk_actions_title')}</span>
                  <ChevronRight />
                </button>
              </section>

              <section className="settings-section">
                <ReferralPanel />
              </section>




              {/* Restart onboarding — hidden (dev-only, not user-facing) */}
            </>
          )}



          </div>
        </div>
      </div>

      {showCleanInboxModal && (
        <CleanInboxModal
          onClose={handleCloseCleanInbox}
          onClean={handleCleanInbox}
        />
      )}

      <SignatureModal
        isOpen={showSignatureModal}
        onClose={handleCloseSignature}
      />

      <SttKeytermsModal
        isOpen={showSttKeyterms}
        onClose={() => setShowSttKeyterms(false)}
      />

      <BackgroundTasksModal
        isOpen={showBgTasks}
        onClose={() => setShowBgTasks(false)}
      />

      <QuickActionsModal
        isOpen={showQuickActions}
        onClose={() => setShowQuickActions(false)}
      />

      <BookingLinkPanel
        isOpen={showBookingLink}
        onClose={() => setShowBookingLink(false)}
        onBack={() => setShowBookingLink(false)}
        accountId={accountId}
      />

      {showNewslettersModal && (
        <NewslettersModal onClose={handleCloseNewsletters} />
      )}

      {showAutoReplyModal && (
        <AutoReplyModal onClose={() => setShowAutoReplyModal(false)} accountId={accountId} />
      )}

      {showContactGroups && (
        <ContactGroupsManager onClose={() => setShowContactGroups(false)} />
      )}

      {showBlockedSenders && (
        <BlockedSendersModal
          onClose={() => setShowBlockedSenders(false)}
          onBack={() => {
            setShowBlockedSenders(false);
            setActiveSection(blockedSendersSourceSection);
          }}
        />
      )}

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}

/* ── BlockedSendersModal ────────────────────────────────────── */

function BlockedSendersModal({ onClose, onBack }: { onClose: () => void; onBack?: () => void }) {
  const { t } = useTranslation('settings');
  const [blockedSenders, setBlockedSenders] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);
  const [newSender, setNewSender] = useState('');
  const [isAdding, setIsAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  useEffect(() => {
    getBlockedSenders()
      .then((res) => {
        setBlockedSenders(res.blocked_senders || []);
        setFetchError(false);
      })
      .catch(() => {
        setBlockedSenders([]);
        setFetchError(true);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleUnblock = useCallback((email: string) => {
    unblockSender(email)
      .then((res) => {
        setBlockedSenders(res.blocked_senders || []);
      })
      .catch(() => {
        // silently fail
      });
  }, []);

  const handleAddBlockedSender = useCallback(async () => {
    const email = newSender.trim();
    if (!email) {
      setAddError(t('blocked_senders_empty_input') || 'Veuillez entrer une adresse email');
      return;
    }
    // Basic email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      setAddError(t('blocked_senders_invalid_email') || 'Adresse email invalide');
      return;
    }
    setIsAdding(true);
    setAddError(null);
    try {
      const res = await blockSender(email);
      setBlockedSenders(res.blocked_senders || []);
      setNewSender('');
    } catch (_err) {
      setAddError(t('blocked_senders_add_error') || 'Erreur lors de l\'ajout');
    } finally {
      setIsAdding(false);
    }
  }, [newSender, t]);

  // Escape key closes the modal — skip when typing in fields so inner popups
  // (autocompletes) handle Escape themselves first.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const tgt = e.target as HTMLElement | null;
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable)) {
        return;
      }
      onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return createPortal(
    <div className="settings-modal-overlay" onClick={onClose}>
      <div
        className="settings-modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 480, width: '90%' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid var(--border-color, #e5e7eb)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button onClick={onBack || onClose} type="button" aria-label={t('common:back', 'Back')} title={t('common:back', 'Back')} style={{ width: 32, height: 32, border: 'none', padding: 0, background: 'none', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', cursor: 'pointer', flexShrink: 0, transition: 'all 0.15s' }}>
              <ChevronLeftIcon size={20} />
            </button>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>{t('blocked_senders')}</h3>
          </div>
          <button onClick={onClose} type="button" aria-label={t('label_close')} style={{ width: 28, height: 28, border: 'none', padding: 0, background: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 6 }}>
            <CloseIcon />
          </button>
        </div>
        <div style={{ padding: '20px 24px' }}>
          {/* Input section */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
            <div style={{ flex: 1 }}>
              {/*
                ContactAutocomplete (single mode) so the user can pick a known
                sender from suggestions instead of typing the full address.
                ``includeAllContacts=true`` so INBOUND senders (the typical
                block target — someone who emailed you) show up, not just
                people you've emailed. ``includeSelf=false`` because blocking
                yourself is meaningless.
                Note : addresses already caught by the noreply / noise filters
                won't appear here, so the most common "block this spammer"
                path still requires typing manually — same UX as before plus
                suggestions when the target IS a known contact.
              */}
              <ContactAutocomplete
                value={newSender}
                onChange={(v) => { setNewSender(v); setAddError(null); }}
                placeholder={t('blocked_senders_input_placeholder')}
                disabled={isAdding}
                multi={false}
                includeAllContacts={true}
                includeSelf={false}
                onContactSelect={({ email: picked }) => {
                  setNewSender(picked)
                  setAddError(null)
                }}
              />
            </div>
            <button
              onClick={handleAddBlockedSender}
              disabled={isAdding || !newSender.trim()}
              type="button"
              style={{
                padding: '9px 16px', fontSize: 13, fontWeight: 500, fontFamily: 'var(--font-sans)',
                border: 'none', borderRadius: 8,
                background: 'var(--accent-primary, #0d9488)', color: 'white',
                cursor: isAdding || !newSender.trim() ? 'not-allowed' : 'pointer',
                transition: 'opacity 0.15s, transform 0.1s',
                opacity: isAdding || !newSender.trim() ? 0.5 : 1,
                whiteSpace: 'nowrap', flexShrink: 0,
              }}
            >
              {isAdding ? (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 14, height: 14, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spin 0.6s linear infinite', display: 'inline-block' }} />
                </span>
              ) : (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>
                  </svg>
                  {t('blocked_senders_add')}
                </span>
              )}
            </button>
          </div>
          {addError && (
            <p style={{ fontSize: 12, color: 'var(--danger-color, #ef4444)', margin: '-12px 0 12px 0' }}>
              {addError}
            </p>
          )}

          {loading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}>
              <span style={{ width: 20, height: 20, border: '2px solid var(--border-default)', borderTopColor: 'var(--accent-primary)', borderRadius: '50%', animation: 'spin 0.6s linear infinite', display: 'inline-block' }} />
            </div>
          ) : fetchError ? (
            <p style={{ color: 'var(--danger-color, #ef4444)', textAlign: 'center', padding: 24, fontSize: 13 }}>
              {t('blocked_senders_fetch_error')}
            </p>
          ) : blockedSenders.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '32px 16px' }}>
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-placeholder)" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" style={{ margin: '0 auto 12px', opacity: 0.5 }}>
                <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="17" x2="22" y1="11" y2="11"/>
              </svg>
              <p style={{ color: 'var(--text-placeholder)', fontSize: 13, margin: 0 }}>
                {t('blocked_senders_empty')}
              </p>
            </div>
          ) : (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {blockedSenders.map((sender) => (
                <li
                  key={sender}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '10px 12px', marginBottom: 4,
                    borderRadius: 8, transition: 'background 0.12s',
                    background: 'var(--surface-secondary)',
                  }}
                >
                  <span style={{ fontSize: 13, color: 'var(--text-primary)', fontFamily: 'var(--font-sans)' }}>{sender}</span>
                  <button
                    onClick={() => handleUnblock(sender)}
                    type="button"
                    style={{
                      padding: '4px 10px', fontSize: 12, fontWeight: 500,
                      border: 'none', borderRadius: 6,
                      background: 'none', color: 'var(--text-tertiary)',
                      cursor: 'pointer',
                    }}
                  >
                    {t('blocked_senders_unblock')}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
