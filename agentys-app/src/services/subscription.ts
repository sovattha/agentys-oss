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

/**
 * Subscription types and billing helpers.
 * Checkout and Customer Portal use the backend Stripe API; legacy trial,
 * referral, and usage widgets still keep their local mock state.
 */

import { API_URL } from '../config'
import { getAuthHeaders, handleAuthResponse } from './authToken'
import { formatCompactDate } from '../utils/dateFormat'

// Dev-only logger: no-op in production builds
const devLog = import.meta.env.DEV ? console.log.bind(console) : (() => {}) as typeof console.log

/**
 * Subscription plan types
 */
export type SubscriptionPlan = 'trial' | 'premium' | 'expired'

/**
 * Subscription status types
 */
export type SubscriptionStatus = 'active' | 'trialing' | 'past_due' | 'canceled' | 'expired'

/**
 * Subscription data interface
 */
export interface Subscription {
  /** Current plan type */
  plan: SubscriptionPlan
  /** Subscription status */
  status: SubscriptionStatus
  /** Renewal or trial end date (ISO string) */
  currentPeriodEnd: string | null
  /** Trial start date (ISO string) */
  trialStart: string | null
  /** Trial end date (ISO string) */
  trialEnd: string | null
  /** Whether there's a payment issue */
  hasPaymentIssue: boolean
  /** Payment issue message (if any) */
  paymentIssueMessage: string | null
  /** Stripe customer portal URL (if available) */
  stripePortalUrl: string | null
  /** Monthly price in cents */
  pricePerMonth: number
}

/**
 * Payment history item interface
 */
export interface PaymentHistoryItem {
  /** Unique payment ID */
  id: string
  /** Payment date (ISO string) */
  date: string
  /** Amount in cents */
  amount: number
  /** Currency code (e.g., 'eur', 'usd') */
  currency: string
  /** Payment status */
  status: 'succeeded' | 'failed' | 'pending' | 'refunded'
  /** Invoice URL (if available) */
  invoiceUrl: string | null
  /** Description of the payment */
  description: string
}

/**
 * Subscription service response interface
 */
export interface SubscriptionData {
  subscription: Subscription
  paymentHistory: PaymentHistoryItem[]
}

/**
 * Mock subscription data for development
 * This will be replaced by real API calls once Story 9.2 is implemented
 */
const MOCK_SUBSCRIPTION: Subscription = {
  plan: 'trial',
  status: 'trialing',
  currentPeriodEnd: new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString(), // 5 days from now
  trialStart: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(), // 2 days ago
  trialEnd: new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString(), // 5 days from now
  hasPaymentIssue: false,
  paymentIssueMessage: null,
  stripePortalUrl: 'https://billing.stripe.com/p/login/mock_portal_session',
  pricePerMonth: 2500, // $25.00 USD (Story 9-2 AC2)
}

const MOCK_PAYMENT_HISTORY: PaymentHistoryItem[] = []

/**
 * Mock subscription with payment issue for testing AC5
 */
export const MOCK_SUBSCRIPTION_WITH_ISSUE: Subscription = {
  plan: 'premium',
  status: 'past_due',
  currentPeriodEnd: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(), // 3 days ago
  trialStart: null,
  trialEnd: null,
  hasPaymentIssue: true,
  paymentIssueMessage: 'Your last payment failed. Please update your payment information.',
  stripePortalUrl: 'https://billing.stripe.com/p/login/mock_portal_session',
  pricePerMonth: 2500,
}

/**
 * Mock premium subscription for testing
 */
export const MOCK_PREMIUM_SUBSCRIPTION: Subscription = {
  plan: 'premium',
  status: 'active',
  currentPeriodEnd: new Date(Date.now() + 25 * 24 * 60 * 60 * 1000).toISOString(), // 25 days from now
  trialStart: null,
  trialEnd: null,
  hasPaymentIssue: false,
  paymentIssueMessage: null,
  stripePortalUrl: 'https://billing.stripe.com/p/login/mock_portal_session',
  pricePerMonth: 2500,
}

/**
 * Mock payment history for testing
 */
export const MOCK_PAYMENT_HISTORY_WITH_DATA: PaymentHistoryItem[] = [
  {
    id: 'pi_mock_1',
    date: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString(), // 30 days ago
    amount: 2500,
    currency: 'eur',
    status: 'succeeded',
    invoiceUrl: 'https://invoice.stripe.com/mock_invoice_1',
    description: 'Premium Subscription - January 2026',
  },
  {
    id: 'pi_mock_2',
    date: new Date(Date.now() - 60 * 24 * 60 * 60 * 1000).toISOString(), // 60 days ago
    amount: 2500,
    currency: 'eur',
    status: 'succeeded',
    invoiceUrl: 'https://invoice.stripe.com/mock_invoice_2',
    description: 'Premium Subscription - December 2025',
  },
]

/**
 * Subscription service class
 * Provides methods to fetch subscription data
 */
class SubscriptionService {
  private mockData: SubscriptionData = {
    subscription: MOCK_SUBSCRIPTION,
    paymentHistory: MOCK_PAYMENT_HISTORY,
  }

  /**
   * Set mock data for testing purposes
   */
  setMockData(subscription: Subscription, paymentHistory: PaymentHistoryItem[]): void {
    this.mockData = { subscription, paymentHistory }
  }

  /**
   * Reset mock data to defaults
   */
  resetMockData(): void {
    this.mockData = {
      subscription: MOCK_SUBSCRIPTION,
      paymentHistory: MOCK_PAYMENT_HISTORY,
    }
  }

  /**
   * Fetch current subscription data
   * Will be connected to real API once Story 9.2 is implemented
   */
  async getSubscription(): Promise<SubscriptionData> {
    // Simulate API delay
    await new Promise(resolve => setTimeout(resolve, 100))
    return this.mockData
  }

  /**
   * Open Stripe customer portal
   * Will be connected to real API once Story 9.2 is implemented
   */
  async openStripePortal(): Promise<void> {
    const { subscription } = await this.getSubscription()
    if (subscription.stripePortalUrl) {
      window.open(subscription.stripePortalUrl, '_blank', 'noopener,noreferrer')
    }
  }

  /**
   * Format price for display
   */
  formatPrice(amountInCents: number, currency: string = 'eur'): string {
    const amount = amountInCents / 100
    const formatter = new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: currency.toUpperCase(),
    })
    return formatter.format(amount)
  }

  /**
   * Get days remaining until date
   */
  getDaysRemaining(dateString: string | null): number | null {
    if (!dateString) return null
    const endDate = new Date(dateString)
    const now = new Date()
    const diffTime = endDate.getTime() - now.getTime()
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
    return diffDays
  }

  /**
   * Format date for display
   */
  formatDate(dateString: string | null): string {
    if (!dateString) return '-'
    return formatCompactDate(new Date(dateString))
  }

  /**
   * Get plan display name
   */
  getPlanDisplayName(plan: SubscriptionPlan): string {
    const names: Record<SubscriptionPlan, string> = {
      trial: 'Free Trial',
      premium: 'Premium',
      expired: 'Expired',
    }
    return names[plan]
  }

  /**
   * Get status display info
   */
  getStatusDisplay(status: SubscriptionStatus): { label: string; variant: 'success' | 'warning' | 'error' | 'info' } {
    const statusMap: Record<SubscriptionStatus, { label: string; variant: 'success' | 'warning' | 'error' | 'info' }> = {
      active: { label: 'Active', variant: 'success' },
      trialing: { label: 'Trial period', variant: 'info' },
      past_due: { label: 'Payment overdue', variant: 'warning' },
      canceled: { label: 'Canceled', variant: 'error' },
      expired: { label: 'Expired', variant: 'error' },
    }
    return statusMap[status]
  }
}

/**
 * Trial storage keys (Story 9-1, 9-3)
 */
const TRIAL_STORAGE_KEYS = {
  EMAIL: 'agentys_trial_email',
  START: 'agentys_trial_start',
  END: 'agentys_trial_end',
  WELCOME_SENT: 'agentys_trial_welcome_sent',
  EXPIRATION_NOTIFIED: 'agentys_trial_expiration_notified',
  DATA_DELETION_WARNING_SHOWN: 'agentys_trial_data_deletion_warning',
} as const

/**
 * Trial status types (Story 9-3: added 'last_day' for J0)
 */
export type TrialStatus = 'not_started' | 'active' | 'expiring_soon' | 'last_day' | 'expired'

/**
 * Trial duration in days
 */
const TRIAL_DURATION_DAYS = 7

/**
 * Days before expiration to show warning (J-2)
 */
const EXPIRATION_WARNING_DAYS = 2

/**
 * Days to retain data after expiration (Story 9-3 AC5)
 */
const DATA_RETENTION_DAYS = 30

/**
 * Trial service for managing free trial signup (Story 9-1)
 */
class TrialService {
  /**
   * Start a new free trial (AC1, AC2)
   * @param email User's email address
   */
  async startTrial(email: string): Promise<{ success: boolean; trialEnd: string }> {
    if (!email || !this.isValidEmail(email)) {
      throw new Error('Invalid email address')
    }

    // Check if trial already exists
    const existingEmail = localStorage.getItem(TRIAL_STORAGE_KEYS.EMAIL)
    if (existingEmail) {
      throw new Error('A free trial is already in progress')
    }

    const now = new Date()
    const trialEnd = new Date(now.getTime() + TRIAL_DURATION_DAYS * 24 * 60 * 60 * 1000)

    // Store trial data
    localStorage.setItem(TRIAL_STORAGE_KEYS.EMAIL, email)
    localStorage.setItem(TRIAL_STORAGE_KEYS.START, now.toISOString())
    localStorage.setItem(TRIAL_STORAGE_KEYS.END, trialEnd.toISOString())

    // Update subscription service mock data
    subscriptionService.setMockData(
      {
        plan: 'trial',
        status: 'trialing',
        currentPeriodEnd: trialEnd.toISOString(),
        trialStart: now.toISOString(),
        trialEnd: trialEnd.toISOString(),
        hasPaymentIssue: false,
        paymentIssueMessage: null,
        stripePortalUrl: null,
        pricePerMonth: 2500,
      },
      []
    )

    // Send welcome email (AC3) - mock for now
    await this.sendWelcomeEmail(email)

    return { success: true, trialEnd: trialEnd.toISOString() }
  }

  /**
   * Get current trial status (AC4, Story 9-3 AC2)
   */
  getTrialStatus(): { status: TrialStatus; email: string | null; daysRemaining: number | null; trialEnd: string | null } {
    const email = localStorage.getItem(TRIAL_STORAGE_KEYS.EMAIL)
    const trialEndStr = localStorage.getItem(TRIAL_STORAGE_KEYS.END)

    if (!email || !trialEndStr) {
      return { status: 'not_started', email: null, daysRemaining: null, trialEnd: null }
    }

    const trialEnd = new Date(trialEndStr)
    const now = new Date()
    const diffTime = trialEnd.getTime() - now.getTime()
    const daysRemaining = Math.ceil(diffTime / (1000 * 60 * 60 * 24))

    if (daysRemaining <= 0) {
      return { status: 'expired', email, daysRemaining: 0, trialEnd: trialEndStr }
    }

    // J0: Last day of trial (Story 9-3 AC2)
    if (daysRemaining === 1) {
      return { status: 'last_day', email, daysRemaining: 1, trialEnd: trialEndStr }
    }

    // J-2, J-1: Expiring soon
    if (daysRemaining <= EXPIRATION_WARNING_DAYS) {
      return { status: 'expiring_soon', email, daysRemaining, trialEnd: trialEndStr }
    }

    return { status: 'active', email, daysRemaining, trialEnd: trialEndStr }
  }

  /**
   * Check if trial is expiring soon and notification hasn't been sent (AC5)
   */
  shouldShowExpirationNotification(): boolean {
    const { status } = this.getTrialStatus()
    const alreadyNotified = localStorage.getItem(TRIAL_STORAGE_KEYS.EXPIRATION_NOTIFIED) === 'true'

    return status === 'expiring_soon' && !alreadyNotified
  }

  /**
   * Mark expiration notification as sent
   */
  markExpirationNotified(): void {
    localStorage.setItem(TRIAL_STORAGE_KEYS.EXPIRATION_NOTIFIED, 'true')
  }

  /**
   * Send welcome email (AC3) - mock implementation
   */
  private async sendWelcomeEmail(email: string): Promise<void> {
    // Mark welcome email as sent
    localStorage.setItem(TRIAL_STORAGE_KEYS.WELCOME_SENT, 'true')

    // TODO: Connect to real email service when backend is implemented
    devLog(`[Mock] Welcome email sent to ${email}`)
    devLog(`[Mock] Getting started guide:
        1. Connect your email account
        2. Configure your writing style
        3. Receive your first draft in under 5 minutes!
      `)
  }

  /**
   * Validate email format
   */
  private isValidEmail(email: string): boolean {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    return emailRegex.test(email)
  }

  /**
   * Reset trial data (for testing)
   */
  resetTrial(): void {
    localStorage.removeItem(TRIAL_STORAGE_KEYS.EMAIL)
    localStorage.removeItem(TRIAL_STORAGE_KEYS.START)
    localStorage.removeItem(TRIAL_STORAGE_KEYS.END)
    localStorage.removeItem(TRIAL_STORAGE_KEYS.WELCOME_SENT)
    localStorage.removeItem(TRIAL_STORAGE_KEYS.EXPIRATION_NOTIFIED)
    localStorage.removeItem(TRIAL_STORAGE_KEYS.DATA_DELETION_WARNING_SHOWN)
    subscriptionService.resetMockData()
  }

  /**
   * Check if user has an active trial or subscription
   */
  hasActiveSubscription(): boolean {
    const { status } = this.getTrialStatus()
    return status === 'active' || status === 'expiring_soon' || status === 'last_day'
  }

  /**
   * Check if trial is in read-only mode (Story 9-3 AC3)
   * After expiration, users can only read emails but not generate drafts
   */
  isReadOnly(): boolean {
    // If user has a paid subscription, they're not read-only
    if (stripeService.hasActiveSubscription()) {
      return false
    }

    const { status } = this.getTrialStatus()
    return status === 'expired'
  }

  /**
   * Get data retention status (Story 9-3 AC5)
   * Data is retained for 30 days after trial expiration
   */
  getDataRetentionStatus(): {
    isInRetentionPeriod: boolean
    daysUntilDeletion: number | null
    deletionDate: string | null
  } {
    const { status, trialEnd } = this.getTrialStatus()

    if (status !== 'expired' || !trialEnd) {
      return { isInRetentionPeriod: false, daysUntilDeletion: null, deletionDate: null }
    }

    const trialEndDate = new Date(trialEnd)
    const deletionDate = new Date(trialEndDate.getTime() + DATA_RETENTION_DAYS * 24 * 60 * 60 * 1000)
    const now = new Date()
    const diffTime = deletionDate.getTime() - now.getTime()
    const daysUntilDeletion = Math.ceil(diffTime / (1000 * 60 * 60 * 24))

    return {
      isInRetentionPeriod: daysUntilDeletion > 0,
      daysUntilDeletion: Math.max(0, daysUntilDeletion),
      deletionDate: deletionDate.toISOString(),
    }
  }

  /**
   * Check if data deletion warning should be shown
   */
  shouldShowDataDeletionWarning(): boolean {
    const { isInRetentionPeriod, daysUntilDeletion } = this.getDataRetentionStatus()
    const alreadyShown = localStorage.getItem(TRIAL_STORAGE_KEYS.DATA_DELETION_WARNING_SHOWN) === 'true'

    // Show warning when less than 7 days until deletion
    return isInRetentionPeriod && daysUntilDeletion !== null && daysUntilDeletion <= 7 && !alreadyShown
  }

  /**
   * Mark data deletion warning as shown
   */
  markDataDeletionWarningShown(): void {
    localStorage.setItem(TRIAL_STORAGE_KEYS.DATA_DELETION_WARNING_SHOWN, 'true')
  }
}

/**
 * Stripe storage keys (Story 9-2, 9-4)
 */
const STRIPE_STORAGE_KEYS = {
  SUBSCRIPTION_ID: 'agentys_stripe_subscription_id',
  CUSTOMER_ID: 'agentys_stripe_customer_id',
  SUBSCRIPTION_STATUS: 'agentys_stripe_subscription_status',
  CURRENT_PERIOD_END: 'agentys_stripe_current_period_end',
  CHECKOUT_PENDING: 'agentys_stripe_checkout_pending',
  CANCEL_AT_PERIOD_END: 'agentys_stripe_cancel_at_period_end',
} as const

/**
 * Stripe checkout session response
 */
export interface StripeCheckoutSession {
  /** Checkout session ID */
  sessionId: string
  /** URL to redirect to Stripe Checkout */
  checkoutUrl: string
}

export type StripeCheckoutPlan = 'starter' | 'professional'
export type StripeCheckoutInterval = 'monthly' | 'yearly'

export interface StripeCheckoutOptions {
  plan?: StripeCheckoutPlan
  interval?: StripeCheckoutInterval
}

export interface BillingEntitlement {
  plan: string
  subscription_status: string
  ai_enabled: boolean
  reason: string
  limits?: {
    deepgram_minutes_per_day?: number
    deepgram_active_days_per_month?: number | null
    deepgram_minutes_per_month?: number | null
    llm_monthly_budget_usd?: number
  }
  user_id?: number | null
  stripe_customer_id?: string | null
  stripe_subscription_id?: string | null
  current_period_end?: string | null
  cancel_at_period_end?: boolean
  usage_billing_enabled?: boolean
}

export interface BillingCreditUsageItem {
  included_credits: number
  used_credits: number
  remaining_credits: number
  overage_credits: number
  resets_at: string | null
}

export interface BillingCreditUsage {
  llm: BillingCreditUsageItem & {
    usage_billing_enabled: boolean
  }
  dictation: BillingCreditUsageItem & {
    window: 'day' | 'month'
  }
}

export interface VoiceDictationEntitlementSnapshot {
  plan?: string | null
  subscription_status?: string | null
  ai_enabled?: boolean | null
  billing?: VoiceDictationEntitlementSnapshot | null
}

const VOICE_TRIAL_PLANS = new Set(['trial', 'free_trial'])
const VOICE_INACTIVE_STATUSES = new Set(['none', 'expired', 'canceled', 'cancelled', 'past_due', 'unpaid', 'incomplete'])

export function canUseVoiceDictation(snapshot?: VoiceDictationEntitlementSnapshot | null): boolean {
  const billing = snapshot?.billing ?? snapshot
  if (!billing) return true

  const hasBillingSignal =
    billing.ai_enabled !== undefined ||
    billing.plan !== undefined ||
    billing.subscription_status !== undefined
  if (!hasBillingSignal) return true

  if (billing.ai_enabled === true) return true

  const plan = (billing.plan ?? '').toLowerCase()
  const status = (billing.subscription_status ?? '').toLowerCase()

  if (status === 'trialing') return true
  if (VOICE_TRIAL_PLANS.has(plan) && !VOICE_INACTIVE_STATUSES.has(status)) return true
  if (status === 'active' && plan !== 'free') return true
  if (plan === 'free' || VOICE_INACTIVE_STATUSES.has(status)) return false

  return false
}

/**
 * Stripe subscription activation result
 */
export interface StripeSubscriptionResult {
  success: boolean
  subscriptionId?: string
  customerId?: string
  status?: SubscriptionStatus
  currentPeriodEnd?: string
  error?: string
}

/**
 * Invoice interface (Story 9-4 AC3)
 */
export interface Invoice {
  /** Unique invoice ID */
  id: string
  /** Amount in cents */
  amount: number
  /** Currency code (e.g., 'eur', 'usd') */
  currency: string
  /** Invoice date (ISO string) */
  date: string
  /** Payment status */
  status: 'paid' | 'open' | 'void' | 'draft' | 'uncollectible'
  /** URL to download PDF invoice */
  invoicePdfUrl: string | null
  /** Hosted Stripe invoice URL */
  hostedInvoiceUrl: string | null
  /** Description of the invoice */
  description: string
}

/**
 * Detailed subscription information (Story 9-4 AC5)
 */
export interface SubscriptionDetails {
  /** Stripe subscription ID */
  subscriptionId: string | null
  /** Stripe customer ID */
  customerId: string | null
  /** Current subscription status */
  status: SubscriptionStatus | null
  /** End of current billing period (ISO string) */
  currentPeriodEnd: string | null
  /** Whether subscription will cancel at period end */
  cancelAtPeriodEnd: boolean
  /** Current plan name */
  plan: string
  /** Stripe price ID */
  priceId: string | null
  /** Monthly price in cents */
  pricePerMonth: number | null
  /** Currency code */
  currency: string | null
}

/**
 * Stripe service for handling Stripe Checkout (Story 9-2)
 */
class StripeService {
  private billingCache: BillingEntitlement | null = null

  /**
   * Fetch the backend billing entitlement for the authenticated user.
   * This is the source of truth for paid AI access.
   */
  async getBilling(options: { fresh?: boolean; sessionId?: string | null } = {}): Promise<BillingEntitlement> {
    const params = new URLSearchParams()
    if (options.fresh) params.set('fresh', 'true')
    if (options.sessionId) params.set('session_id', options.sessionId)
    const query = params.toString() ? `?${params.toString()}` : ''
    const response = handleAuthResponse(await fetch(`${API_URL}/api/billing/me${query}`, {
      headers: getAuthHeaders(),
    }))
    const data = await response.json().catch(() => ({})) as {
      billing?: BillingEntitlement
      error?: string
    }
    if (!response.ok || !data.billing) {
      throw new Error(data.error || 'Unable to load billing status')
    }
    this.billingCache = data.billing
    return data.billing
  }

  /** Dernier entitlement billing connu (sans refetch). Null tant que non chargé. */
  getCachedBilling(): BillingEntitlement | null {
    return this.billingCache
  }

  async getCreditUsage(): Promise<BillingCreditUsage> {
    const response = handleAuthResponse(await fetch(`${API_URL}/api/billing/usage`, {
      headers: getAuthHeaders(),
    }))
    const data = await response.json().catch(() => ({})) as {
      usage?: BillingCreditUsage
      error?: string
    }
    if (!response.ok || !data.usage) {
      throw new Error(data.error || 'Unable to load credit usage')
    }
    return data.usage
  }

  /**
   * Create a Stripe Checkout session (AC1)
   * Calls the backend API which creates the Stripe session.
   */
  async createCheckoutSession(_email: string, options: StripeCheckoutOptions = {}): Promise<StripeCheckoutSession> {
    // Mark checkout as pending
    localStorage.setItem(STRIPE_STORAGE_KEYS.CHECKOUT_PENDING, 'true')

    const response = handleAuthResponse(await fetch(`${API_URL}/api/billing/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({
        plan: options.plan ?? 'professional',
        interval: options.interval ?? 'monthly',
        return_origin: window.location.origin,
      }),
    }))
    const data = await response.json().catch(() => ({})) as {
      session_id?: string
      checkout_url?: string
      error?: string
    }
    if (!response.ok || !data.checkout_url || !data.session_id) {
      localStorage.removeItem(STRIPE_STORAGE_KEYS.CHECKOUT_PENDING)
      throw new Error(data.error || 'Unable to create checkout session')
    }

    return {
      sessionId: data.session_id,
      checkoutUrl: data.checkout_url,
    }
  }

  /**
   * Verify a checkout session after redirect (AC4)
   * Called when user returns from Stripe Checkout
   */
  async verifyCheckoutSession(sessionId: string): Promise<StripeSubscriptionResult> {
    try {
      const billing = await this.getBilling({ fresh: true, sessionId })
      return {
        success: billing.ai_enabled,
        subscriptionId: billing.stripe_subscription_id ?? undefined,
        customerId: billing.stripe_customer_id ?? undefined,
        status: billing.subscription_status as SubscriptionStatus,
        currentPeriodEnd: billing.current_period_end ?? undefined,
        error: billing.ai_enabled ? undefined : billing.reason,
      }
    } finally {
      localStorage.removeItem(STRIPE_STORAGE_KEYS.CHECKOUT_PENDING)
    }
  }

  /**
   * Activate subscription after successful payment (AC4)
   */
  async activateSubscription(result: StripeSubscriptionResult): Promise<void> {
    if (!result.success || !result.subscriptionId) {
      throw new Error('Invalid subscription result')
    }
    if (this.billingCache?.stripe_subscription_id !== result.subscriptionId || this.billingCache.ai_enabled !== true) {
      throw new Error('Subscription is not active')
    }
  }

  /**
   * Check if user has an active Stripe subscription
   */
  hasActiveSubscription(): boolean {
    return this.billingCache?.ai_enabled === true
  }

  /**
   * Check if there's a pending checkout
   */
  hasCheckoutPending(): boolean {
    return localStorage.getItem(STRIPE_STORAGE_KEYS.CHECKOUT_PENDING) === 'true'
  }

  /**
   * Clear pending checkout
   */
  clearCheckoutPending(): void {
    localStorage.removeItem(STRIPE_STORAGE_KEYS.CHECKOUT_PENDING)
  }

  /**
   * Get current subscription info
   */
  getSubscriptionInfo(): {
    subscriptionId: string | null
    customerId: string | null
    status: string | null
    currentPeriodEnd: string | null
  } {
    return {
      subscriptionId: this.billingCache?.stripe_subscription_id ?? null,
      customerId: this.billingCache?.stripe_customer_id ?? null,
      status: this.billingCache?.subscription_status ?? null,
      currentPeriodEnd: this.billingCache?.current_period_end ?? null,
    }
  }

  /**
   * Reset subscription data (for testing)
   */
  resetSubscription(): void {
    this.billingCache = null
    localStorage.removeItem(STRIPE_STORAGE_KEYS.SUBSCRIPTION_ID)
    localStorage.removeItem(STRIPE_STORAGE_KEYS.CUSTOMER_ID)
    localStorage.removeItem(STRIPE_STORAGE_KEYS.SUBSCRIPTION_STATUS)
    localStorage.removeItem(STRIPE_STORAGE_KEYS.CURRENT_PERIOD_END)
    localStorage.removeItem(STRIPE_STORAGE_KEYS.CHECKOUT_PENDING)
    localStorage.removeItem(STRIPE_STORAGE_KEYS.CANCEL_AT_PERIOD_END)
    subscriptionService.resetMockData()
  }

  // ═══════════════════════════════════════════════════════════════════
  // Story 9-4: Subscription Management
  // ═══════════════════════════════════════════════════════════════════

  /**
   * Open Stripe Customer Portal for subscription management (Story 9-4 AC1)
   * Allows user to update payment method, view invoices, cancel subscription
   */
  async openCustomerPortal(): Promise<void> {
    const response = handleAuthResponse(await fetch(`${API_URL}/api/billing/portal`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ return_origin: window.location.origin }),
    }))
    const data = await response.json().catch(() => ({})) as {
      portal_url?: string
      error?: string
    }
    if (!response.ok || !data.portal_url) {
      throw new Error(data.error || 'Unable to open customer portal')
    }

    window.open(data.portal_url, '_blank', 'noopener,noreferrer')
  }

  /**
   * Get invoice list from Stripe (Story 9-4 AC3)
   */
  async getInvoices(): Promise<Invoice[]> {
    const response = handleAuthResponse(await fetch(`${API_URL}/api/billing/invoices`, {
      headers: getAuthHeaders(),
    }))
    const data = await response.json().catch(() => ({})) as {
      invoices?: Array<{
        id: string
        amount: number
        currency: string
        date: string | null
        status: Invoice['status']
        invoice_pdf?: string | null
        hosted_invoice_url?: string | null
        description: string
      }>
      error?: string
    }
    if (!response.ok || !Array.isArray(data.invoices)) {
      throw new Error(data.error || 'Unable to load invoices')
    }
    return data.invoices.map(invoice => ({
      id: invoice.id,
      amount: invoice.amount,
      currency: invoice.currency,
      date: invoice.date ?? '',
      status: invoice.status,
      invoicePdfUrl: invoice.invoice_pdf ?? null,
      hostedInvoiceUrl: invoice.hosted_invoice_url ?? null,
      description: invoice.description,
    }))
  }

  /**
   * Cancel subscription via Stripe portal (Story 9-4 AC4)
   * Opens Stripe portal with cancellation intent
   */
  async cancelSubscription(): Promise<void> {
    if (!this.hasActiveSubscription()) {
      throw new Error('No active subscription to cancel')
    }
    await this.openCustomerPortal()
  }

  /**
   * Get detailed subscription information (Story 9-4 AC5)
   * Returns full subscription details including cancellation status
   */
  async getSubscriptionDetails(): Promise<SubscriptionDetails | null> {
    const response = handleAuthResponse(await fetch(`${API_URL}/api/billing/subscription`, {
      headers: getAuthHeaders(),
    }))
    const data = await response.json().catch(() => ({})) as {
      subscription?: {
        subscription_id: string | null
        customer_id: string | null
        price_id: string | null
        plan: string
        status: string
        current_period_end: string | null
        cancel_at_period_end: boolean
      } | null
      error?: string
    }
    if (!response.ok) {
      throw new Error(data.error || 'Unable to load subscription details')
    }
    if (!data.subscription) {
      return null
    }

    return {
      subscriptionId: data.subscription.subscription_id,
      customerId: data.subscription.customer_id,
      status: data.subscription.status as SubscriptionStatus,
      currentPeriodEnd: data.subscription.current_period_end,
      cancelAtPeriodEnd: data.subscription.cancel_at_period_end,
      plan: data.subscription.plan,
      priceId: data.subscription.price_id,
      pricePerMonth: null,
      currency: null,
    }
  }

  /**
   * Mark subscription as cancelling at period end (Story 9-4 AC5)
   * Called when user confirms cancellation
   */
  markCancelAtPeriodEnd(): void {
    if (this.billingCache) {
      this.billingCache = { ...this.billingCache, cancel_at_period_end: true }
    }
  }
}

// ═══════════════════════════════════════════════════════════════════
// Story 9-5: Usage Limits Enforcement
// ═══════════════════════════════════════════════════════════════════

/**
 * Usage limits storage keys (Story 9-5)
 */
const USAGE_STORAGE_KEYS = {
  DAILY_DRAFT_COUNT: 'agentys_usage_daily_draft_count',
  LAST_RESET_DATE: 'agentys_usage_last_reset_date',
} as const

/**
 * Trial daily draft limit (Story 9-5 AC1)
 */
const TRIAL_DAILY_LIMIT = 10

/**
 * Usage limits interface (Story 9-5 AC3)
 */
export interface UsageLimits {
  /** Daily limit (null = unlimited for premium) */
  dailyLimit: number | null
  /** Number of drafts used today */
  used: number
  /** Remaining drafts (null = unlimited) */
  remaining: number | null
  /** Whether limit has been reached */
  isLimitReached: boolean
  /** Next reset time (UTC midnight) */
  resetTime: string
}

/**
 * Usage limits service for managing daily draft limits (Story 9-5)
 * Trial users: 10 drafts/day (AC1)
 * Premium users: unlimited (AC2)
 * Reset at midnight UTC (AC5)
 */
class UsageLimitsService {
  /**
   * Check if user can generate a draft (AC1, AC2, Story 9-6 AC5)
   * Returns true for premium users, checks limit for trial users
   * Blocks generation if account is suspended due to payment issue
   */
  canGenerateDraft(): boolean {
    // Story 9-6 AC5: Block if account is suspended
    if (this.isAccountSuspended()) {
      return false
    }

    // Premium users: always can (unless suspended)
    if (stripeService.hasActiveSubscription()) {
      return true
    }

    // Check daily reset first
    this.checkAndResetDailyCounter()

    // Trial users: check limit
    const count = this.getDailyDraftCount()
    return count < TRIAL_DAILY_LIMIT
  }

  /**
   * Check if account is suspended due to payment issue (Story 9-6)
   * Note: This is a forward reference to paymentIssueService
   */
  isAccountSuspended(): boolean {
    const isSuspended = localStorage.getItem('agentys_payment_suspended')
    return isSuspended === 'true'
  }

  /**
   * Increment draft count after successful generation
   */
  incrementDraftCount(): void {
    this.checkAndResetDailyCounter()
    const count = this.getDailyDraftCount()
    localStorage.setItem(USAGE_STORAGE_KEYS.DAILY_DRAFT_COUNT, String(count + 1))
  }

  /**
   * Get current daily draft count
   */
  getDailyDraftCount(): number {
    return parseInt(localStorage.getItem(USAGE_STORAGE_KEYS.DAILY_DRAFT_COUNT) || '0', 10)
  }

  /**
   * Check if reset is needed (past UTC midnight) and reset counter (AC5)
   */
  checkAndResetDailyCounter(): void {
    const lastReset = localStorage.getItem(USAGE_STORAGE_KEYS.LAST_RESET_DATE)
    const today = this.getUTCDateString()

    if (lastReset !== today) {
      localStorage.setItem(USAGE_STORAGE_KEYS.DAILY_DRAFT_COUNT, '0')
      localStorage.setItem(USAGE_STORAGE_KEYS.LAST_RESET_DATE, today)
    }
  }

  /**
   * Get current usage limits info (AC3)
   */
  getUsageLimits(): UsageLimits {
    this.checkAndResetDailyCounter()

    const isPremium = stripeService.hasActiveSubscription()
    const used = this.getDailyDraftCount()
    const dailyLimit = isPremium ? null : TRIAL_DAILY_LIMIT
    const remaining = dailyLimit === null ? null : Math.max(0, dailyLimit - used)

    return {
      dailyLimit,
      used,
      remaining,
      isLimitReached: dailyLimit !== null && used >= dailyLimit,
      resetTime: this.getNextResetTime(),
    }
  }

  /**
   * Get time remaining until next reset (for display)
   */
  getTimeUntilReset(): { hours: number; minutes: number } {
    const now = new Date()
    const tomorrow = new Date(Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate() + 1,
      0, 0, 0, 0
    ))
    const diffMs = tomorrow.getTime() - now.getTime()
    const hours = Math.floor(diffMs / (1000 * 60 * 60))
    const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))
    return { hours, minutes }
  }

  /**
   * Get UTC date string (YYYY-MM-DD)
   */
  private getUTCDateString(): string {
    const now = new Date()
    return now.toISOString().split('T')[0]
  }

  /**
   * Get next UTC midnight reset time
   */
  private getNextResetTime(): string {
    const now = new Date()
    const tomorrow = new Date(Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate() + 1,
      0, 0, 0, 0
    ))
    return tomorrow.toISOString()
  }

  /**
   * Reset usage data (for testing)
   */
  resetUsage(): void {
    localStorage.removeItem(USAGE_STORAGE_KEYS.DAILY_DRAFT_COUNT)
    localStorage.removeItem(USAGE_STORAGE_KEYS.LAST_RESET_DATE)
  }
}

// ═══════════════════════════════════════════════════════════════════
// Story 9-6: Payment Issue Notifications
// ═══════════════════════════════════════════════════════════════════

/**
 * Payment issue storage keys (Story 9-6)
 */
const PAYMENT_ISSUE_STORAGE_KEYS = {
  ISSUE_DATE: 'agentys_payment_issue_date',
  REMINDERS_SENT: 'agentys_payment_reminders_sent',
  IS_SUSPENDED: 'agentys_payment_suspended',
} as const

/**
 * Grace period before suspension (Story 9-6 AC3)
 */
const GRACE_PERIOD_DAYS = 7

/**
 * Days to send reminder emails (Story 9-6 AC4)
 */
const REMINDER_DAYS = [1, 3, 6] as const

/**
 * Payment issue status interface (Story 9-6)
 */
export interface PaymentIssueStatus {
  /** Date when payment issue was recorded (ISO string) */
  issueDate: string | null
  /** Days elapsed since issue */
  daysElapsed: number
  /** Days remaining before suspension */
  daysRemaining: number
  /** Days on which reminders were sent */
  remindersSent: number[]
  /** Whether account is in grace period */
  isInGracePeriod: boolean
  /** Whether account is suspended */
  isSuspended: boolean
}

/**
 * Banner severity levels (Story 9-6 AC2)
 */
export type PaymentBannerSeverity = 'warning' | 'critical' | 'suspended'

/**
 * Payment issue service for managing payment failures (Story 9-6)
 * - Grace period of 7 days (AC3)
 * - Reminders at D+1, D+3, D+6 (AC4)
 * - Automatic suspension after D+7 (AC5)
 */
class PaymentIssueService {
  /**
   * Record a payment issue (AC3)
   * Called when Stripe webhook reports payment failure
   */
  recordPaymentIssue(date: Date = new Date()): void {
    const existingDate = localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.ISSUE_DATE)
    if (existingDate) {
      // Issue already recorded, don't overwrite
      return
    }

    const dateStr = date.toISOString()
    localStorage.setItem(PAYMENT_ISSUE_STORAGE_KEYS.ISSUE_DATE, dateStr)
    localStorage.setItem(PAYMENT_ISSUE_STORAGE_KEYS.REMINDERS_SENT, JSON.stringify([]))
    localStorage.setItem(PAYMENT_ISSUE_STORAGE_KEYS.IS_SUSPENDED, 'false')

    devLog(`[PaymentIssue] Payment issue recorded: ${dateStr}`)
  }

  /**
   * Get grace period status (AC3, AC5)
   */
  getGracePeriodStatus(): { daysRemaining: number; isInGracePeriod: boolean; isSuspended: boolean } {
    const issueDate = localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.ISSUE_DATE)
    const isSuspended = localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.IS_SUSPENDED) === 'true'

    if (!issueDate) {
      return { daysRemaining: 0, isInGracePeriod: false, isSuspended: false }
    }

    const elapsed = this.getDaysElapsed(issueDate)
    const remaining = Math.max(0, GRACE_PERIOD_DAYS - elapsed)

    return {
      daysRemaining: remaining,
      isInGracePeriod: remaining > 0 && !isSuspended,
      isSuspended,
    }
  }

  /**
   * Check if a reminder should be sent (AC4)
   * Returns the reminder day (1, 3, or 6) if reminder should be sent, null otherwise
   */
  shouldSendReminder(): number | null {
    const issueDate = localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.ISSUE_DATE)
    if (!issueDate) return null

    // Don't send reminders if suspended
    const isSuspended = localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.IS_SUSPENDED) === 'true'
    if (isSuspended) return null

    const elapsed = this.getDaysElapsed(issueDate)
    const remindersSent = this.getRemindersSent()

    // Check if we should send a reminder for any of the reminder days
    for (const day of REMINDER_DAYS) {
      if (elapsed >= day && !remindersSent.includes(day)) {
        return day
      }
    }

    return null
  }

  /**
   * Mark a reminder as sent (AC4)
   */
  markReminderSent(day: number): void {
    const remindersSent = this.getRemindersSent()
    if (!remindersSent.includes(day)) {
      remindersSent.push(day)
      localStorage.setItem(PAYMENT_ISSUE_STORAGE_KEYS.REMINDERS_SENT, JSON.stringify(remindersSent))
      devLog(`[PaymentIssue] Reminder sent for day ${day}`)
    }
  }

  /**
   * Check if account should be suspended and suspend if needed (AC5)
   * Returns true if account was suspended
   */
  checkAndSuspend(): boolean {
    const issueDate = localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.ISSUE_DATE)
    if (!issueDate) return false

    const isSuspended = localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.IS_SUSPENDED) === 'true'
    if (isSuspended) return false

    const elapsed = this.getDaysElapsed(issueDate)
    if (elapsed >= GRACE_PERIOD_DAYS) {
      localStorage.setItem(PAYMENT_ISSUE_STORAGE_KEYS.IS_SUSPENDED, 'true')
      devLog('[PaymentIssue] Account suspended due to payment issue')

      return true
    }

    return false
  }

  /**
   * Resolve payment issue (when payment succeeds)
   */
  resolvePaymentIssue(): void {
    localStorage.removeItem(PAYMENT_ISSUE_STORAGE_KEYS.ISSUE_DATE)
    localStorage.removeItem(PAYMENT_ISSUE_STORAGE_KEYS.REMINDERS_SENT)
    localStorage.removeItem(PAYMENT_ISSUE_STORAGE_KEYS.IS_SUSPENDED)

    devLog('[PaymentIssue] Payment issue resolved')
  }

  /**
   * Get full payment issue status
   */
  getPaymentIssueStatus(): PaymentIssueStatus {
    const issueDate = localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.ISSUE_DATE)
    const isSuspended = localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.IS_SUSPENDED) === 'true'
    const remindersSent = this.getRemindersSent()

    if (!issueDate) {
      return {
        issueDate: null,
        daysElapsed: 0,
        daysRemaining: GRACE_PERIOD_DAYS,
        remindersSent: [],
        isInGracePeriod: false,
        isSuspended: false,
      }
    }

    const daysElapsed = this.getDaysElapsed(issueDate)
    const daysRemaining = Math.max(0, GRACE_PERIOD_DAYS - daysElapsed)

    return {
      issueDate,
      daysElapsed,
      daysRemaining,
      remindersSent,
      isInGracePeriod: daysRemaining > 0 && !isSuspended,
      isSuspended,
    }
  }

  /**
   * Get banner severity based on days elapsed (AC2)
   */
  getBannerSeverity(): PaymentBannerSeverity | null {
    const { issueDate, daysElapsed, isSuspended } = this.getPaymentIssueStatus()

    if (!issueDate) return null
    if (isSuspended) return 'suspended'
    if (daysElapsed >= 4) return 'critical' // D4-D6
    return 'warning' // D1-D3
  }

  /**
   * Check if there's an active payment issue
   */
  hasPaymentIssue(): boolean {
    return localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.ISSUE_DATE) !== null
  }

  /**
   * Check if account is currently suspended
   */
  isAccountSuspended(): boolean {
    return localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.IS_SUSPENDED) === 'true'
  }

  /**
   * Get days elapsed since issue date
   */
  private getDaysElapsed(issueDateStr: string): number {
    const issueDate = new Date(issueDateStr)
    const now = new Date()
    const diffTime = now.getTime() - issueDate.getTime()
    return Math.floor(diffTime / (1000 * 60 * 60 * 24))
  }

  /**
   * Get list of reminder days that have been sent
   */
  private getRemindersSent(): number[] {
    const stored = localStorage.getItem(PAYMENT_ISSUE_STORAGE_KEYS.REMINDERS_SENT)
    if (!stored) return []
    try {
      return JSON.parse(stored)
    } catch {
      return []
    }
  }

  /**
   * Reset payment issue data (for testing)
   */
  resetPaymentIssue(): void {
    localStorage.removeItem(PAYMENT_ISSUE_STORAGE_KEYS.ISSUE_DATE)
    localStorage.removeItem(PAYMENT_ISSUE_STORAGE_KEYS.REMINDERS_SENT)
    localStorage.removeItem(PAYMENT_ISSUE_STORAGE_KEYS.IS_SUSPENDED)
  }
}

/**
 * Payment notification service for email alerts (Story 9-6 AC1, AC4)
 * Mock implementation - will be connected to real email service
 */
class PaymentNotificationService {
  /**
   * Send initial payment failed email (AC1)
   */
  async sendPaymentFailedEmail(email: string): Promise<void> {
    devLog(`[PaymentNotification] Payment failed email sent to ${email}`)
    devLog(`[PaymentNotification] Content: Your payment has failed.
        Please update your payment information within 7 days
        to avoid account suspension.`)
    // TODO: Connect to real email service
  }

  /**
   * Send reminder email (AC4)
   * @param email User email
   * @param day Reminder day (1, 3, or 6)
   */
  async sendReminderEmail(email: string, day: number): Promise<void> {
    const daysRemaining = GRACE_PERIOD_DAYS - day
    const urgency = day === 6 ? 'URGENT: ' : ''

    devLog(`[PaymentNotification] Reminder D+${day} sent to ${email}`)
    devLog(`[PaymentNotification] Content: ${urgency}You have ${daysRemaining} day(s) remaining
        to update your payment information.`)
    // TODO: Connect to real email service
  }

  /**
   * Send suspension email (AC5)
   */
  async sendSuspensionEmail(email: string): Promise<void> {
    devLog(`[PaymentNotification] Suspension email sent to ${email}`)
    devLog(`[PaymentNotification] Content: Your Agentys subscription has been suspended
        due to a payment issue. Update your payment information
        to reactivate your account.`)
    // TODO: Connect to real email service
  }
}

/**
 * Singleton instance of the subscription service
 */
export const subscriptionService = new SubscriptionService()

/**
 * Singleton instance of the trial service (Story 9-1)
 */
export const trialService = new TrialService()

/**
 * Singleton instance of the Stripe service (Story 9-2)
 */
export const stripeService = new StripeService()

/**
 * Singleton instance of the usage limits service (Story 9-5)
 */
export const usageLimitsService = new UsageLimitsService()

/**
 * Singleton instance of the payment issue service (Story 9-6)
 */
export const paymentIssueService = new PaymentIssueService()

/**
 * Singleton instance of the payment notification service (Story 9-6)
 */
export const paymentNotificationService = new PaymentNotificationService()

// ═══════════════════════════════════════════════════════════════════
// Story 9-7: Referral Link System
// ═══════════════════════════════════════════════════════════════════

/**
 * Referral storage keys (Story 9-7)
 */
const REFERRAL_STORAGE_KEYS = {
  REFERRAL_CODE: 'agentys_referral_code',
  REFERRALS_COUNT: 'agentys_referrals_count',
} as const

/**
 * Referral stats interface (Story 9-7 AC1, AC5)
 */
export interface ReferralStats {
  /** User's unique referral code */
  code: string
  /** Full referral link URL */
  link: string
  /** Number of users who signed up via this link */
  referralsCount: number
}

/**
 * Referral service for managing referral links (Story 9-7)
 * - Unique code per user (AC1)
 * - Tracking signups (AC5)
 */
class ReferralService {
  /**
   * Generate a unique referral code from user email (AC1)
   * Uses simple base64 encoding of email for uniqueness
   */
  generateReferralCode(email: string): string {
    if (!email) {
      throw new Error('Email is required to generate referral code')
    }

    // Check if code already exists
    const existingCode = localStorage.getItem(REFERRAL_STORAGE_KEYS.REFERRAL_CODE)
    if (existingCode) {
      return existingCode
    }

    // Generate new code from email hash
    // Use first 8 chars of base64 encoded email, uppercase alphanumeric only
    const hash = btoa(email).replace(/[^a-zA-Z0-9]/g, '').substring(0, 8).toUpperCase()

    localStorage.setItem(REFERRAL_STORAGE_KEYS.REFERRAL_CODE, hash)
    localStorage.setItem(REFERRAL_STORAGE_KEYS.REFERRALS_COUNT, '0')

    devLog(`[Referral] Generated code for ${email}: ${hash}`)

    return hash
  }

  /**
   * Get referral code (generate if needed from trial email)
   */
  getReferralCode(): string | null {
    const existingCode = localStorage.getItem(REFERRAL_STORAGE_KEYS.REFERRAL_CODE)
    if (existingCode) {
      return existingCode
    }

    // Try to generate from trial email
    const { email } = trialService.getTrialStatus()
    if (email) {
      return this.generateReferralCode(email)
    }

    return null
  }

  /**
   * Get full referral link URL (AC1)
   */
  getReferralLink(): string | null {
    const code = this.getReferralCode()
    if (!code) {
      return null
    }

    return `https://agentys.app/signup?ref=${code}`
  }

  /**
   * Active le programme ambassadeur côté serveur (crée le coupon + promotion
   * code Stripe) et renvoie le code/lien réels. Remplace le code localStorage
   * du MVP : le serveur devient la source de vérité du parrainage.
   */
  async activateAmbassador(): Promise<ReferralStats> {
    const response = handleAuthResponse(await fetch(`${API_URL}/api/ambassador/activate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    }))
    const data = await response.json().catch(() => ({})) as {
      code?: string
      referral_link?: string
      status?: string
      error?: string
    }
    if (!response.ok || !data.code || !data.referral_link) {
      throw new Error(data.error || 'Unable to activate ambassador program')
    }

    // Persiste le code serveur pour l'affichage hors-ligne (getReferralStats).
    localStorage.setItem(REFERRAL_STORAGE_KEYS.REFERRAL_CODE, data.code)
    const storedCount = localStorage.getItem(REFERRAL_STORAGE_KEYS.REFERRALS_COUNT) ?? '0'
    return {
      code: data.code,
      link: data.referral_link,
      referralsCount: parseInt(storedCount, 10) || 0,
    }
  }

  /**
   * Track a referral signup (AC5)
   * Called when someone signs up via a referral link
   * Mock implementation for MVP
   */
  trackReferral(code: string): void {
    // In production, this would be handled by backend
    // For MVP, we track locally for the referrer
    const myCode = localStorage.getItem(REFERRAL_STORAGE_KEYS.REFERRAL_CODE)
    if (myCode === code) {
      const currentCount = this.getReferralsCount()
      localStorage.setItem(REFERRAL_STORAGE_KEYS.REFERRALS_COUNT, String(currentCount + 1))
      devLog(`[Referral] Tracked referral for code ${code}, new count: ${currentCount + 1}`)
    }
  }

  /**
   * Get number of referrals (AC5)
   */
  getReferralsCount(): number {
    return parseInt(localStorage.getItem(REFERRAL_STORAGE_KEYS.REFERRALS_COUNT) || '0', 10)
  }

  /**
   * Get full referral stats (AC1, AC5)
   */
  getReferralStats(): ReferralStats | null {
    const code = this.getReferralCode()
    if (!code) {
      return null
    }

    return {
      code,
      link: `https://agentys.app/signup?ref=${code}`,
      referralsCount: this.getReferralsCount(),
    }
  }

  /**
   * Reset referral data (for testing)
   */
  resetReferral(): void {
    localStorage.removeItem(REFERRAL_STORAGE_KEYS.REFERRAL_CODE)
    localStorage.removeItem(REFERRAL_STORAGE_KEYS.REFERRALS_COUNT)
  }
}

/**
 * Usage stats storage keys (Story 9-7)
 */
const USAGE_STATS_STORAGE_KEYS = {
  EMAILS_PROCESSED: 'agentys_stats_emails_processed',
  DRAFTS_GENERATED: 'agentys_stats_drafts_generated',
  MONTHLY_RESET_DATE: 'agentys_stats_monthly_reset',
} as const

/**
 * Monthly stats interface (Story 9-7 AC3)
 */
export interface MonthlyStats {
  /** Number of emails processed this month */
  emailsProcessed: number
  /** Number of drafts generated this month */
  draftsGenerated: number
  /** Estimated time saved in minutes (draftsGenerated * 5) */
  timeSavedMinutes: number
  /** Start of current period (ISO date) */
  periodStart: string
}

/**
 * Time saved per draft in minutes (average time to write email manually)
 */
const MINUTES_SAVED_PER_DRAFT = 5

/**
 * Usage stats service for tracking productivity (Story 9-7 AC3)
 * - Tracks emails processed and drafts generated
 * - Calculates time saved
 * - Resets monthly
 */
class UsageStatsService {
  /**
   * Record an email as processed
   */
  recordEmailProcessed(): void {
    this.checkAndResetMonthly()
    const count = this.getEmailsProcessed()
    localStorage.setItem(USAGE_STATS_STORAGE_KEYS.EMAILS_PROCESSED, String(count + 1))
  }

  /**
   * Record a draft as generated
   */
  recordDraftGenerated(): void {
    this.checkAndResetMonthly()
    const count = this.getDraftsGenerated()
    localStorage.setItem(USAGE_STATS_STORAGE_KEYS.DRAFTS_GENERATED, String(count + 1))
  }

  /**
   * Get number of emails processed this month
   */
  getEmailsProcessed(): number {
    this.checkAndResetMonthly()
    return parseInt(localStorage.getItem(USAGE_STATS_STORAGE_KEYS.EMAILS_PROCESSED) || '0', 10)
  }

  /**
   * Get number of drafts generated this month
   */
  getDraftsGenerated(): number {
    this.checkAndResetMonthly()
    return parseInt(localStorage.getItem(USAGE_STATS_STORAGE_KEYS.DRAFTS_GENERATED) || '0', 10)
  }

  /**
   * Get monthly stats (AC3)
   */
  getMonthlyStats(): MonthlyStats {
    this.checkAndResetMonthly()

    const emailsProcessed = this.getEmailsProcessed()
    const draftsGenerated = this.getDraftsGenerated()
    const timeSavedMinutes = draftsGenerated * MINUTES_SAVED_PER_DRAFT

    return {
      emailsProcessed,
      draftsGenerated,
      timeSavedMinutes,
      periodStart: this.getMonthStart(),
    }
  }

  /**
   * Get time saved formatted as hours and minutes
   */
  getTimeSavedFormatted(): string {
    const { timeSavedMinutes } = this.getMonthlyStats()
    const hours = Math.floor(timeSavedMinutes / 60)
    const minutes = timeSavedMinutes % 60

    if (hours === 0) {
      return `${minutes} min`
    }

    return `${hours}h${minutes > 0 ? minutes.toString().padStart(2, '0') : ''}`
  }

  /**
   * Check if we need to reset for new month
   * If resetting, saves a snapshot of the previous month first (Story 9-8)
   */
  checkAndResetMonthly(): void {
    const lastReset = localStorage.getItem(USAGE_STATS_STORAGE_KEYS.MONTHLY_RESET_DATE)
    const currentMonthStart = this.getMonthStart()

    if (lastReset && lastReset !== currentMonthStart) {
      // Save snapshot of previous month before resetting (Story 9-8)
      this.saveSnapshotBeforeReset(lastReset)
      this.resetMonthlyStats()
    } else if (!lastReset) {
      // First time initialization
      this.resetMonthlyStats()
    }
  }

  /**
   * Save a snapshot of the current stats before resetting (Story 9-8)
   */
  private saveSnapshotBeforeReset(monthStart: string): void {
    const emailsProcessed = parseInt(localStorage.getItem(USAGE_STATS_STORAGE_KEYS.EMAILS_PROCESSED) || '0', 10)
    const draftsGenerated = parseInt(localStorage.getItem(USAGE_STATS_STORAGE_KEYS.DRAFTS_GENERATED) || '0', 10)

    // Only save if there's data
    if (emailsProcessed > 0 || draftsGenerated > 0) {
      // Extract month from monthStart (YYYY-MM-01 -> YYYY-MM)
      const month = monthStart.substring(0, 7)

      // Import and use monthlySummaryService (avoid circular dependency by using direct localStorage)
      const historyKey = 'agentys_monthly_history'
      const stored = localStorage.getItem(historyKey)
      const history = stored ? JSON.parse(stored) : []

      const snapshot = {
        month,
        emailsProcessed,
        draftsGenerated,
        timeSavedMinutes: draftsGenerated * MINUTES_SAVED_PER_DRAFT,
      }

      // Check if we already have this month
      const existingIndex = history.findIndex((h: { month: string }) => h.month === month)
      if (existingIndex >= 0) {
        history[existingIndex] = snapshot
      } else {
        history.push(snapshot)
      }

      // Keep only last 12 months
      const trimmed = history.slice(-12)
      localStorage.setItem(historyKey, JSON.stringify(trimmed))
      devLog(`[UsageStats] Archived snapshot for ${month}`)
    }
  }

  /**
   * Reset monthly stats
   */
  resetMonthlyStats(): void {
    const currentMonthStart = this.getMonthStart()
    localStorage.setItem(USAGE_STATS_STORAGE_KEYS.EMAILS_PROCESSED, '0')
    localStorage.setItem(USAGE_STATS_STORAGE_KEYS.DRAFTS_GENERATED, '0')
    localStorage.setItem(USAGE_STATS_STORAGE_KEYS.MONTHLY_RESET_DATE, currentMonthStart)
  }

  /**
   * Get start of current month (YYYY-MM-01)
   */
  private getMonthStart(): string {
    const now = new Date()
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`
  }

  /**
   * Reset stats data (for testing)
   */
  resetStats(): void {
    localStorage.removeItem(USAGE_STATS_STORAGE_KEYS.EMAILS_PROCESSED)
    localStorage.removeItem(USAGE_STATS_STORAGE_KEYS.DRAFTS_GENERATED)
    localStorage.removeItem(USAGE_STATS_STORAGE_KEYS.MONTHLY_RESET_DATE)
  }
}

/**
 * Singleton instance of the referral service (Story 9-7)
 */
export const referralService = new ReferralService()

/**
 * Singleton instance of the usage stats service (Story 9-7)
 */
export const usageStatsService = new UsageStatsService()

// ============================================================================
// MONTHLY SUMMARY SERVICE (Story 9-8)
// ============================================================================

/**
 * Monthly summary storage keys (Story 9-8)
 */
const MONTHLY_SUMMARY_STORAGE_KEYS = {
  MONTHLY_HISTORY: 'agentys_monthly_history',
} as const

/**
 * Monthly snapshot interface (Story 9-8)
 */
export interface MonthlySnapshot {
  /** Month in YYYY-MM format */
  month: string
  /** Number of emails processed */
  emailsProcessed: number
  /** Number of drafts generated */
  draftsGenerated: number
  /** Estimated time saved in minutes */
  timeSavedMinutes: number
}

/**
 * Monthly comparison interface (Story 9-8 AC2)
 */
export interface MonthlyComparison {
  current: MonthlySnapshot
  previous: MonthlySnapshot | null
  /** Percentage change in emails processed */
  emailsChange: number | null
  /** Percentage change in drafts generated */
  draftsChange: number | null
  /** Percentage change in time saved */
  timeChange: number | null
}

/**
 * Monthly summary service for historical data and comparisons (Story 9-8)
 * - Maintains history of last 12 months
 * - Provides comparison with previous month
 * - Generates shareable summary
 */
class MonthlySummaryService {
  /**
   * Get current month in YYYY-MM format
   */
  private getCurrentMonth(): string {
    const now = new Date()
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  }

  /**
   * Get previous month in YYYY-MM format
   */
  private getPreviousMonth(): string {
    const now = new Date()
    now.setMonth(now.getMonth() - 1)
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  }

  /**
   * Get month label (e.g., "January 2026")
   */
  getMonthLabel(month: string): string {
    const [year, monthNum] = month.split('-')
    const monthNames = [
      'January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December'
    ]
    return `${monthNames[parseInt(monthNum, 10) - 1]} ${year}`
  }

  /**
   * Get monthly history from storage
   */
  getHistory(): MonthlySnapshot[] {
    const stored = localStorage.getItem(MONTHLY_SUMMARY_STORAGE_KEYS.MONTHLY_HISTORY)
    if (!stored) return []
    try {
      return JSON.parse(stored)
    } catch {
      return []
    }
  }

  /**
   * Save monthly history to storage
   */
  private saveHistory(history: MonthlySnapshot[]): void {
    // Keep only last 12 months
    const trimmed = history.slice(-12)
    localStorage.setItem(MONTHLY_SUMMARY_STORAGE_KEYS.MONTHLY_HISTORY, JSON.stringify(trimmed))
  }

  /**
   * Save a monthly snapshot (called at month end)
   */
  saveMonthlySnapshot(snapshot: MonthlySnapshot): void {
    const history = this.getHistory()

    // Check if we already have this month
    const existingIndex = history.findIndex(h => h.month === snapshot.month)
    if (existingIndex >= 0) {
      history[existingIndex] = snapshot
    } else {
      history.push(snapshot)
    }

    this.saveHistory(history)
    devLog(`[MonthlySummary] Saved snapshot for ${snapshot.month}`)
  }

  /**
   * Get current month stats as a snapshot (AC1)
   */
  getCurrentMonthStats(): MonthlySnapshot {
    const stats = usageStatsService.getMonthlyStats()
    return {
      month: this.getCurrentMonth(),
      emailsProcessed: stats.emailsProcessed,
      draftsGenerated: stats.draftsGenerated,
      timeSavedMinutes: stats.timeSavedMinutes,
    }
  }

  /**
   * Get previous month stats from history (AC2)
   */
  getPreviousMonthStats(): MonthlySnapshot | null {
    const history = this.getHistory()
    const previousMonth = this.getPreviousMonth()
    return history.find(h => h.month === previousMonth) || null
  }

  /**
   * Calculate percentage change
   */
  private calculateChange(current: number, previous: number): number | null {
    if (previous === 0) {
      return current > 0 ? 100 : null
    }
    return Math.round(((current - previous) / previous) * 100)
  }

  /**
   * Get comparison with previous month (AC2)
   */
  getComparison(): MonthlyComparison {
    const current = this.getCurrentMonthStats()
    const previous = this.getPreviousMonthStats()

    return {
      current,
      previous,
      emailsChange: previous ? this.calculateChange(current.emailsProcessed, previous.emailsProcessed) : null,
      draftsChange: previous ? this.calculateChange(current.draftsGenerated, previous.draftsGenerated) : null,
      timeChange: previous ? this.calculateChange(current.timeSavedMinutes, previous.timeSavedMinutes) : null,
    }
  }

  /**
   * Get last N months for chart (AC3)
   */
  getChartData(months: number = 6): MonthlySnapshot[] {
    const history = this.getHistory()
    const current = this.getCurrentMonthStats()

    // Add current month if not in history
    const currentMonth = this.getCurrentMonth()
    const allData = history.some(h => h.month === currentMonth)
      ? history
      : [...history, current]

    return allData.slice(-months)
  }

  /**
   * Generate share message with stats and referral link (AC4)
   */
  getShareMessage(): string {
    const stats = this.getCurrentMonthStats()
    const timeSaved = usageStatsService.getTimeSavedFormatted()
    const referralLink = referralService.getReferralLink() || 'https://agentys.app'

    return `🚀 My month with Agentys:
📧 ${stats.emailsProcessed} emails processed
✍️ ${stats.draftsGenerated} drafts generated
⏱️ ~${timeSaved} of time saved!

Try it for free: ${referralLink}`
  }

  /**
   * Reset history (for testing)
   */
  resetHistory(): void {
    localStorage.removeItem(MONTHLY_SUMMARY_STORAGE_KEYS.MONTHLY_HISTORY)
  }
}

/**
 * Singleton instance of the monthly summary service (Story 9-8)
 */
export const monthlySummaryService = new MonthlySummaryService()
