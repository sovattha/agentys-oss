import { useTranslation } from 'react-i18next';
import { ScoreRing } from './ScoreRing';
import './ThoughtStream.css';

export type StreamStage = 'classification' | 'redaction' | 'optimisation' | 'finalisation';

export interface ThoughtCritique {
  decision: 'valid' | 'reject';
  score: number;
  motive?: string;
}

interface ThoughtStreamProps {
  stageName: StreamStage | string | null;
  versionIndex: number;
  accumulatedText: string;
  critique?: ThoughtCritique;
  classificationLabel?: string;
  classificationTier?: string;
  waitingForEmailBody?: boolean;
  isComplete: boolean;
}

const STAGE_ORDER: StreamStage[] = ['classification', 'redaction', 'optimisation', 'finalisation'];

function stagePosition(active: string | null | undefined): number {
  if (!active) return 0;
  const idx = STAGE_ORDER.indexOf(active as StreamStage);
  return idx < 0 ? 0 : idx;
}

function truncatePreview(text: string, limit = 140): string {
  const cleaned = text.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  if (cleaned.length <= limit) return cleaned;
  return cleaned.slice(0, limit).trimEnd() + '…';
}

export function ThoughtStream({
  stageName,
  versionIndex,
  accumulatedText,
  critique,
  classificationLabel,
  classificationTier,
  waitingForEmailBody = false,
  isComplete,
}: ThoughtStreamProps) {
  const { t } = useTranslation('compose');
  const activeIdx = stagePosition(stageName);
  const preview = truncatePreview(accumulatedText);
  const isRevising = (critique?.decision === 'reject') && stageName === 'redaction' && versionIndex >= 2;
  const motiveKey = critique?.motive || 'default';
  const motiveText = t(`story_motive_${motiveKey}`, { defaultValue: t('story_motive_default') });

  const classificationDone = activeIdx > 0 || isComplete;
  const draftingDone = activeIdx > 1 || isComplete;
  const critiqueDone = activeIdx > 2 || isComplete || !!critique;
  const readingTitle = classificationDone
    ? (classificationLabel
        ? t('story_classified', { label: classificationLabel, tier: classificationTier || t('tier_standard') })
        : t('story_context_ready'))
    : (waitingForEmailBody ? t('story_loading_email_body') : t('story_analyzing_context'));
  const draftingTitle = isRevising
    ? t('story_revising')
    : (preview ? t('story_drafting_live') : t('story_drafting'));
  const critiqueTitle = critique
    ? (critique.decision === 'valid'
        ? t('story_critique_approved')
        : t('story_critique_rejected', { score: critique.score, motive: motiveText }))
    : (activeIdx === 2 ? t('story_critique_active') : t('story_critique_pending'));
  const finishingTitle = isComplete
    ? t('story_ready')
    : (activeIdx === 3 ? t('story_saving_draft') : t('story_finishing'));

  return (
    <ol className="thought-stream" aria-label={t('story_thought_stream_aria', 'Fil de réflexion')}>
      {/* 1. Classification */}
      <li
        className={`thought-step${classificationDone ? ' is-done' : activeIdx === 0 ? ' is-active' : ''}`}
      >
        <span className="thought-marker" aria-hidden="true" />
        <div className="thought-body">
          <div className="thought-title">
            {readingTitle}
          </div>
        </div>
      </li>

      {/* 2. Rédaction V1 (ou Vn si révision) */}
      <li
        className={`thought-step${draftingDone && !isRevising ? ' is-done' : activeIdx === 1 ? ' is-active' : ''}`}
      >
        <span className="thought-marker" aria-hidden="true" />
        <div className="thought-body">
          <div className="thought-title">
            {draftingTitle}
            {versionIndex >= 2 && (
              <span className="thought-version-pill">{t('story_version_label', { n: versionIndex })}</span>
            )}
          </div>
          {preview && (activeIdx === 1 || draftingDone) && (
            <div className="thought-preview">{preview}</div>
          )}
        </div>
      </li>

      {/* 3. Critique — avec ring de score si rendu disponible */}
      <li
        className={`thought-step${critiqueDone && critique?.decision === 'valid' ? ' is-done' : activeIdx === 2 ? ' is-active' : ''}${critique?.decision === 'reject' ? ' is-warn' : ''}`}
      >
        <span className="thought-marker" aria-hidden="true" />
        <div className="thought-body thought-body--with-ring">
          <div className="thought-title">
            {critiqueTitle}
          </div>
          {critique && (
            <ScoreRing
              score={critique.score}
              size={36}
              stroke={3}
              label={t('pipeline_critique')}
            />
          )}
        </div>
      </li>

      {/* 4. Finalisation */}
      <li
        className={`thought-step${isComplete ? ' is-done' : activeIdx === 3 ? ' is-active' : ''}`}
      >
        <span className="thought-marker" aria-hidden="true" />
        <div className="thought-body">
          <div className="thought-title">{finishingTitle}</div>
        </div>
      </li>
    </ol>
  );
}
