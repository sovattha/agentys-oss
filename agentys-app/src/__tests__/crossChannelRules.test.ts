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
 * Cross-Channel Rules Service Tests
 *
 * Tests for the cross-channel rules system that allows:
 * - VIP contacts to trigger immediate notifications
 * - Newsletter detection and auto-ignore
 * - Urgent keywords to prioritize messages
 * - Cross-channel actions (e.g., VIP email → Telegram notification)
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/currentAccountId', () => ({
  getCurrentAccountId: () => 'test-account',
  subscribeCurrentAccountId: () => () => {},
  ensureCurrentAccountId: async () => 'test-account',
  isCurrentAccountLoaded: () => true,
}))

import {
  type CrossChannelRule,
  type RuleCondition,
  createCrossChannelRulesService,
  evaluateRule,
  matchesCondition,
} from '../services/crossChannelRules'

const RULES_STORAGE_KEY = 'agentys_cross_channel_rules:test-account'

const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key]
    }),
    clear: vi.fn(() => {
      store = {}
    }),
  }
})()

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock })

describe('crossChannelRules', () => {
  beforeEach(() => {
    localStorageMock.clear()
    vi.clearAllMocks()
  })
  describe('matchesCondition', () => {
    it('should match VIP sender by email', () => {
      const condition: RuleCondition = {
        type: 'vip_sender',
        value: 'boss@company.com',
      }
      const message = {
        sender: 'boss@company.com',
        subject: 'Hello',
        content: 'Meeting tomorrow',
        channel: 'email' as const,
      }
      expect(matchesCondition(condition, message)).toBe(true)
    })

    it('should not match non-VIP sender', () => {
      const condition: RuleCondition = {
        type: 'vip_sender',
        value: 'boss@company.com',
      }
      const message = {
        sender: 'random@other.com',
        subject: 'Hello',
        content: 'Spam',
        channel: 'email' as const,
      }
      expect(matchesCondition(condition, message)).toBe(false)
    })

    it('should match urgent keyword in subject', () => {
      const condition: RuleCondition = {
        type: 'keyword',
        value: 'URGENT',
        field: 'subject',
      }
      const message = {
        sender: 'someone@example.com',
        subject: '[URGENT] Please review',
        content: 'Details...',
        channel: 'email' as const,
      }
      expect(matchesCondition(condition, message)).toBe(true)
    })

    it('should match keyword case-insensitively', () => {
      const condition: RuleCondition = {
        type: 'keyword',
        value: 'urgent',
        field: 'subject',
      }
      const message = {
        sender: 'someone@example.com',
        subject: 'URGENT: Action required',
        content: 'Details...',
        channel: 'email' as const,
      }
      expect(matchesCondition(condition, message)).toBe(true)
    })

    it('should detect newsletter patterns', () => {
      const condition: RuleCondition = {
        type: 'newsletter',
      }
      const message = {
        sender: 'noreply@newsletter.company.com',
        subject: 'Weekly digest - Unsubscribe here',
        content: 'Click to unsubscribe',
        channel: 'email' as const,
      }
      expect(matchesCondition(condition, message)).toBe(true)
    })

    it('should not match normal email as newsletter', () => {
      const condition: RuleCondition = {
        type: 'newsletter',
      }
      const message = {
        sender: 'colleague@company.com',
        subject: 'Project update',
        content: 'Here is the latest version',
        channel: 'email' as const,
      }
      expect(matchesCondition(condition, message)).toBe(false)
    })

    it('should match sender domain', () => {
      const condition: RuleCondition = {
        type: 'sender_domain',
        value: 'company.com',
      }
      const message = {
        sender: 'anyone@company.com',
        subject: 'Hello',
        content: 'Content',
        channel: 'email' as const,
      }
      expect(matchesCondition(condition, message)).toBe(true)
    })

    it('should match source channel', () => {
      const condition: RuleCondition = {
        type: 'source_channel',
        value: 'discord',
      }
      const message = {
        sender: 'user123',
        subject: 'Discord message',
        content: 'Hello from Discord',
        channel: 'discord' as const,
      }
      expect(matchesCondition(condition, message)).toBe(true)
    })
  })

  describe('evaluateRule', () => {
    it('should return action when all conditions match (AND)', () => {
      const rule: CrossChannelRule = {
        id: 'rule-1',
        name: 'VIP from company',
        conditions: [
          { type: 'vip_sender', value: 'ceo@company.com' },
          { type: 'source_channel', value: 'email' },
        ],
        conditionOperator: 'AND',
        action: { type: 'notify_immediately' },
        enabled: true,
      }
      const message = {
        sender: 'ceo@company.com',
        subject: 'Important',
        content: 'Read this',
        channel: 'email' as const,
      }
      const result = evaluateRule(rule, message)
      expect(result).toEqual({ type: 'notify_immediately' })
    })

    it('should return null when not all conditions match (AND)', () => {
      const rule: CrossChannelRule = {
        id: 'rule-1',
        name: 'VIP from company',
        conditions: [
          { type: 'vip_sender', value: 'ceo@company.com' },
          { type: 'source_channel', value: 'discord' },
        ],
        conditionOperator: 'AND',
        action: { type: 'notify_immediately' },
        enabled: true,
      }
      const message = {
        sender: 'ceo@company.com',
        subject: 'Important',
        content: 'Read this',
        channel: 'email' as const,
      }
      const result = evaluateRule(rule, message)
      expect(result).toBeNull()
    })

    it('should return action when any condition matches (OR)', () => {
      const rule: CrossChannelRule = {
        id: 'rule-2',
        name: 'Urgent keywords',
        conditions: [
          { type: 'keyword', value: 'URGENT', field: 'subject' },
          { type: 'keyword', value: 'ASAP', field: 'subject' },
        ],
        conditionOperator: 'OR',
        action: { type: 'prioritize' },
        enabled: true,
      }
      const message = {
        sender: 'someone@example.com',
        subject: 'Please reply ASAP',
        content: 'Details',
        channel: 'email' as const,
      }
      const result = evaluateRule(rule, message)
      expect(result).toEqual({ type: 'prioritize' })
    })

    it('should return null for disabled rules', () => {
      const rule: CrossChannelRule = {
        id: 'rule-3',
        name: 'Disabled rule',
        conditions: [{ type: 'vip_sender', value: 'vip@example.com' }],
        conditionOperator: 'AND',
        action: { type: 'notify_immediately' },
        enabled: false,
      }
      const message = {
        sender: 'vip@example.com',
        subject: 'Hello',
        content: 'Content',
        channel: 'email' as const,
      }
      const result = evaluateRule(rule, message)
      expect(result).toBeNull()
    })
  })

  describe('CrossChannelRulesService', () => {
    it('should add and retrieve rules', () => {
      const service = createCrossChannelRulesService()
      const rule: CrossChannelRule = {
        id: 'rule-1',
        name: 'Test rule',
        conditions: [{ type: 'vip_sender', value: 'test@example.com' }],
        conditionOperator: 'AND',
        action: { type: 'notify_immediately' },
        enabled: true,
      }
      service.addRule(rule)
      expect(service.getRules()).toContainEqual(rule)
    })

    it('should remove rules by id', () => {
      const service = createCrossChannelRulesService()
      const rule: CrossChannelRule = {
        id: 'rule-to-remove',
        name: 'Test rule',
        conditions: [{ type: 'newsletter' }],
        conditionOperator: 'AND',
        action: { type: 'ignore' },
        enabled: true,
      }
      service.addRule(rule)
      service.removeRule('rule-to-remove')
      expect(service.getRules()).not.toContainEqual(rule)
    })

    it('should evaluate all rules and return first matching action', () => {
      const service = createCrossChannelRulesService()
      service.addRule({
        id: 'rule-1',
        name: 'VIP rule',
        conditions: [{ type: 'vip_sender', value: 'vip@company.com' }],
        conditionOperator: 'AND',
        action: { type: 'notify_immediately' },
        enabled: true,
        priority: 10,
      })
      service.addRule({
        id: 'rule-2',
        name: 'Newsletter rule',
        conditions: [{ type: 'newsletter' }],
        conditionOperator: 'AND',
        action: { type: 'ignore' },
        enabled: true,
        priority: 5,
      })

      const message = {
        sender: 'vip@company.com',
        subject: 'Hello',
        content: 'Important message',
        channel: 'email' as const,
      }

      const actions = service.evaluateMessage(message)
      expect(actions).toContainEqual({ type: 'notify_immediately' })
    })

    it('should support cross-channel notification action', () => {
      const service = createCrossChannelRulesService()
      service.addRule({
        id: 'cross-channel-rule',
        name: 'VIP email to Telegram',
        conditions: [
          { type: 'vip_sender', value: 'boss@company.com' },
          { type: 'source_channel', value: 'email' },
        ],
        conditionOperator: 'AND',
        action: {
          type: 'notify_via_channel',
          targetChannel: 'telegram',
        },
        enabled: true,
      })

      const message = {
        sender: 'boss@company.com',
        subject: 'Urgent',
        content: 'Please review',
        channel: 'email' as const,
      }

      const actions = service.evaluateMessage(message)
      expect(actions).toContainEqual({
        type: 'notify_via_channel',
        targetChannel: 'telegram',
      })
    })

    it('should persist rules to localStorage', () => {
      const service = createCrossChannelRulesService()
      const rule: CrossChannelRule = {
        id: 'persistent-rule',
        name: 'Persistent',
        conditions: [{ type: 'vip_sender', value: 'test@test.com' }],
        conditionOperator: 'AND',
        action: { type: 'prioritize' },
        enabled: true,
      }
      service.addRule(rule)
      service.saveRules()

      const stored = localStorage.getItem(RULES_STORAGE_KEY)
      expect(stored).not.toBeNull()
      const parsed = JSON.parse(stored!)
      expect(parsed).toContainEqual(rule)
    })

    it('should load rules from localStorage', () => {
      const rules: CrossChannelRule[] = [
        {
          id: 'loaded-rule',
          name: 'Loaded',
          conditions: [{ type: 'newsletter' }],
          conditionOperator: 'AND',
          action: { type: 'ignore' },
          enabled: true,
        },
      ]
      localStorage.setItem(RULES_STORAGE_KEY, JSON.stringify(rules))

      const service = createCrossChannelRulesService()
      service.loadRules()
      expect(service.getRules()).toContainEqual(rules[0])
    })

    it('should toggle rule enabled state', () => {
      const service = createCrossChannelRulesService()
      service.addRule({
        id: 'toggle-rule',
        name: 'Toggle test',
        conditions: [{ type: 'vip_sender', value: 'x@y.com' }],
        conditionOperator: 'AND',
        action: { type: 'notify_immediately' },
        enabled: true,
      })

      service.toggleRule('toggle-rule', false)
      const rule = service.getRules().find(r => r.id === 'toggle-rule')
      expect(rule?.enabled).toBe(false)
    })

    it('should provide default VIP and newsletter rules', () => {
      const service = createCrossChannelRulesService()
      const defaults = service.getDefaultRules()

      expect(defaults.some(r => r.name.toLowerCase().includes('vip'))).toBe(true)
      expect(defaults.some(r => r.name.toLowerCase().includes('newsletter'))).toBe(true)
    })
  })
})
