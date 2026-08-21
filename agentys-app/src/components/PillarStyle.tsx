import { useMemo, type MutableRefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { useAccountSignature } from '../hooks/useAccountSignature';
import type { ProfilData, ContactStyleProfile, DefaultStyleSettings, FormalityLevel, FormatSettings, LanguageVariant } from '../types/training';
import { StyleSettingsSection } from './StyleSettingsSection';
import { FormatSection } from './FormatSection';
import { ContactStyleEditor } from './ContactStyleEditor';
import './TrainingCommon.css';
import './PillarStyle.css';

interface DraftRuleItem {
  id: string;
  rule_text: string;
  category: string;
  scope: string;
  contact: string;
  confidence: number;
  active: boolean;
  created_at?: string;
  [key: string]: unknown;
}

interface PillarStyleProps {
  profil: ProfilData;
  onUpdateProfil: (field: string, value: string) => void;
  rules: DraftRuleItem[];
  onToggleRule: (id: string, active: boolean) => void;
  onDeleteRule: (id: string) => void;
  contactStyles?: ContactStyleProfile[];
  defaultStyle?: DefaultStyleSettings;
  onSaveContactStyle?: (data: {
    contact_email: string;
    formality_override: FormalityLevel | null;
    preferred_greeting: string | null;
    preferred_closing: string | null;
    langue_variante?: LanguageVariant | null;
    langue?: string | null;
    nickname?: string | null;
  }) => Promise<{ error?: string }>;
  onDeleteContactStyle?: (email: string) => void;
  onUpdateDefaultStyle?: (field: string, value: string) => void;
  pendingCardSaveRef?: MutableRefObject<(() => Promise<{ error?: string } | void>) | null>;
}

const DEFAULT_FORMAT: FormatSettings = {
  longueur: 'moyen',
  complexite: 'standard',
};

export function PillarStyle({
  profil,
  onUpdateProfil,
  rules,
  onToggleRule,
  onDeleteRule,
  contactStyles,
  defaultStyle,
  onSaveContactStyle,
  onDeleteContactStyle,
  onUpdateDefaultStyle,
  pendingCardSaveRef,
}: PillarStyleProps) {
  const { t } = useTranslation('agents');

  const globalRules = useMemo(() => rules.filter(r => r.scope !== 'contact'), [rules]);
  const contactRules = useMemo(() => rules.filter(r => r.scope === 'contact'), [rules]);
  const { text: signatureText } = useAccountSignature();

  return (
    <div className="pillar-style">
      {/* Section 1 : Format de rédaction */}
      <div className="pillar-section-header">
        <span className="pillar-section-title">{t('format_section_title')}</span>
      </div>

      <FormatSection
        format={profil.format || DEFAULT_FORMAT}
        onUpdate={onUpdateProfil}
        signatureText={signatureText}
        closingText={defaultStyle?.preferred_closings?.[0] ?? null}
      />

      {/* Section 2 : Style d'écriture par défaut */}
      <div className="pillar-style-divider" />

      <div className="pillar-section-header">
        <span className="pillar-section-title">{t('style_section_settings')}</span>
      </div>

      <StyleSettingsSection
        defaultStyle={defaultStyle}
        onUpdateDefaultStyle={onUpdateDefaultStyle}
        globalRules={globalRules}
        onToggleRule={onToggleRule}
        onDeleteRule={onDeleteRule}
      />

      {/* Section 3 : Style d'écriture par contact */}
      {onSaveContactStyle && onDeleteContactStyle && (
        <>
          <div className="pillar-style-divider" />

          <div className="pillar-section-header">
            <span className="pillar-section-title">{t('style_section_contact_styles')}</span>
          </div>
          <ContactStyleEditor
            contacts={contactStyles || []}
            onSave={onSaveContactStyle}
            onDelete={onDeleteContactStyle}
            contactRules={contactRules}
            onToggleRule={onToggleRule}
            onDeleteRule={onDeleteRule}
            pendingCardSaveRef={pendingCardSaveRef}
          />
        </>
      )}

    </div>
  );
}
