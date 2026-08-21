import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { ComposeEmailForm, type ComposeEmailRequest } from './ComposeEmailForm'
import { apiClient, type ComposeEmailResponse } from '../../services/api'
import { getWebSocketClient } from '../../services/websocket'
import { safeRandomUUID } from '../../utils/uuid'
import { useAnimatedUnmount } from '../../hooks/useAnimatedUnmount'
import { copyToClipboard } from '../../utils/clipboard'
import { CloseIcon } from '../icons/ActionIcons'
import './ComposeEmailModal.css'

const STREAM_FIRST_CHUNK_TIMEOUT_MS = 10000

interface ComposeEmailModalProps {
  isOpen: boolean
  onClose: () => void
  onEmailComposed?: (draftContent: string) => void
}

export function ComposeEmailModal({
  isOpen,
  onClose,
  onEmailComposed,
}: ComposeEmailModalProps) {
  const { t } = useTranslation('compose')
  const LOADING_MESSAGE_KEYS = ['compose_loading_1', 'compose_loading_2', 'compose_loading_3', 'compose_loading_4'] as const
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [generatedDraft, setGeneratedDraft] = useState<string | null>(null)
  const [streamingText, setStreamingText] = useState<string>('')
  const [loadingMessageKey, setLoadingMessageKey] = useState<typeof LOADING_MESSAGE_KEYS[number]>(LOADING_MESSAGE_KEYS[0])
  const [elapsedTime, setElapsedTime] = useState(0)
  const abortControllerRef = useRef<AbortController | null>(null)
  const wsUnsubscribeRef = useRef<(() => void) | null>(null)
  const streamWatchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const cleanupStream = () => {
    wsUnsubscribeRef.current?.()
    wsUnsubscribeRef.current = null
    if (streamWatchdogRef.current) {
      clearTimeout(streamWatchdogRef.current)
      streamWatchdogRef.current = null
    }
  }

  const resetAndClose = () => {
    cleanupStream()
    setError(null)
    setGeneratedDraft(null)
    setStreamingText('')
    onClose()
  }

  useEffect(() => {
    return () => {
      cleanupStream()
    }
  }, [])

  const { shouldRender, isClosing, handleClose } = useAnimatedUnmount(isOpen, resetAndClose)

  // Escape key closes the modal (NEW-F fix)
  useEffect(() => {
    if (!shouldRender) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        handleClose()
      }
    }
    window.addEventListener('keydown', onKeyDown, true)
    return () => window.removeEventListener('keydown', onKeyDown, true)
  }, [shouldRender, handleClose])

  // Update loading message and elapsed time during generation
  useEffect(() => {
    if (!isLoading) {
      setElapsedTime(0)
      setLoadingMessageKey(LOADING_MESSAGE_KEYS[0])
      return
    }

    const startTime = Date.now()
    const interval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startTime) / 1000)
      setElapsedTime(elapsed)

      // Cycle through messages every 8 seconds
      const messageIndex = Math.min(
        Math.floor(elapsed / 8),
        LOADING_MESSAGE_KEYS.length - 1
      )
      setLoadingMessageKey(LOADING_MESSAGE_KEYS[messageIndex])
    }, 1000)

    return () => clearInterval(interval)
  }, [isLoading])

  const handleSubmit = async (data: ComposeEmailRequest) => {
    setIsLoading(true)
    setError(null)
    setStreamingText('')
    setGeneratedDraft(null)
    abortControllerRef.current = new AbortController()

    const ws = getWebSocketClient()
    const useStreaming = ws.isConnected()
    const composeId = useStreaming ? safeRandomUUID() : undefined

    if (composeId) {
      const unsubscribe = ws.subscribe((event) => {
        if (event.type === 'draft_chunk' && event.data.email_id === composeId) {
          setStreamingText((prev) => prev + event.data.chunk)
          if (streamWatchdogRef.current) {
            clearTimeout(streamWatchdogRef.current)
            streamWatchdogRef.current = null
          }
        } else if (event.type === 'draft_complete' && event.data.email_id === composeId) {
          const finalDraft = event.data.draft
          cleanupStream()
          setGeneratedDraft(finalDraft)
          onEmailComposed?.(finalDraft)
          setIsLoading(false)
        } else if (event.type === 'draft_error' && event.data.email_id === composeId) {
          cleanupStream()
          setError(event.data.error || t('generation_failed'))
          setIsLoading(false)
        }
      })
      wsUnsubscribeRef.current = unsubscribe

      streamWatchdogRef.current = setTimeout(() => {
        cleanupStream()
        setError(t('generation_failed'))
        setIsLoading(false)
      }, STREAM_FIRST_CHUNK_TIMEOUT_MS)
    }

    try {
      const response = await apiClient.composeEmail(
        data.to,
        data.subject,
        data.instructions,
        data.useHistory,
        undefined,
        composeId
      )

      const respMaybeStreaming = response as ComposeEmailResponse & {
        status?: string
        compose_id?: string
      }
      if (composeId && respMaybeStreaming.status === 'processing') {
        return
      }

      cleanupStream()
      if (response.success && response.final_draft) {
        setGeneratedDraft(response.final_draft.content)
        onEmailComposed?.(response.final_draft.content)
      } else {
        setError(t('generation_failed'))
      }
      setIsLoading(false)
    } catch (err) {
      cleanupStream()
      if (err instanceof Error && err.name === 'AbortError') {
        setError(t('generation_cancelled'))
      } else {
        setError(err instanceof Error ? err.message : t('generic_error'))
      }
      setIsLoading(false)
    } finally {
      abortControllerRef.current = null
    }
  }

  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    cleanupStream()
    setIsLoading(false)
  }

  const handleCopyDraft = async () => {
    if (generatedDraft) {
      await copyToClipboard(generatedDraft)
    }
  }

  if (!shouldRender) {
    return null
  }

  return (
    <div className="compose-modal-overlay" onClick={handleClose}>
      <div className={`compose-modal${isClosing ? ' closing' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="compose-modal-header">
          <h2>{t('new_message')}</h2>
          <button className="close-button" onClick={handleClose} type="button" aria-label={t('close')}>
            <CloseIcon />
          </button>
        </div>

        <div className="compose-modal-content">
          {error && (
            <div className="compose-error" role="alert">
              {error}
            </div>
          )}

          {isLoading && !streamingText && (
            <div className="compose-loading-overlay">
              <div className="compose-loading-content">
                <div className="compose-loading-spinner" />
                <p className="compose-loading-message">{t(loadingMessageKey)}</p>
                <p className="compose-loading-time">
                  {elapsedTime > 0 && `${elapsedTime}s`}
                </p>
                <button
                  type="button"
                  className="btn-cancel-generation"
                  onClick={handleCancel}
                >
                  {t('cancel')}
                </button>
              </div>
            </div>
          )}

          {!generatedDraft && streamingText ? (
            <div className="generated-draft generated-draft-streaming">
              <h3>{t('draft_generated')}</h3>
              <div className="draft-preview draft-preview-streaming">
                {streamingText}
                <span className="streaming-cursor" aria-hidden="true">▍</span>
              </div>
            </div>
          ) : generatedDraft ? (
            <div className="generated-draft">
              <h3>{t('draft_generated')}</h3>
              <div className="draft-preview">
                {generatedDraft}
              </div>
              <div className="draft-actions">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={handleCopyDraft}
                >
                  {t('copy')}
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setGeneratedDraft(null)}
                >
                  {t('edit')}
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={handleClose}
                >
                  {t('close')}
                </button>
              </div>
            </div>
          ) : (
            <ComposeEmailForm
              onSubmit={handleSubmit}
              onCancel={handleClose}
              isLoading={isLoading}
            />
          )}
        </div>
      </div>
    </div>
  )
}
