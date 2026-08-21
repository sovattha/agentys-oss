import { useState, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { getApiClient, type WizardConnectionParams, type EnvConfigResponse } from '../../../services/api'
import { IS_CLOUD } from '../../../config'
import { ConnectGmailButton } from '../../ConnectGmailButton'
import { ConnectOutlookButton } from '../../ConnectOutlookButton'

interface Step1Props {
  onNext: () => void
  onBack: () => void
  onConnected: () => void
  onOAuthComplete?: () => void
  onLlmConfigured: () => void
  forceOAuthReconnect?: boolean
}

type Phase = 'connect' | 'llm'
type ConnectionStatus = 'idle' | 'testing' | 'success' | 'error'

interface EmailPreset {
  name: string
  imapHost: string
  imapPort: number
  smtpHost: string
  smtpPort: number
  imapUseSsl: boolean
  smtpUseTls: boolean
  smtpUseSsl: boolean
}

const EMAIL_PRESETS: EmailPreset[] = [
  { name: 'OVH', imapHost: 'ssl0.ovh.net', imapPort: 993, smtpHost: 'ssl0.ovh.net', smtpPort: 587, imapUseSsl: true, smtpUseTls: true, smtpUseSsl: false },
  { name: 'Infomaniak', imapHost: 'mail.infomaniak.com', imapPort: 993, smtpHost: 'mail.infomaniak.com', smtpPort: 587, imapUseSsl: true, smtpUseTls: true, smtpUseSsl: false },
  { name: 'Gmail', imapHost: 'imap.gmail.com', imapPort: 993, smtpHost: 'smtp.gmail.com', smtpPort: 587, imapUseSsl: true, smtpUseTls: true, smtpUseSsl: false },
  { name: 'Outlook', imapHost: 'outlook.office365.com', imapPort: 993, smtpHost: 'smtp.office365.com', smtpPort: 587, imapUseSsl: true, smtpUseTls: true, smtpUseSsl: false },
]

const INITIAL_FORM = {
  imapHost: '', imapPort: 993, smtpHost: '', smtpPort: 587,
  email: '', password: '', imapUseSsl: true, smtpUseTls: true, smtpUseSsl: false,
}

export function Step1Connect({ onNext, onBack: _onBack, onConnected, onOAuthComplete, onLlmConfigured, forceOAuthReconnect = false }: Step1Props) {
  const { t } = useTranslation('onboarding')
  const api = getApiClient()
  const [phase, setPhase] = useState<Phase>('connect')
  const [form, setForm] = useState(INITIAL_FORM)
  const [status, setStatus] = useState<ConnectionStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [envLoading, setEnvLoading] = useState(true)
  const [oauthConfigured, setOauthConfigured] = useState(false)
  const [oauthProvider, setOauthProvider] = useState<'gmail' | 'outlook' | null>(null)
  const [activePreset, setActivePreset] = useState<string | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)

  // LLM state
  const [llmProvider, setLlmProvider] = useState<'claude' | 'ollama'>('claude')
  const [llmKey, setLlmKey] = useState('')
  const [llmHasEnv, setLlmHasEnv] = useState(false)
  const [llmTesting, setLlmTesting] = useState(false)

  // Load env config on mount
  useEffect(() => {
    const load = async () => {
      try {
        const env: EnvConfigResponse = await api.getEnvConfig()
        if (env.success && env.has_env) {
          if (env.email?.provider === 'gmail' || env.email?.provider === 'outlook') {
            setOauthProvider(env.email.provider as 'gmail' | 'outlook')
            if (env.email.configured) {
              setOauthConfigured(true)
              if (!forceOAuthReconnect) {
                onConnected()
                if (env.llm?.has_api_key || IS_CLOUD) {
                  setLlmHasEnv(true)
                  onLlmConfigured()
                  onNext()
                } else {
                  setPhase('llm')
                }
              }
            }
          } else if (env.email) {
            const e = env.email
            setForm(prev => ({
              ...prev,
              imapHost: e.imap_host || prev.imapHost,
              imapPort: e.imap_port || prev.imapPort,
              smtpHost: e.smtp_host || prev.smtpHost,
              smtpPort: e.smtp_port || prev.smtpPort,
              email: e.imap_username || prev.email,
              imapUseSsl: e.imap_use_ssl ?? prev.imapUseSsl,
              smtpUseTls: e.smtp_use_tls ?? prev.smtpUseTls,
              smtpUseSsl: e.smtp_use_ssl ?? prev.smtpUseSsl,
            }))
          }
          if (env.llm?.has_api_key) {
            setLlmHasEnv(true)
            setLlmProvider((env.llm.provider === 'ollama') ? 'ollama' : 'claude')
          }
        }
      } catch { /* ignore */ } finally {
        setEnvLoading(false)
      }
    }
    load()

  }, [forceOAuthReconnect, onConnected, onLlmConfigured, onNext])

  const handleTestConnection = useCallback(async () => {
    if (!form.imapHost || !form.email || !form.password) {
      setError(t('step1_error_fields'))
      return
    }
    setStatus('testing')
    setError(null)
    const params: WizardConnectionParams = {
      imap_host: form.imapHost, imap_port: form.imapPort,
      imap_username: form.email, imap_password: form.password, imap_use_ssl: form.imapUseSsl,
      smtp_host: form.smtpHost, smtp_port: form.smtpPort,
      smtp_username: form.email, smtp_password: form.password,
      smtp_use_tls: form.smtpUseTls, smtp_use_ssl: form.smtpUseSsl,
    }
    try {
      const result = await api.testWizardConnection(params)
      if (result.success) {
        setStatus('success')
        onConnected()
        if (llmHasEnv || IS_CLOUD) {
          onLlmConfigured()
          onNext()
        } else {
          setPhase('llm')
        }
      } else {
        setStatus('error')
        setError(result.imap?.error || result.smtp?.error || t('step1_error_connection'))
      }
    } catch {
      setStatus('error')
      setError(t('step1_error_connection'))
    }
  }, [form, api, onConnected, onLlmConfigured, llmHasEnv, onNext, t])

  const handleOAuthSuccess = useCallback(() => {
    // Use onOAuthComplete (triggers recheckConnection) for interactive OAuth,
    // not onConnected (auto-detection only — no recheck to avoid wizard remount loop)
    ;(onOAuthComplete || onConnected)()
    if (llmHasEnv || IS_CLOUD) {
      onLlmConfigured()
      onNext()
    } else {
      setPhase('llm')
    }
  }, [onConnected, onOAuthComplete, onLlmConfigured, llmHasEnv, onNext])

  const handlePreset = useCallback((preset: EmailPreset) => {
    setActivePreset(preset.name)
    setForm(prev => ({
      ...prev,
      imapHost: preset.imapHost, imapPort: preset.imapPort,
      smtpHost: preset.smtpHost, smtpPort: preset.smtpPort,
      imapUseSsl: preset.imapUseSsl, smtpUseTls: preset.smtpUseTls, smtpUseSsl: preset.smtpUseSsl,
    }))
    setStatus('idle')
    setError(null)
  }, [])

  const handleLlmSubmit = useCallback(async () => {
    if (!llmKey.trim() && llmProvider === 'claude') {
      setError(t('step1_error_api_key'))
      return
    }
    setLlmTesting(true)
    setError(null)
    try {
      await api.testLLMConnection({
        provider: llmProvider,
        api_key: llmProvider === 'claude' ? llmKey : undefined,
        model: llmProvider === 'claude' ? 'claude-haiku-4-5-20251001' : 'llama3',
      })
      onLlmConfigured()
      onNext()
    } catch {
      setError(t('step1_error_llm'))
    } finally {
      setLlmTesting(false)
    }
  }, [llmKey, llmProvider, api, onLlmConfigured, onNext, t])

  const handleFormChange = useCallback((field: string, value: string | number | boolean) => {
    setForm(prev => ({ ...prev, [field]: value }))
    setStatus('idle')
    setError(null)
  }, [])

  // ─── Phase: Connect ───
  if (phase === 'connect') {
    return (
      <div className="s1-connect-phase">
        {envLoading ? (
          <div className="po-loading-center">
            <div className="po-spinner" />
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{t('step1_loading_config')}</span>
          </div>
        ) : oauthConfigured && !forceOAuthReconnect ? (
          <div className="s1-oauth-success">
            <div className="s1-oauth-success-icon" aria-hidden="true">
              <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
                <circle cx="16" cy="16" r="14" fill="currentColor" opacity="0.12"/>
                <path d="M10 16l4 4 8-10" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
              </svg>
              {/* Sparkles — 6 particules dirigées radialement */}
              <span className="s1-oauth-sparkle" style={{ ['--a' as string]: '0deg' }} aria-hidden="true" />
              <span className="s1-oauth-sparkle" style={{ ['--a' as string]: '60deg' }} aria-hidden="true" />
              <span className="s1-oauth-sparkle" style={{ ['--a' as string]: '120deg' }} aria-hidden="true" />
              <span className="s1-oauth-sparkle" style={{ ['--a' as string]: '180deg' }} aria-hidden="true" />
              <span className="s1-oauth-sparkle" style={{ ['--a' as string]: '240deg' }} aria-hidden="true" />
              <span className="s1-oauth-sparkle" style={{ ['--a' as string]: '300deg' }} aria-hidden="true" />
            </div>
            <div className="s1-oauth-success-text">
              {t('step1_oauth_configured', { provider: oauthProvider === 'gmail' ? 'Gmail' : 'Outlook' })}
            </div>
          </div>
        ) : (
          <>
            {forceOAuthReconnect && (
              <div className="s1-reconnect-note" role="status">
                {t('step1_reconnect_scope_note', 'Reconnectez Gmail et acceptez toutes les autorisations Google demandées pour relancer la synchronisation.')}
              </div>
            )}
            {/* OAuth — chemin principal */}
            <div className="s1-oauth-hero">
              <ConnectGmailButton accountId="default" onConnected={handleOAuthSuccess} />
              <ConnectOutlookButton accountId="default" onConnected={handleOAuthSuccess} />
            </div>

            {/* Connexion manuelle — tout dans l'accordéon */}
            <button
              type="button"
              className="s1-advanced-toggle"
              onClick={() => setShowAdvanced(v => !v)}
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true" style={{ transform: showAdvanced ? 'rotate(90deg)' : 'none', transition: 'transform .2s ease' }}>
                <path d="M6 3l5 5-5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              {t('step1_manual_toggle')}
            </button>

            {showAdvanced && (
              <div className="s1-advanced-fields">
                {/* Presets */}
                <div className="po-presets">
                  {EMAIL_PRESETS.map(p => (
                    <button
                      key={p.name}
                      className={`po-preset-btn${activePreset === p.name ? ' active' : ''}`}
                      onClick={() => handlePreset(p)}
                    >
                      {p.name}
                    </button>
                  ))}
                </div>

                <div className="po-imap-form">
                  <div className="po-form-field">
                    <label htmlFor="imap-email">{t('step1_label_email')}</label>
                    <input
                      id="imap-email"
                      type="email" value={form.email}
                      onChange={e => handleFormChange('email', e.target.value)}
                      placeholder="you@example.com"
                    />
                  </div>
                  <div className="po-form-field">
                    <label htmlFor="imap-password">{t('step1_label_password')}</label>
                    <input
                      id="imap-password"
                      type="password" value={form.password}
                      onChange={e => handleFormChange('password', e.target.value)}
                      placeholder={t('step1_placeholder_password')}
                    />
                  </div>
                  <div className="po-form-row">
                    <div className="po-form-field">
                      <label htmlFor="imap-host">{t('step1_label_imap')}</label>
                      <input
                        id="imap-host"
                        type="text" value={form.imapHost}
                        onChange={e => handleFormChange('imapHost', e.target.value)}
                        placeholder="imap.example.com"
                      />
                    </div>
                    <div className="po-form-field small">
                      <label htmlFor="imap-port">{t('step1_label_port')}</label>
                      <input
                        id="imap-port"
                        type="number" value={form.imapPort}
                        onChange={e => handleFormChange('imapPort', parseInt(e.target.value) || 993)}
                      />
                    </div>
                  </div>
                  <div className="po-form-row">
                    <div className="po-form-field">
                      <label htmlFor="smtp-host">{t('step1_label_smtp')}</label>
                      <input
                        id="smtp-host"
                        type="text" value={form.smtpHost}
                        onChange={e => handleFormChange('smtpHost', e.target.value)}
                        placeholder="smtp.example.com"
                      />
                    </div>
                    <div className="po-form-field small">
                      <label htmlFor="smtp-port">{t('step1_label_port')}</label>
                      <input
                        id="smtp-port"
                        type="number" value={form.smtpPort}
                        onChange={e => handleFormChange('smtpPort', parseInt(e.target.value) || 587)}
                      />
                    </div>
                  </div>
                  <div className="po-form-options">
                    <label className="po-checkbox">
                      <input type="checkbox" checked={form.imapUseSsl} onChange={e => handleFormChange('imapUseSsl', e.target.checked)} />
                      <span>IMAP SSL</span>
                    </label>
                    <label className="po-checkbox">
                      <input type="checkbox" checked={form.smtpUseTls} onChange={e => handleFormChange('smtpUseTls', e.target.checked)} />
                      <span>SMTP TLS</span>
                    </label>
                  </div>
                </div>

                {error && <div className="po-status-msg error">{error}</div>}

                <button
                  className="po-btn-primary"
                  onClick={handleTestConnection}
                  disabled={status === 'testing'}
                >
                  {status === 'testing' ? (
                    <><span className="po-spinner" /> {t('step1_testing')}</>
                  ) : t('step1_connect_btn')}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    )
  }

  // ─── Phase: LLM Config ───
  if (phase === 'llm') {
    return (
      <>
        <h2 className="po-section-title">{t('step1_llm_title')}</h2>
        <p className="po-section-subtitle">
          {t('step1_llm_subtitle')}
        </p>

        <div className="po-llm-config">
          <h4>{t('step1_llm_provider')}</h4>
          <div className="po-provider-radios">
            <button
              className={`po-provider-radio${llmProvider === 'claude' ? ' active' : ''}`}
              onClick={() => setLlmProvider('claude')}
            >
              Claude (Anthropic)
            </button>
            <button
              className={`po-provider-radio${llmProvider === 'ollama' ? ' active' : ''}`}
              onClick={() => setLlmProvider('ollama')}
            >
              Ollama (local)
            </button>
          </div>

          {llmProvider === 'claude' && (
            <div className="po-form-field" style={{ marginBottom: 0 }}>
              <label htmlFor="llm-api-key">{t('step1_llm_key')}</label>
              <input
                id="llm-api-key"
                type="password"
                value={llmKey}
                onChange={e => { setLlmKey(e.target.value); setError(null) }}
                placeholder="sk-ant-..."
              />
            </div>
          )}
        </div>

        {error && <div className="po-status-msg error">{error}</div>}

        <div style={{ marginTop: 16 }}>
          <button
            className="po-btn-primary"
            onClick={handleLlmSubmit}
            disabled={llmTesting}
          >
            {llmTesting ? (
              <><span className="po-spinner" /> {t('step1_verifying')}</>
            ) : t('step1_validate')}
          </button>
        </div>
      </>
    )
  }

  // Phase 'llm' is the last phase — no more scanning/results
  return null
}
