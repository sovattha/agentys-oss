/**
 * Single source of truth for the agentys-app localStorage keys.
 *
 * Pre-existing scatter: each consumer (App, useBackendConnection,
 * useOnboardingState, useOnboardingV2, useOnboardingWizard,
 * clearUserData service) hardcoded the same raw string. A future
 * rename or namespacing refactor would have had to touch many sites —
 * drift risk.
 *
 * Keep this file the only place that names the strings. Consumers import
 * the const, never the literal.
 */

/** First-run onboarding completed (provider connected + base setup). */
export const ONBOARDING_COMPLETE_KEY = 'agentys_onboarding_complete';

/** Knowledge-base ingestion phase of onboarding completed. */
export const ONBOARDING_KB_COMPLETE_KEY = 'agentys_onboarding_kb_complete';

/** Manual override that re-opens the onboarding wizard regardless of state. */
export const FORCE_ONBOARDING_KEY = 'agentys_force_onboarding';
