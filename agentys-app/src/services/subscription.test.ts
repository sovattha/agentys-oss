import { beforeEach, describe, expect, it, vi } from 'vitest'

import { canUseVoiceDictation, stripeService } from './subscription'

describe('canUseVoiceDictation', () => {
  it('blocks the pure free plan', () => {
    expect(canUseVoiceDictation({
      plan: 'free',
      subscription_status: 'none',
      ai_enabled: false,
    })).toBe(false)
  })

  it('allows Stripe free-trial status even when paid AI is not enabled', () => {
    expect(canUseVoiceDictation({
      plan: 'free',
      subscription_status: 'trialing',
      ai_enabled: false,
    })).toBe(true)
  })

  it('allows legacy trial plan snapshots', () => {
    expect(canUseVoiceDictation({
      plan: 'trial',
      subscription_status: 'active',
      ai_enabled: false,
    })).toBe(true)
  })

  it('blocks expired trial snapshots', () => {
    expect(canUseVoiceDictation({
      plan: 'trial',
      subscription_status: 'expired',
      ai_enabled: false,
    })).toBe(false)
  })

  it('keeps local/dev sessions without billing data usable', () => {
    expect(canUseVoiceDictation({})).toBe(true)
    expect(canUseVoiceDictation(null)).toBe(true)
  })
})

describe('stripeService billing API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    localStorage.clear()
    stripeService.resetSubscription()
  })

  it('loads backend billing entitlement with auth headers', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      billing: {
        plan: 'professional',
        subscription_status: 'active',
        ai_enabled: true,
        reason: 'active',
        usage_billing_enabled: true,
        limits: {
          deepgram_minutes_per_day: 20,
          deepgram_active_days_per_month: 20,
          deepgram_minutes_per_month: 400,
          llm_monthly_budget_usd: 7,
        },
      },
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const billing = await stripeService.getBilling()

    expect(billing.ai_enabled).toBe(true)
    expect(billing.usage_billing_enabled).toBe(true)
    expect(billing.limits).toMatchObject({
      deepgram_minutes_per_day: 20,
      deepgram_active_days_per_month: 20,
      deepgram_minutes_per_month: 400,
      llm_monthly_budget_usd: 7,
    })
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/billing\/me$/), {
      headers: expect.objectContaining({
        Authorization: 'Bearer jwt_test',
      }),
    })
  })

  it('loads LLM credit usage with auth headers', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      usage: {
        llm: {
          included_credits: 350,
          used_credits: 42,
          remaining_credits: 308,
          overage_credits: 0,
          resets_at: '2026-07-01T00:00:00+00:00',
          usage_billing_enabled: false,
        },
        dictation: {
          included_credits: 10,
          used_credits: 3,
          remaining_credits: 7,
          overage_credits: 0,
          resets_at: '2026-06-10T00:00:00+00:00',
          window: 'day',
        },
      },
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const usage = await stripeService.getCreditUsage()

    expect(usage.llm).toMatchObject({
      included_credits: 350,
      used_credits: 42,
      remaining_credits: 308,
      overage_credits: 0,
    })
    expect(usage.dictation).toMatchObject({
      included_credits: 10,
      used_credits: 3,
      remaining_credits: 7,
      window: 'day',
    })
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/billing\/usage$/), {
      headers: expect.objectContaining({
        Authorization: 'Bearer jwt_test',
      }),
    })
  })

  it('requests fresh billing reconciliation when asked', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      billing: {
        plan: 'free',
        subscription_status: 'canceled',
        ai_enabled: false,
        reason: 'subscription_canceled',
      },
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await stripeService.getBilling({ fresh: true })

    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/billing\/me\?fresh=true$/), {
      headers: expect.objectContaining({
        Authorization: 'Bearer jwt_test',
      }),
    })
  })

  it('passes the checkout session id when reconciling a Stripe return', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      billing: {
        plan: 'professional',
        subscription_status: 'active',
        ai_enabled: true,
        reason: 'active',
      },
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await stripeService.getBilling({ fresh: true, sessionId: 'cs_test_123' })

    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/billing\/me\?fresh=true&session_id=cs_test_123$/), {
      headers: expect.objectContaining({
        Authorization: 'Bearer jwt_test',
      }),
    })
  })

  it('verifies checkout sessions through backend billing reconciliation', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    localStorage.setItem('agentys_stripe_checkout_pending', 'true')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      billing: {
        plan: 'professional',
        subscription_status: 'active',
        ai_enabled: true,
        reason: 'active',
        stripe_customer_id: 'cus_real',
        stripe_subscription_id: 'sub_real',
        current_period_end: '2026-07-01T00:00:00Z',
      },
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await stripeService.verifyCheckoutSession('cs_test_real')

    expect(result).toMatchObject({
      success: true,
      customerId: 'cus_real',
      subscriptionId: 'sub_real',
      status: 'active',
      currentPeriodEnd: '2026-07-01T00:00:00Z',
    })
    expect(localStorage.getItem('agentys_stripe_checkout_pending')).toBeNull()
    expect(localStorage.getItem('agentys_stripe_subscription_id')).toBeNull()
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/billing\/me\?fresh=true&session_id=cs_test_real$/), {
      headers: expect.objectContaining({
        Authorization: 'Bearer jwt_test',
      }),
    })
  })

  it('does not trust legacy Stripe localStorage as an active subscription', () => {
    localStorage.setItem('agentys_stripe_subscription_status', 'active')
    localStorage.setItem('agentys_stripe_current_period_end', new Date(Date.now() + 86_400_000).toISOString())

    expect(stripeService.hasActiveSubscription()).toBe(false)
  })

  it('uses the backend billing entitlement cache for active subscription checks', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      billing: {
        plan: 'professional',
        subscription_status: 'active',
        ai_enabled: true,
        reason: 'active',
      },
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await stripeService.getBilling()

    expect(stripeService.hasActiveSubscription()).toBe(true)
  })

  it('lets backend free billing override legacy active localStorage', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    localStorage.setItem('agentys_stripe_subscription_status', 'active')
    localStorage.setItem('agentys_stripe_current_period_end', new Date(Date.now() + 86_400_000).toISOString())
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      billing: {
        plan: 'free',
        subscription_status: 'none',
        ai_enabled: false,
        reason: 'no_active_subscription',
      },
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await stripeService.getBilling()

    expect(stripeService.hasActiveSubscription()).toBe(false)
  })

  it('creates checkout sessions through the backend with the selected plan', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      session_id: 'cs_test_123',
      checkout_url: 'https://checkout.stripe.com/c/pay/cs_test_123',
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const checkout = await stripeService.createCheckoutSession('', {
      plan: 'starter',
      interval: 'yearly',
    })

    expect(checkout.checkoutUrl).toBe('https://checkout.stripe.com/c/pay/cs_test_123')
    expect(localStorage.getItem('agentys_stripe_checkout_pending')).toBe('true')
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/billing\/checkout$/), expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        Authorization: 'Bearer jwt_test',
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify({
        plan: 'starter',
        interval: 'yearly',
        return_origin: window.location.origin,
      }),
    }))
  })

  it('clears pending checkout when the backend rejects checkout creation', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: 'STRIPE_PRICE_STARTER_MONTHLY is missing',
    }), { status: 503 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(stripeService.createCheckoutSession('', {
      plan: 'starter',
      interval: 'monthly',
    })).rejects.toThrow('STRIPE_PRICE_STARTER_MONTHLY is missing')

    expect(localStorage.getItem('agentys_stripe_checkout_pending')).toBeNull()
  })

  it('loads invoices from the backend billing API', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      invoices: [
        {
          id: 'in_real',
          amount: 2500,
          currency: 'eur',
          date: '2026-06-01T00:00:00+00:00',
          status: 'paid',
          invoice_pdf: 'https://pay.stripe.test/in_real.pdf',
          hosted_invoice_url: 'https://pay.stripe.test/in_real',
          description: 'Agentys Professional',
        },
      ],
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const invoices = await stripeService.getInvoices()

    expect(invoices).toEqual([{
      id: 'in_real',
      amount: 2500,
      currency: 'eur',
      date: '2026-06-01T00:00:00+00:00',
      status: 'paid',
      invoicePdfUrl: 'https://pay.stripe.test/in_real.pdf',
      hostedInvoiceUrl: 'https://pay.stripe.test/in_real',
      description: 'Agentys Professional',
    }])
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/billing\/invoices$/), {
      headers: expect.objectContaining({
        Authorization: 'Bearer jwt_test',
      }),
    })
  })

  it('loads subscription details from the backend billing API', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    localStorage.setItem('agentys_stripe_subscription_id', 'sub_legacy')
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      subscription: {
        subscription_id: 'sub_real',
        customer_id: 'cus_real',
        price_id: 'price_professional_m',
        plan: 'professional',
        status: 'active',
        current_period_end: '2026-07-01T00:00:00+00:00',
        cancel_at_period_end: true,
      },
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const details = await stripeService.getSubscriptionDetails()

    expect(details).toEqual({
      subscriptionId: 'sub_real',
      customerId: 'cus_real',
      priceId: 'price_professional_m',
      plan: 'professional',
      status: 'active',
      currentPeriodEnd: '2026-07-01T00:00:00+00:00',
      cancelAtPeriodEnd: true,
      pricePerMonth: null,
      currency: null,
    })
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/billing\/subscription$/), {
      headers: expect.objectContaining({
        Authorization: 'Bearer jwt_test',
      }),
    })
  })

  it('returns null when backend has no subscription details', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      subscription: null,
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(stripeService.getSubscriptionDetails()).resolves.toBeNull()
  })

  it('opens the backend customer portal when canceling an active subscription', async () => {
    localStorage.setItem('agentys_jwt', 'jwt_test')
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        billing: {
          plan: 'professional',
          subscription_status: 'active',
          ai_enabled: true,
          reason: 'active',
          stripe_customer_id: 'cus_real',
          stripe_subscription_id: 'sub_real',
        },
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        portal_url: 'https://billing.stripe.test/session',
      }), { status: 200 }))
    const openMock = vi.spyOn(window, 'open').mockImplementation(() => null)
    vi.stubGlobal('fetch', fetchMock)

    await stripeService.getBilling()
    await stripeService.cancelSubscription()

    expect(fetchMock).toHaveBeenLastCalledWith(expect.stringMatching(/\/api\/billing\/portal$/), expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        Authorization: 'Bearer jwt_test',
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify({ return_origin: window.location.origin }),
    }))
    expect(openMock).toHaveBeenCalledWith('https://billing.stripe.test/session', '_blank', 'noopener,noreferrer')
  })
})
