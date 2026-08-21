import { useTranslation } from 'react-i18next';
import type { DefaultStyleSettings } from '../types/training';
import { InlineRule } from './InlineRule';
import { StyleObservedFromOutbox } from './StyleObservedFromOutbox';
import { GreetingInput } from './GreetingInput';

interface DraftRuleItem {
  id: string;
  rule_text: string;
  confidence: number;
  active: boolean;
  [key: string]: unknown;
}

interface StyleSettingsProps {
  defaultStyle?: DefaultStyleSettings;
  onUpdateDefaultStyle?: (field: string, value: string) => void;
  globalRules?: DraftRuleItem[];
  onToggleRule?: (id: string, active: boolean) => void;
  onDeleteRule?: (id: string) => void;
  /** Account ID (DB int) pour afficher le style observé depuis l'outbox (issue #187) */
  accountId?: number | null;
}

// Issue #187: les sliders Formalité + Niveau d'émotion ont été supprimés ; le
// ton est inféré depuis l'outbox (StyleInferenceService +
// StyleObservedFromOutbox).
//
// 2026-06-23: le picker « Reply language » par défaut a AUSSI été retiré. Les
// réponses miroir déjà la langue de l'email entrant (détection) et la saveur
// régionale est apprise du style de l'utilisateur (few-shot outbox), donc le
// picker était redondant + trompeur (il ne forçait pas, il départageait). La
// variante reste réglable PAR CONTACT dans ContactStyleEditor. Les champs
// `langue`/`langue_variante` du profil subsistent (défaut Auto) et restent
// sérialisés dans le KB.
export function StyleSettingsSection({ defaultStyle, onUpdateDefaultStyle, globalRules, onToggleRule, onDeleteRule, accountId }: StyleSettingsProps) {
  const { t } = useTranslation('agents');

  return (
    <div className="style-settings">
      {accountId !== undefined && accountId !== null && (
        <StyleObservedFromOutbox accountId={accountId} />
      )}

      {onUpdateDefaultStyle && (
        <div className="style-greetings-block">
          <span className="pillar-field-hint">{t('style_greetings_hint')}</span>
          <div className="pillar-field-row">
            <div className="pillar-field">
              <label className="pillar-field-label">{t('style_greeting_formal')}</label>
              <GreetingInput
                value={defaultStyle?.preferred_greetings?.[0] || ''}
                placeholder={t('style_greeting_formal_placeholder', 'Dear {first_name},')}
                ariaLabel={t('style_greeting_formal')}
                onCommit={next => onUpdateDefaultStyle('preferred_greeting', next)}
              />
            </div>
            <div className="pillar-field">
              <label className="pillar-field-label">{t('style_closing_formal')}</label>
              <GreetingInput
                value={defaultStyle?.preferred_closings?.[0] || ''}
                placeholder={t('style_closing_placeholder_formal')}
                ariaLabel={t('style_closing_formal')}
                onCommit={next => onUpdateDefaultStyle('preferred_closing', next)}
              />
            </div>
          </div>
          <div className="pillar-field-row">
            <div className="pillar-field">
              <label className="pillar-field-label">{t('style_greeting_casual')}</label>
              <GreetingInput
                value={defaultStyle?.preferred_greetings?.[1] || ''}
                placeholder={t('style_greeting_casual_placeholder', 'Hey {first_name},')}
                ariaLabel={t('style_greeting_casual')}
                onCommit={next => onUpdateDefaultStyle('preferred_greeting_casual', next)}
              />
            </div>
            <div className="pillar-field">
              <label className="pillar-field-label">{t('style_closing_casual')}</label>
              <GreetingInput
                value={defaultStyle?.preferred_closings?.[1] || ''}
                placeholder={t('style_closing_placeholder_casual')}
                ariaLabel={t('style_closing_casual')}
                onCommit={next => onUpdateDefaultStyle('preferred_closing_casual', next)}
              />
            </div>
          </div>
        </div>
      )}

      {globalRules && globalRules.length > 0 && onToggleRule && onDeleteRule && (
        <div className="style-inline-rules">
          <span className="style-inline-rules-title">{t('style_learned_rules_title')}</span>
          {globalRules.map(rule => (
            <InlineRule key={rule.id} rule={rule} onToggle={onToggleRule} onDelete={onDeleteRule} />
          ))}
        </div>
      )}
    </div>
  );
}
