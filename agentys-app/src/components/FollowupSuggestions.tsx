import { useState, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient, type CommitmentSuggestion } from '../services/api'
import './FollowupSuggestions.css'

interface FollowupSuggestionsProps {
  /** Email ID to fetch suggestions for, or undefined for all pending */
  emailId?: string
  /** Inline commitments from preview response (before send) */
  previewCommitments?: Array<{ description: string; deadline?: string | null }>
  /** Called after a suggestion is accepted */
  onAccepted?: (suggestionId: string, followupId: string) => void
}

export function FollowupSuggestions({
  emailId,
  previewCommitments,
  onAccepted,
}: FollowupSuggestionsProps) {
  const { t } = useTranslation('common')
  const [suggestions, setSuggestions] = useState<CommitmentSuggestion[]>([])
  const [expanded, setExpanded] = useState(true)
  const [loading, setLoading] = useState<Record<string, boolean>>({})
  const [calendarToggles, setCalendarToggles] = useState<Record<string, boolean>>({})

  // Fetch suggestions from backend
  useEffect(() => {
    // If we have preview commitments, don't fetch from backend
    if (previewCommitments && previewCommitments.length > 0) return

    let cancelled = false
    const fetchSuggestions = async () => {
      try {
        const resp = await apiClient.getSuggestions(emailId, 'pending')
        if (!cancelled) {
          setSuggestions(resp.suggestions ?? [])
        }
      } catch {
        // Silently fail — suggestions are non-critical
      }
    }

    fetchSuggestions()
    return () => { cancelled = true }
  }, [emailId, previewCommitments])

  // Convert preview commitments to display format
  const displayItems: Array<{
    id: string
    description: string
    deadline?: string | null
    status: 'pending' | 'accepted' | 'rejected'
    isPreview: boolean
  }> = previewCommitments?.length
    ? previewCommitments.map((c, i) => ({
        id: `preview-${i}`,
        description: c.description,
        deadline: c.deadline,
        status: 'pending' as const,
        isPreview: true,
      }))
    : suggestions.map(s => ({
        id: s.id,
        description: s.description,
        deadline: s.deadline,
        status: s.status,
        isPreview: false,
      }))

  const handleAccept = useCallback(async (id: string) => {
    if (loading[id]) return
    setLoading(prev => ({ ...prev, [id]: true }))
    try {
      const syncToCal = calendarToggles[id] ?? false
      const result = await apiClient.acceptSuggestion(id, syncToCal)
      if (result.success) {
        setSuggestions(prev =>
          prev.map(s => s.id === id ? { ...s, status: 'accepted' } : s)
        )
        onAccepted?.(id, result.followup_id)
      } else {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: { message: t('toasts.action_failed'), type: 'error', duration: 6000 },
        }))
      }
    } catch {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: t('toasts.action_failed'), type: 'error', duration: 6000 },
      }))
    } finally {
      setLoading(prev => ({ ...prev, [id]: false }))
    }
  }, [loading, calendarToggles, onAccepted, t])

  const handleReject = useCallback(async (id: string) => {
    if (loading[id]) return
    setLoading(prev => ({ ...prev, [id]: true }))
    try {
      const result = await apiClient.rejectSuggestion(id)
      if (result.success) {
        setSuggestions(prev =>
          prev.map(s => s.id === id ? { ...s, status: 'rejected' } : s)
        )
      } else {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: { message: t('toasts.action_failed'), type: 'error', duration: 6000 },
        }))
      }
    } catch {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: t('toasts.action_failed'), type: 'error', duration: 6000 },
      }))
    } finally {
      setLoading(prev => ({ ...prev, [id]: false }))
    }
  }, [loading, t])

  // Don't render if nothing to show
  if (displayItems.length === 0) return null

  const pendingCount = displayItems.filter(i => i.status === 'pending').length

  return (
    <div className="followup-suggestions">
      <button
        className="followup-suggestions-header"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        type="button"
      >
        <span className="followup-suggestions-icon">✨</span>
        <span className="followup-suggestions-title" role="heading" aria-level={4}>
          {t('commitments_detected')}
        </span>
        {pendingCount > 0 && (
          <span className="followup-suggestions-badge">{pendingCount}</span>
        )}
        <span className={`followup-suggestions-chevron ${expanded ? 'expanded' : ''}`}>
          &#x25B8;
        </span>
      </button>

      {expanded && (
        <div className="followup-suggestions-list">
          {displayItems.map(item => (
            <div key={item.id} className="followup-suggestion-item">
              <div className="followup-suggestion-content">
                <div className="followup-suggestion-description">
                  {item.description}
                </div>
                {item.deadline && (
                  <div className="followup-suggestion-deadline">
                    {t('deadline_label')}: <span className="deadline-value">{item.deadline}</span>
                  </div>
                )}
                {!item.isPreview && item.status === 'pending' && (
                  <label className="followup-suggestion-calendar-toggle">
                    <input
                      type="checkbox"
                      checked={calendarToggles[item.id] ?? false}
                      onChange={e =>
                        setCalendarToggles(prev => ({
                          ...prev,
                          [item.id]: e.target.checked,
                        }))
                      }
                    />
                    {t('add_to_calendar')}
                  </label>
                )}
              </div>

              <div className="followup-suggestion-actions">
                {item.status === 'pending' && !item.isPreview ? (
                  <>
                    <button
                      className="followup-suggestion-btn accept"
                      onClick={() => handleAccept(item.id)}
                      disabled={loading[item.id]}
                    >
                      {t('accept')}
                    </button>
                    <button
                      className="followup-suggestion-btn reject"
                      onClick={() => handleReject(item.id)}
                      disabled={loading[item.id]}
                    >
                      {t('ignore')}
                    </button>
                  </>
                ) : item.isPreview ? (
                  <span className="followup-suggestion-status accepted">
                    {t('preview_label')}
                  </span>
                ) : (
                  <span className={`followup-suggestion-status ${item.status}`}>
                    {item.status === 'accepted' ? t('accepted') : t('ignored')}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
