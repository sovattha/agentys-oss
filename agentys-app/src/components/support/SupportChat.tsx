import { useState, useCallback, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import DOMPurify from 'dompurify'
import { getResponse, getWelcomeMessage, POPULAR_ARTICLE_IDS, ARTICLE_INDEX, type ChatResponse, type QuickAction } from './chatEngine'
import { buildSupportEmail } from './supportEmail'
import { apiClient } from '../../services/api'
import { CheckIcon, SendIcon } from '../icons/ActionIcons'
import type { PanelView } from './SupportPanel'

interface ChatMessage {
  id: number
  role: 'bot' | 'user'
  text: string
  quickActions?: QuickAction[]
  animate?: boolean
  timestamp: number
  isWelcome?: boolean
  /** Special inline widget instead of text bubble */
  widget?: 'email-preview' | 'inline-success' | 'inline-error' | 'inline-sending'
  /** Widget metadata */
  widgetData?: { subject?: string; body?: string; ticketRef?: string; errorMsg?: string }
}

interface SupportChatProps {
  onNavigate: (view: PanelView) => void
  onClose: () => void
  accountEmail: string
}

type EscaladePhase = 'idle' | 'collecting' | 'preview' | 'sending' | 'sent' | 'error'

let msgIdCounter = 0

function parseAction(action: string): { type: string; value: string } {
  const colonIdx = action.indexOf(':')
  if (colonIdx === -1) return { type: action, value: '' }
  return { type: action.slice(0, colonIdx), value: action.slice(colonIdx + 1) }
}

function generateTicketRef(): string {
  const num = Math.floor(10000 + Math.random() * 90000)
  return `AG-${num}`
}

/** Should show a timestamp separator between two messages? (2+ min gap) */
function shouldShowTimestamp(prev: ChatMessage, curr: ChatMessage): boolean {
  return (curr.timestamp - prev.timestamp) >= 120000
}

/** SVG micro-icons for chips (13x13) */
function ChipIcon({ icon }: { icon: string }) {
  const props = { width: 13, height: 13, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }

  switch (icon) {
    case 'drafts':
      return <svg aria-hidden="true" {...props}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6" /><path d="M16 13H8" /><path d="M16 17H8" /><path d="M10 9H8" /></svg>
    case 'style':
      return <svg aria-hidden="true" {...props}><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>
    case 'speed':
      return <svg aria-hidden="true" {...props}><path d="m13 2-2 14h6L9 22" /></svg>
    case 'problem':
      return <svg aria-hidden="true" {...props}><circle cx="12" cy="12" r="10" /><path d="M12 8v4" /><path d="M12 16h.01" /></svg>
    case 'idea':
      return <svg aria-hidden="true" {...props}><path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5" /><path d="M9 18h6" /><path d="M10 22h4" /></svg>
    case 'search':
      return <svg aria-hidden="true" {...props}><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
    case 'help':
      return <svg aria-hidden="true" {...props}><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><path d="M12 17h.01" /></svg>
    case 'bug':
      return <svg aria-hidden="true" {...props}><path d="m8 2 1.88 1.88" /><path d="M14.12 3.88 16 2" /><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1" /><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6" /><path d="M12 20v-9" /><path d="M6.53 9C4.6 8.8 3 7.1 3 5" /><path d="M6 13H2" /><path d="M3 21c0-2.1 1.7-3.9 3.8-4" /><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4" /><path d="M22 13h-4" /><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4" /></svg>
    case 'close':
      return <svg aria-hidden="true" {...props}><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>
    default:
      return null
  }
}

/** Agentys logo avatar — filled triangle with glow */
function AgentysAvatar({ size = 28, className = '' }: { size?: number; className?: string }) {
  return (
    <div className={`sp-chat-avatar ${className}`} style={size !== 28 ? { width: size, height: size } : undefined}>
      <svg aria-hidden="true" width={size * 0.5} height={size * 0.5} viewBox="0 0 24 24" fill="currentColor" stroke="none">
        <path d="M12 2L2 19h20L12 2Z" />
      </svg>
    </div>
  )
}

/** Welcome Hero — replaces the first bot message */
function WelcomeHero({ actions, onAction }: { actions: QuickAction[]; onAction: (action: string) => void }) {
  const { t } = useTranslation('support')
  const gridActions = actions.slice(0, 4)
  const linkActions = actions.slice(4)

  // Build popular articles from the index
  const popularArticles = POPULAR_ARTICLE_IDS
    .map(id => ARTICLE_INDEX.find(a => a.id === id))
    .filter(Boolean) as typeof ARTICLE_INDEX

  return (
    <div className="sp-welcome-hero sp-chat-animate">
      <div className="sp-welcome-intro">
        <p className="sp-welcome-text">{t('welcome_greeting_short', 'How can I help?')}</p>
      </div>

      <div className="sp-welcome-grid" role="list">
        {gridActions.map((qa, i) => (
          <button
            key={i}
            role="listitem"
            className="sp-welcome-card"
            onClick={() => onAction(qa.action)}
            style={{ animationDelay: `${0.06 + i * 0.05}s` }}
          >
            <span className="sp-welcome-card-icon" aria-hidden="true">
              {qa.icon && <ChipIcon icon={qa.icon} />}
            </span>
            <span className="sp-welcome-card-label">{qa.label}</span>
          </button>
        ))}
      </div>

      {popularArticles.length > 0 && (
        <div className="sp-welcome-popular">
          <span className="sp-welcome-section-label">{t('welcome_popular_guides', 'Popular guides')}</span>
          <div className="sp-welcome-articles">
            {popularArticles.map((article) => (
              <button
                key={article.id}
                className="sp-welcome-article"
                onClick={() => onAction(`help-article:${article.id}`)}
              >
                <span className="sp-welcome-article-label">{t(article.titleKey)}</span>
                <svg aria-hidden="true" className="sp-welcome-article-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m9 18 6-6-6-6" />
                </svg>
              </button>
            ))}
          </div>
        </div>
      )}

      {linkActions.length > 0 && (
        <div className="sp-welcome-links">
          {linkActions.map((qa, i) => (
            <button key={i} className="sp-welcome-link" onClick={() => onAction(qa.action)}>
              {qa.icon && <ChipIcon icon={qa.icon} />}
              <span>{qa.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** Feedback thumbs (up/down) — component state only */
function FeedbackThumbs({ messageId: _messageId }: { messageId: number }) {
  const { t } = useTranslation('support')
  const [vote, setVote] = useState<'up' | 'down' | null>(null)
  const [flash, setFlash] = useState(false)

  const handleVote = (v: 'up' | 'down') => {
    setVote(v)
    setFlash(true)
    setTimeout(() => setFlash(false), 400)
  }

  return (
    <div className={`sp-feedback${vote ? ' sp-feedback-voted' : ''}`}>
      <button
        className={`sp-feedback-btn${vote === 'up' ? ' sp-feedback-active' : ''}${flash && vote === 'up' ? ' sp-feedback-flash' : ''}`}
        onClick={() => handleVote('up')}
        aria-label={t('aria_useful')}
        disabled={vote !== null}
      >
        <svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M7 10v12" /><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
        </svg>
      </button>
      <button
        className={`sp-feedback-btn${vote === 'down' ? ' sp-feedback-active' : ''}${flash && vote === 'down' ? ' sp-feedback-flash' : ''}`}
        onClick={() => handleVote('down')}
        aria-label={t('aria_not_useful')}
        disabled={vote !== null}
      >
        <svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M17 14V2" /><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
        </svg>
      </button>
    </div>
  )
}

/** Email preview card — inline in chat */
function EmailPreviewCard({ subject, body, ticketRef, onModify, onSend }: {
  subject: string
  body: string
  ticketRef: string
  onModify: () => void
  onSend: () => void
}) {
  const { t } = useTranslation('support')
  // The full subject sent to support carries the ref suffix (`- AG-12345`).
  // The preview surface strips it so the ref appears once, as the topbar badge.
  const subjectClean = ticketRef
    ? subject.replace(new RegExp(`\\s*-\\s*${ticketRef}\\s*$`), '').trim()
    : subject
  const previewBody = body.length > 240 ? body.slice(0, 240) + '…' : body

  return (
    <div className="sp-email-preview sp-chat-animate">
      <div className="sp-email-preview-topbar">
        <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect width="20" height="16" x="2" y="4" rx="2" />
          <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
        </svg>
        <span className="sp-email-preview-title">{t('email_preview_header')}</span>
      </div>
      <div className="sp-email-preview-fields">
        <div className="sp-email-preview-field">
          <span className="sp-email-preview-label">{t('email_preview_to_label')}</span>
          <span className="sp-email-preview-value">support@agentys.io</span>
        </div>
        <div className="sp-email-preview-field">
          <span className="sp-email-preview-label">{t('email_preview_subject_label')}</span>
          <span className="sp-email-preview-value">{subjectClean}</span>
        </div>
      </div>
      <div className="sp-email-preview-body">{previewBody}</div>
      <div className="sp-email-preview-actions">
        <button className="sp-email-preview-btn sp-email-preview-btn-ghost" onClick={onModify}>
          {t('email_preview_modify')}
        </button>
        <button className="sp-email-preview-btn sp-email-preview-btn-send" onClick={onSend}>
          <SendIcon size={14} />
          {t('send')}
        </button>
      </div>
    </div>
  )
}

/** Inline success — compact check */
function InlineSuccess() {
  const { t } = useTranslation('support')
  return (
    <div className="sp-inline-success sp-chat-animate">
      <div className="sp-inline-success-check">
        <CheckIcon />
      </div>
      <div className="sp-inline-success-text">
        <span className="sp-inline-success-title">{t('inline_success_title')}</span>
      </div>
    </div>
  )
}

/** Inline sending spinner */
function InlineSending() {
  const { t } = useTranslation('support')
  return (
    <div className="sp-inline-sending sp-chat-animate">
      <span className="sp-dot" />
      <span className="sp-dot" />
      <span className="sp-dot" />
      <span className="sp-inline-sending-text">{t('inline_sending_text')}</span>
    </div>
  )
}

/** Inline error */
function InlineError({ message }: { message: string }) {
  return (
    <div className="sp-inline-error sp-chat-animate">
      <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <path d="M12 8v4" />
        <path d="M12 16h.01" />
      </svg>
      <span>{message}</span>
    </div>
  )
}

export function SupportChat({ onNavigate, onClose, accountEmail }: SupportChatProps) {
  const { t } = useTranslation('support')
  // i18next's TFunction has many overloads — narrow to the single call shape
  // chatEngine uses: t(key, defaultValue) → string.
  const welcome = getWelcomeMessage(t as unknown as (key: string, defaultValue?: string) => string)
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: ++msgIdCounter, role: 'bot', text: welcome.text, quickActions: welcome.quickActions, animate: true, timestamp: Date.now(), isWelcome: true },
  ])
  const [input, setInput] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Escalation state machine
  const [escaladePhase, setEscaladePhase] = useState<EscaladePhase>('idle')
  const escaladeDataRef = useRef<{
    description: string
    subject: string
    body: string
    ticketRef: string
  }>({ description: '', subject: '', body: '', ticketRef: '' })

  // Auto-scroll on new messages
  useEffect(() => {
    const el = scrollRef.current
    if (el) {
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight
      })
    }
  }, [messages, isTyping])

  /** Relative time label for timestamp separators */
  const getTimeLabel = useCallback((ts: number): string => {
    const diff = Math.floor((Date.now() - ts) / 60000)
    if (diff < 1) return t('time_now')
    if (diff === 1) return t('time_1min')
    return t('time_n_min', { n: diff })
  }, [t])

  /**
   * Build email subject + body from user description. Delegates to the
   * `buildSupportEmail` pure helper so the body contract stays unit-tested.
   */
  const buildEmail = useCallback((description: string): { subject: string; body: string; ticketRef: string } => {
    const ticketRef = generateTicketRef()
    const { subject, body } = buildSupportEmail({
      description,
      accountEmail,
      ticketRef,
      signature: t('email_body_signature', 'Sent from Agentys'),
    })
    return { subject, body, ticketRef }
  }, [accountEmail, t])

  const addBotMessage = useCallback((text: string, quickActions?: QuickAction[], widget?: ChatMessage['widget'], widgetData?: ChatMessage['widgetData']) => {
    setMessages(prev => [
      ...prev,
      {
        id: ++msgIdCounter,
        role: 'bot',
        text,
        quickActions,
        widget,
        widgetData,
        animate: true,
        timestamp: Date.now(),
      },
    ])
  }, [])

  const addBotResponse = useCallback((response: ChatResponse) => {
    setIsTyping(true)
    const delay = 350 + Math.random() * 350
    setTimeout(() => {
      setIsTyping(false)
      // The rule engine returns an i18n KEY for `text` (or '' for the welcome
      // screen). Resolve it against the active locale here; an empty string
      // stays empty (t('') === ''). Chip labels are resolved by the renderer
      // via t(qa.label, qa.label).
      addBotMessage(response.text ? t(response.text) : '', response.quickActions)
    }, delay)
  }, [addBotMessage, t])

  /** Start escalation flow */
  const handleEscalateStart = useCallback(() => {
    setEscaladePhase('collecting')
    setIsTyping(true)
    setTimeout(() => {
      setIsTyping(false)
      addBotMessage(t('escalate_prompt'))
      // Focus input
      inputRef.current?.focus()
    }, 400)
  }, [addBotMessage, t])

  /** User submitted their description — show preview */
  const handleEscalateCollect = useCallback((description: string) => {
    const email = buildEmail(description)
    escaladeDataRef.current = { description, ...email }
    setEscaladePhase('preview')

    // Show the email preview card as a widget message
    addBotMessage('', undefined, 'email-preview', {
      subject: email.subject,
      body: email.body,
      ticketRef: email.ticketRef,
    })
  }, [buildEmail, addBotMessage])

  /** User clicked "Modifier" — go back to collecting */
  const handleEscalateModify = useCallback(() => {
    setEscaladePhase('collecting')
    addBotMessage(t('escalate_modify_prompt'))
    inputRef.current?.focus()
  }, [addBotMessage, t])

  /** User clicked "Envoyer" — send the email */
  const handleEscaladeSend = useCallback(async () => {
    const data = escaladeDataRef.current
    setEscaladePhase('sending')

    // Show inline sending
    addBotMessage('', undefined, 'inline-sending')

    try {
      await apiClient.sendNewEmail('support@agentys.io', data.subject, data.body)
      setEscaladePhase('sent')

      // Replace sending widget with success
      setMessages(prev => {
        // Remove the sending widget
        const filtered = prev.filter(m => m.widget !== 'inline-sending')
        return [
          ...filtered,
          {
            id: ++msgIdCounter,
            role: 'bot',
            text: '',
            widget: 'inline-success',
            widgetData: { ticketRef: data.ticketRef },
            animate: true,
            timestamp: Date.now(),
          },
          {
            id: ++msgIdCounter,
            role: 'bot',
            text: t('escalate_sent_msg', { ref: data.ticketRef }),
            quickActions: [
              { label: t('escalate_another_question'), action: 'input:j\'ai une autre question' },
              { label: t('close'), action: 'close' },
            ],
            animate: true,
            timestamp: Date.now(),
          },
        ]
      })

      // Reset escalade
      setEscaladePhase('idle')
      escaladeDataRef.current = { description: '', subject: '', body: '', ticketRef: '' }
    } catch (err) {
      setEscaladePhase('error')
      const errorMsg = err instanceof Error ? err.message : t('send_failed')

      // Replace sending widget with error
      setMessages(prev => {
        const filtered = prev.filter(m => m.widget !== 'inline-sending')
        return [
          ...filtered,
          {
            id: ++msgIdCounter,
            role: 'bot',
            text: '',
            widget: 'inline-error',
            widgetData: { errorMsg },
            animate: true,
            timestamp: Date.now(),
          },
          {
            id: ++msgIdCounter,
            role: 'bot',
            text: `${t('error_title')} : ${errorMsg}`,
            quickActions: [
              { label: t('escalate_retry_label'), action: 'escalate-retry:support' },
              { label: t('close'), action: 'close' },
            ],
            animate: true,
            timestamp: Date.now(),
          },
        ]
      })
    }
  }, [addBotMessage, t])

  const handleSend = useCallback((text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return

    setInput('')
    setMessages(prev => [
      ...prev,
      { id: ++msgIdCounter, role: 'user', text: trimmed, timestamp: Date.now() },
    ])

    // If we're in collecting phase, capture as description instead of chatbot response
    if (escaladePhase === 'collecting') {
      handleEscalateCollect(trimmed)
      return
    }

    const response = getResponse(trimmed)
    addBotResponse(response)
  }, [addBotResponse, escaladePhase, handleEscalateCollect])

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault()
    handleSend(input)
  }, [input, handleSend])

  const handleQuickAction = useCallback((action: string) => {
    const { type, value } = parseAction(action)

    switch (type) {
      case 'input':
        handleSend(value)
        break
      case 'form':
        onNavigate({ screen: 'form', intent: value as 'support' | 'feedback' | 'bug' | 'feature' })
        break
      case 'escalate':
        handleEscalateStart()
        break
      case 'escalate-retry':
        // Retry: go back to preview with existing data
        setEscaladePhase('preview')
        addBotMessage('', undefined, 'email-preview', {
          subject: escaladeDataRef.current.subject,
          body: escaladeDataRef.current.body,
          ticketRef: escaladeDataRef.current.ticketRef,
        })
        break
      case 'navigate':
        if (value === 'help') {
          onNavigate({ screen: 'help' })
        }
        break
      case 'help-article':
        onNavigate({ screen: 'help-article', articleId: value })
        break
      case 'close':
        onClose()
        break
      default:
        break
    }
  }, [handleSend, onNavigate, onClose, handleEscalateStart, addBotMessage])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend(input)
    }
  }, [input, handleSend])

  // Placeholder changes based on escalade phase
  const inputPlaceholder = escaladePhase === 'collecting'
    ? t('input_placeholder_collecting')
    : t('input_placeholder_default')

  // Disable input during sending
  const inputDisabled = escaladePhase === 'sending'

  return (
    <div className="sp-chat">
      {/* Messages area */}
      <div className="sp-chat-messages" ref={scrollRef}>
        {messages.map((msg, idx) => {
          // Timestamp separator between messages spaced 2+ min
          const prevMsg = idx > 0 ? messages[idx - 1] : null
          const showTs = prevMsg && shouldShowTimestamp(prevMsg, msg)
          // Dedupe bot avatars: first message in a bot streak shows the avatar,
          // subsequent consecutive bot messages get a transparent spacer of the
          // same width so the bubble alignment stays consistent.
          const isBot = msg.role === 'bot'
          const showAvatar = isBot && (!prevMsg || prevMsg.role !== 'bot' || !!showTs)
          const BotIcon = () =>
            showAvatar ? <AgentysAvatar /> : <span className="sp-chat-avatar-spacer" aria-hidden="true" />

          return (
            <div key={msg.id}>
              {/* Timestamp separator */}
              {showTs && (
                <div className="sp-timestamp">
                  <span>{getTimeLabel(msg.timestamp)}</span>
                </div>
              )}

              {/* Welcome Hero replaces first bot message */}
              {msg.isWelcome && msg.quickActions ? (
                <WelcomeHero actions={msg.quickActions} onAction={handleQuickAction} />
              ) : msg.widget === 'email-preview' && msg.widgetData ? (
                <div className="sp-chat-row sp-chat-bot sp-chat-animate">
                  <BotIcon />
                  <div className="sp-chat-bubble-wrap">
                    <EmailPreviewCard
                      subject={msg.widgetData.subject || ''}
                      body={msg.widgetData.body || ''}
                      ticketRef={msg.widgetData.ticketRef || ''}
                      onModify={handleEscalateModify}
                      onSend={handleEscaladeSend}
                    />
                  </div>
                </div>
              ) : msg.widget === 'inline-success' && msg.widgetData ? (
                <div className="sp-chat-row sp-chat-bot sp-chat-animate">
                  <BotIcon />
                  <div className="sp-chat-bubble-wrap">
                    <InlineSuccess />
                  </div>
                </div>
              ) : msg.widget === 'inline-sending' ? (
                <div className="sp-chat-row sp-chat-bot sp-chat-animate">
                  <BotIcon />
                  <div className="sp-chat-bubble-wrap">
                    <InlineSending />
                  </div>
                </div>
              ) : msg.widget === 'inline-error' && msg.widgetData ? (
                <div className="sp-chat-row sp-chat-bot sp-chat-animate">
                  <BotIcon />
                  <div className="sp-chat-bubble-wrap">
                    <InlineError message={msg.widgetData.errorMsg || t('send_failed')} />
                  </div>
                </div>
              ) : (
                <div className={`sp-chat-row sp-chat-${msg.role}${msg.animate ? ' sp-chat-animate' : ''}`}>
                  {isBot && <BotIcon />}
                  <div className="sp-chat-bubble-wrap">
                    <div className="sp-chat-bubble">
                      {msg.text.split('\n').map((line, i) => {
                        const parsed = DOMPurify.sanitize(
                          line
                            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                            .replace(/`(.+?)`/g, '<code>$1</code>'),
                          { ALLOWED_TAGS: ['strong', 'code', 'em'] }
                        )
                        return <p key={i} dangerouslySetInnerHTML={{ __html: parsed }} />
                      })}
                    </div>
                    {msg.quickActions && msg.quickActions.length > 0 && (
                      <div className="sp-chat-chips">
                        {msg.quickActions.map((qa, i) => (
                          <button
                            key={i}
                            className="sp-chat-chip"
                            onClick={() => handleQuickAction(qa.action)}
                          >
                            {qa.icon && <ChipIcon icon={qa.icon} />}
                            {/* Rule engine sometimes stuffs i18n keys (e.g. `art_*_title`)
                                into `label` and trusts the renderer to translate them.
                                t(label, label) resolves keys + passes literals through. */}
                            {t(qa.label, qa.label)}
                          </button>
                        ))}
                      </div>
                    )}
                    {/* Feedback thumbs — only on non-welcome bot messages */}
                    {isBot && <FeedbackThumbs messageId={msg.id} />}
                  </div>
                </div>
              )}
            </div>
          )
        })}

        {/* Typing indicator */}
        {isTyping && (
          <div className="sp-chat-row sp-chat-bot sp-chat-animate">
            <AgentysAvatar />
            <div className="sp-chat-bubble-wrap">
              <div className="sp-chat-bubble sp-chat-typing">
                <span className="sp-dot" />
                <span className="sp-dot" />
                <span className="sp-dot" />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input bar */}
      <form className="sp-chat-input-bar" onSubmit={handleSubmit}>
        <input
          ref={inputRef}
          type="text"
          className="sp-chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={inputPlaceholder}
          disabled={inputDisabled}
          autoFocus
        />
        <button
          type="submit"
          className="sp-chat-send"
          disabled={!input.trim() || inputDisabled}
          aria-label={t('aria_send')}
        >
          <SendIcon size={16} />
        </button>
      </form>
    </div>
  )
}
