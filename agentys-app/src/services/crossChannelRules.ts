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
 * Cross-Channel Rules Service
 *
 * Manages intelligent rules that work across all channels (email, Discord, Telegram).
 * Features:
 * - VIP contacts: immediate notification regardless of work hours
 * - Newsletter detection: auto-ignore common patterns
 * - Urgent keywords: prioritize messages containing specific keywords
 * - Cross-channel actions: e.g., VIP email triggers Telegram notification
 */

import i18n from '../i18n'
import {
  getCurrentAccountId,
  subscribeCurrentAccountId,
} from '../lib/currentAccountId'

export type MessageChannel = 'email' | 'discord' | 'telegram' | 'slack'

export interface RuleMessage {
  sender: string
  subject: string
  content: string
  channel: MessageChannel
}

export type RuleConditionType =
  | 'vip_sender'
  | 'sender_domain'
  | 'keyword'
  | 'newsletter'
  | 'source_channel'

export interface RuleCondition {
  type: RuleConditionType
  value?: string
  field?: 'subject' | 'content' | 'sender'
}

export type RuleActionType =
  | 'notify_immediately'
  | 'ignore'
  | 'prioritize'
  | 'notify_via_channel'

export interface RuleAction {
  type: RuleActionType
  targetChannel?: MessageChannel
}

export interface CrossChannelRule {
  id: string
  name: string
  conditions: RuleCondition[]
  conditionOperator: 'AND' | 'OR'
  action: RuleAction
  enabled: boolean
  priority?: number
}

const NEWSLETTER_PATTERNS = [
  /noreply@/i,
  /no-reply@/i,
  /newsletter@/i,
  /marketing@/i,
  /unsubscribe/i,
  /se désabonner/i,
  /click here to unsubscribe/i,
  /update your preferences/i,
  /email preferences/i,
  /weekly digest/i,
  /daily digest/i,
  /promotional/i,
]

export function matchesCondition(
  condition: RuleCondition,
  message: RuleMessage
): boolean {
  switch (condition.type) {
    case 'vip_sender':
      return message.sender.toLowerCase() === condition.value?.toLowerCase()

    case 'sender_domain': {
      const domain = message.sender.split('@')[1]?.toLowerCase()
      return domain === condition.value?.toLowerCase()
    }

    case 'keyword': {
      const searchValue = condition.value?.toLowerCase() || ''
      const field = condition.field || 'subject'
      const text =
        field === 'subject'
          ? message.subject
          : field === 'content'
            ? message.content
            : message.sender
      return text.toLowerCase().includes(searchValue)
    }

    case 'newsletter': {
      const combined = `${message.sender} ${message.subject} ${message.content}`
      return NEWSLETTER_PATTERNS.some((pattern) => pattern.test(combined))
    }

    case 'source_channel':
      return message.channel === condition.value

    default:
      return false
  }
}

export function evaluateRule(
  rule: CrossChannelRule,
  message: RuleMessage
): RuleAction | null {
  if (!rule.enabled) return null

  const results = rule.conditions.map((condition) =>
    matchesCondition(condition, message)
  )

  const matches =
    rule.conditionOperator === 'AND'
      ? results.every(Boolean)
      : results.some(Boolean)

  return matches ? rule.action : null
}

export interface CrossChannelRulesService {
  getRules(): CrossChannelRule[]
  addRule(rule: CrossChannelRule): void
  updateRule(id: string, updates: Partial<CrossChannelRule>): void
  removeRule(id: string): void
  toggleRule(id: string, enabled: boolean): void
  evaluateMessage(message: RuleMessage): RuleAction[]
  saveRules(): void
  loadRules(): void
  getDefaultRules(): CrossChannelRule[]
}

const STORAGE_KEY_BASE = 'agentys_cross_channel_rules'

function getStorageKey(): string {
  const accountId = getCurrentAccountId()
  return `${STORAGE_KEY_BASE}:${accountId ?? '__none'}`
}

export function createCrossChannelRulesService(): CrossChannelRulesService {
  let rules: CrossChannelRule[] = []

  const getDefaultRules = (): CrossChannelRule[] => [
    {
      id: 'default-vip',
      name: i18n.t('common:rule_vip_contacts'),
      conditions: [],
      conditionOperator: 'OR',
      action: { type: 'notify_immediately' },
      enabled: true,
      priority: 100,
    },
    {
      id: 'default-newsletter',
      name: i18n.t('common:rule_ignore_newsletters'),
      conditions: [{ type: 'newsletter' }],
      conditionOperator: 'AND',
      action: { type: 'ignore' },
      enabled: true,
      priority: 50,
    },
    {
      id: 'default-urgent',
      name: i18n.t('common:rule_urgent_keywords'),
      conditions: [
        { type: 'keyword', value: 'urgent', field: 'subject' },
        { type: 'keyword', value: 'asap', field: 'subject' },
        { type: 'keyword', value: 'important', field: 'subject' },
      ],
      conditionOperator: 'OR',
      action: { type: 'prioritize' },
      enabled: true,
      priority: 80,
    },
  ]

  return {
    getRules(): CrossChannelRule[] {
      return [...rules]
    },

    addRule(rule: CrossChannelRule): void {
      const exists = rules.some((r) => r.id === rule.id)
      if (!exists) {
        rules.push(rule)
      }
    },

    updateRule(id: string, updates: Partial<CrossChannelRule>): void {
      const index = rules.findIndex((r) => r.id === id)
      if (index !== -1) {
        rules[index] = { ...rules[index], ...updates }
      }
    },

    removeRule(id: string): void {
      rules = rules.filter((r) => r.id !== id)
    },

    toggleRule(id: string, enabled: boolean): void {
      const rule = rules.find((r) => r.id === id)
      if (rule) {
        rule.enabled = enabled
      }
    },

    evaluateMessage(message: RuleMessage): RuleAction[] {
      const sortedRules = [...rules].sort(
        (a, b) => (b.priority || 0) - (a.priority || 0)
      )

      const actions: RuleAction[] = []
      for (const rule of sortedRules) {
        const action = evaluateRule(rule, message)
        if (action) {
          actions.push(action)
        }
      }

      return actions
    },

    saveRules(): void {
      try {
        localStorage.setItem(getStorageKey(), JSON.stringify(rules))
      } catch {
        // Storage quota exceeded or unavailable
      }
    },

    loadRules(): void {
      try {
        const stored = localStorage.getItem(getStorageKey())
        rules = stored ? JSON.parse(stored) : []
      } catch {
        // Invalid JSON or storage unavailable
        rules = []
      }
    },

    getDefaultRules,
  }
}

let serviceInstance: CrossChannelRulesService | null = null

export function getCrossChannelRulesService(): CrossChannelRulesService {
  if (!serviceInstance) {
    serviceInstance = createCrossChannelRulesService()
    serviceInstance.loadRules()
    if (serviceInstance.getRules().length === 0) {
      serviceInstance.getDefaultRules().forEach((rule) => {
        serviceInstance!.addRule(rule)
      })
      serviceInstance.saveRules()
    }
  }
  return serviceInstance
}

export function resetCrossChannelRulesService(): void {
  serviceInstance = null
}

// Invalider le singleton quand le compte actif change : le prochain
// getCrossChannelRulesService() rechargera les règles depuis la clé
// localStorage du nouveau compte (ou seedera les règles par défaut).
subscribeCurrentAccountId(() => {
  serviceInstance = null
})
