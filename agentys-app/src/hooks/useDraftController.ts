import { useState, useCallback, useRef, useEffect } from 'react'
import { apiClient, type PendingDraft } from '../services/api'

export interface DraftController {
  selectedDraft: PendingDraft | null
  setSelectedDraft: React.Dispatch<React.SetStateAction<PendingDraft | null>>
  selectedDraftId: string | null
  setSelectedDraftId: React.Dispatch<React.SetStateAction<string | null>>
  isLoadingDraft: boolean
  setIsLoadingDraft: React.Dispatch<React.SetStateAction<boolean>>
  selectedDraftIndex: number
  setSelectedDraftIndex: React.Dispatch<React.SetStateAction<number>>
  draftsRef: React.MutableRefObject<PendingDraft[]>
  draftDetailReady: boolean
  draftCount: number
  setDraftCount: React.Dispatch<React.SetStateAction<number>>
  handleDraftSelect: (draft: PendingDraft) => Promise<void>
}

export function useDraftController(): DraftController {
  const [selectedDraft, setSelectedDraft] = useState<PendingDraft | null>(null)
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null)
  const [isLoadingDraft, setIsLoadingDraft] = useState(false)
  const [selectedDraftIndex, setSelectedDraftIndex] = useState(-1)
  const draftsRef = useRef<PendingDraft[]>([])
  const [draftDetailReady, setDraftDetailReady] = useState(false)
  const [draftCount, setDraftCount] = useState(0)

  // Trigger detail-ready for drafts tab
  useEffect(() => {
    if (selectedDraft) {
      setDraftDetailReady(false)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setDraftDetailReady(true))
      })
    } else {
      setDraftDetailReady(false)
    }
  }, [selectedDraft])

  // Load full draft details when a draft is selected
  const selectedDraftIdRef = useRef<string | null>(null)
  const handleDraftSelect = useCallback(async (draft: PendingDraft) => {
    selectedDraftIdRef.current = draft.id
    setSelectedDraftId(draft.id)
    // Show panel immediately with list data (optimistic), then enrich with full API data
    setSelectedDraft(draft)
    setIsLoadingDraft(true)
    try {
      // Load full draft details including draft_v1, critique, email_body
      const fullDraft = await apiClient.getPendingDraft(draft.id)
      // Guard against race: only apply if this draft is still selected
      if (selectedDraftIdRef.current === draft.id) {
        setSelectedDraft(fullDraft ?? draft)
      }
    } catch (err) {
      console.error('Failed to load draft details:', err)
      // draft from list already set above — nothing to do
    } finally {
      if (selectedDraftIdRef.current === draft.id) {
        setIsLoadingDraft(false)
      }
    }
  }, [])

  return {
    selectedDraft, setSelectedDraft,
    selectedDraftId, setSelectedDraftId,
    isLoadingDraft, setIsLoadingDraft,
    selectedDraftIndex, setSelectedDraftIndex,
    draftsRef,
    draftDetailReady,
    draftCount, setDraftCount,
    handleDraftSelect,
  }
}
