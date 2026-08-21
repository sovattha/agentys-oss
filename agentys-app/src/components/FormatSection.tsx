import { useTranslation } from 'react-i18next';
import type {
  FormatSettings,
  EmailLength,
  WritingComplexity,
} from '../types/training';
import { buildFormatPreviewEmail } from '../utils/formatPreview';

interface FormatSectionProps {
  format: FormatSettings;
  onUpdate: (field: string, value: string) => void;
  signatureText?: string | null;
  closingText?: string | null;
}

const LENGTH_OPTIONS: { value: EmailLength; labelKey: string }[] = [
  { value: 'concis', labelKey: 'format_length_concis' },
  { value: 'moyen', labelKey: 'format_length_moyen' },
  { value: 'detaille', labelKey: 'format_length_detaille' },
];

const COMPLEXITY_OPTIONS: { value: WritingComplexity; labelKey: string }[] = [
  { value: 'accessible', labelKey: 'format_complexity_accessible' },
  { value: 'standard', labelKey: 'format_complexity_standard' },
  { value: 'elabore', labelKey: 'format_complexity_elabore' },
];

function SegmentedControl({ options, value, onChange, t, tooltips }: {
  options: { value: string; labelKey: string }[];
  value: string;
  onChange: (v: string) => void;
  t: (key: string) => string;
  tooltips?: Record<string, string>;
}) {
  return (
    <div className="style-emotion-control">
      {options.map(opt => (
        <button
          key={opt.value}
          type="button"
          className={`style-emotion-option${value === opt.value ? ' active' : ''}`}
          onClick={() => onChange(opt.value)}
          title={tooltips?.[opt.value] || undefined}
        >
          {t(opt.labelKey)}
        </button>
      ))}
    </div>
  );
}

export function FormatSection({ format, onUpdate, signatureText, closingText }: FormatSectionProps) {
  const { t } = useTranslation('agents');

  const lengthTooltips: Record<string, string> = {
    concis: t('format_length_tooltip_concis'),
    moyen: t('format_length_tooltip_moyen'),
    detaille: t('format_length_tooltip_detaille'),
  };
  const complexityTooltips: Record<string, string> = {
    accessible: t('format_complexity_tooltip_accessible'),
    standard: t('format_complexity_tooltip_standard'),
    elabore: t('format_complexity_tooltip_elabore'),
  };

  const preview = buildFormatPreviewEmail(
    t,
    format.longueur,
    format.complexite,
    closingText ?? null,
    signatureText ?? null,
  );

  return (
    <div className="style-settings">
      <div className="pillar-field">
        <label className="pillar-field-label">{t('format_length')}</label>
        <SegmentedControl
          options={LENGTH_OPTIONS}
          value={format.longueur}
          onChange={v => onUpdate('format.longueur', v as EmailLength)}
          t={t}
          tooltips={lengthTooltips}
        />
        <span className="pillar-field-hint">{t('format_length_hint')}</span>
      </div>

      <div className="pillar-field">
        <label className="pillar-field-label">{t('format_complexity')}</label>
        <SegmentedControl
          options={COMPLEXITY_OPTIONS}
          value={format.complexite}
          onChange={v => onUpdate('format.complexite', v as WritingComplexity)}
          t={t}
          tooltips={complexityTooltips}
        />
        <span className="pillar-field-hint">{t('format_complexity_hint')}</span>
      </div>

      {/* Preview */}
      <div className="format-preview">
        <span className="format-preview-label">{t('format_preview_label')}</span>
        <div className="format-preview-question">
          {t('format_preview_question')}
        </div>
        <div className="format-preview-answer">
          {preview.split('\n').map((line, i) => (
            <span key={i}>{line}<br /></span>
          ))}
        </div>
      </div>
    </div>
  );
}
