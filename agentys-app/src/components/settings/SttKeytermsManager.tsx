/**
 * SttKeytermsManager — Settings → Productivity → "Voice dictation".
 *
 * Single CRUD list of user-defined custom keyterms (nicknames, jargon,
 * phonetic variants). Biased into Deepgram's decoder via the `keyterm`
 * query parameter at /api/transcribe time — no model retraining.
 *
 * Project-label auto-injection was removed (2026-05-11) per UX feedback —
 * the auto-seeded list was noisy and users preferred curating their own
 * vocabulary explicitly.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { addKeyterm, getKeyterms, removeKeyterm } from '../../services/stt'
import { CloseIcon } from '../icons/ActionIcons'

// Effective limit dictation can boost. The backend is the source of truth
// (sent on GET as `cap`); this is only the fallback for older API responses.
const DEFAULT_CUSTOM_KEYTERM_CAP = 50

export function SttKeytermsManager() {
  const { t } = useTranslation('settings')
  const [custom, setCustom] = useState<string[]>([])
  const [cap, setCap] = useState(DEFAULT_CUSTOM_KEYTERM_CAP)
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // At the cap, a new word would never reach the decoder, so the backend
  // rejects it — block the add field client-side and explain why.
  const atCap = custom.length >= cap

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getKeyterms()
      setCustom(data.custom)
      setCap(data.cap ?? DEFAULT_CUSTOM_KEYTERM_CAP)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('stt_keyterms_load_error'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => { load() }, [load])

  const handleAdd = useCallback(async () => {
    const term = draft.trim()
    if (!term || busy || atCap) return
    setBusy(true)
    setError(null)
    try {
      const res = await addKeyterm(term)
      setCustom(res.custom)
      setDraft('')
    } catch (e) {
      setError(e instanceof Error ? e.message : t('stt_keyterms_generic_error'))
    } finally {
      setBusy(false)
    }
  }, [draft, busy, atCap, t])

  const handleRemove = useCallback(async (term: string) => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const res = await removeKeyterm(term)
      setCustom(res.custom)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('stt_keyterms_generic_error'))
    } finally {
      setBusy(false)
    }
  }, [busy, t])

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleAdd()
    }
  }

  return (
    <section className="settings-section stt-keyterms">
      <p className="stt-keyterms-description">
        {t('stt_keyterms_description')}
      </p>

      {error && (
        <div className="stt-keyterms-error" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <div className="stt-keyterms-loading">{t('common:loading')}</div>
      ) : (
        <div className="stt-keyterms-block">
          <div className="stt-keyterms-block-label">
            <span>{t('stt_keyterms_custom_label')}</span>
            {custom.length > 0 && (
              <span className="stt-keyterms-block-count">
                {custom.length} / {cap}
              </span>
            )}
          </div>

          <div className="stt-keyterms-add-row">
            <input
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={t('stt_keyterms_input_placeholder')}
              disabled={busy || atCap}
              className="settings-input stt-keyterms-input"
              aria-label={t('stt_keyterms_input_aria')}
            />
            <button
              type="button"
              onClick={handleAdd}
              disabled={busy || atCap || !draft.trim()}
              className="stt-keyterms-add-btn"
            >
              {t('common:add')}
            </button>
          </div>
          {atCap && (
            <p className="stt-keyterms-limit-hint" role="note">
              {t('stt_keyterms_limit_hint', { count: cap })}
            </p>
          )}

          {custom.length === 0 ? (
            <div className="stt-keyterms-empty">
              {t('stt_keyterms_custom_empty')}
            </div>
          ) : (
            <div className="stt-keyterms-chips">
              {custom.map((term) => (
                <span key={`custom-${term}`} className="stt-keyterm-chip stt-keyterm-chip--custom">
                  <span>{term}</span>
                  <button
                    type="button"
                    onClick={() => handleRemove(term)}
                    disabled={busy}
                    aria-label={t('stt_keyterms_remove_aria', { term })}
                    className="stt-keyterm-chip-remove"
                  >
                    <CloseIcon size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
