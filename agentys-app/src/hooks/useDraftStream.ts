import { useEffect, useState } from 'react'
import { subscribeDraftStream } from './useWebSocketSync'

export interface DraftStreamCritiqueView {
  decision: 'valid' | 'reject'
  score: number
  motive?: string
}

export interface DraftStreamView {
  stageName: string | null
  versionIndex: number
  critique: DraftStreamCritiqueView | null
  crossfadeKey: number
  progressPercent: number
  isComplete: boolean
}

const NEUTRAL_VIEW: DraftStreamView = {
  stageName: null,
  versionIndex: 1,
  critique: null,
  crossfadeKey: 0,
  progressPercent: 0,
  isComplete: false,
}

/**
 * Subscribe to the global draft-stream bus and expose derived state for the
 * given `sourceId` (email.id in reply mode, composeId in compose mode).
 *
 * Stays inert when `isActive` is false so idle composers do not react to
 * events from a concurrent generation elsewhere in the app.
 *
 * The hook does NOT track `accumulatedText` because each surface keeps its
 * own editable body (Reply: `draftBody`, Compose: `body`). Consumers listen
 * to `subscribeDraftStream` directly for the text when they need to mirror
 * it into their editor — this hook only handles the storytelling metadata
 * shared by ThoughtStream, RecapBanner and the pipeline disclosure.
 */
export function useDraftStream(sourceId: string | null, isActive: boolean): DraftStreamView {
  const [view, setView] = useState<DraftStreamView>(NEUTRAL_VIEW)

  useEffect(() => {
    if (!isActive || !sourceId) {
      // Reset view so a leftover critique from a previous generation does not
      // leak into the current idle surface.
      setView(NEUTRAL_VIEW)
      return
    }

    // Also reset at the start of each active cycle — otherwise the critique
    // from a previous generation stays visible until the first WS event.
    setView(NEUTRAL_VIEW)

    const unsub = subscribeDraftStream((streamState) => {
      if (streamState.emailId !== sourceId) return

      setView((prev) => {
        const nextVersionIndex = streamState.versionIndex
        const versionChanged = nextVersionIndex !== prev.versionIndex
        const critique: DraftStreamCritiqueView | null = streamState.critique
          ? {
              decision: streamState.critique.decision,
              score: streamState.critique.score,
              motive: streamState.critique.motive,
            }
          : prev.critique

        return {
          stageName: streamState.stageName ?? prev.stageName,
          versionIndex: nextVersionIndex,
          critique,
          crossfadeKey: versionChanged ? prev.crossfadeKey + 1 : prev.crossfadeKey,
          progressPercent: streamState.progressPercent ?? prev.progressPercent,
          isComplete: streamState.isComplete,
        }
      })
    })

    return () => {
      unsub()
    }
  }, [sourceId, isActive])

  return view
}
