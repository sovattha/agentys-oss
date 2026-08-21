/**
 * Bus d'événements applicatifs légers.
 *
 * Usage : découpler les API clients des hooks React sans dépendance circulaire.
 * Par exemple : `activateAccount()` dispatch `ACCOUNT_CHANGED`, et `useCurrentAccountId`
 * écoute pour invalider son cache module-level.
 */

export const appEvents = new EventTarget();

export const ACCOUNT_CHANGED = "agentys:account-changed";
