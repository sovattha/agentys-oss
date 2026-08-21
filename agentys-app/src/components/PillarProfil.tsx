import { useTranslation } from 'react-i18next';
import type { ProfilData } from '../types/training';
import './TrainingCommon.css';
import './PillarProfil.css';

interface PillarProfilProps {
  profil: ProfilData;
  onUpdate: (field: string, value: string) => void;
}

export function PillarProfil({ profil, onUpdate }: PillarProfilProps) {
  const { t } = useTranslation('agents');

  return (
    <div className="pillar-profil">
      <div className="pillar-section-header">
        <span className="pillar-section-title">{t('training_section_identity')}</span>
        <span className="pillar-section-subtitle">{t('training_section_identity_subtitle')}</span>
      </div>

      <div className="pillar-profil-form">
        <div className="pillar-field">
          <label className="pillar-field-label">{t('training_label_fullname')}</label>
          <input
            className="pillar-field-input"
            value={profil.nom_complet}
            onChange={e => onUpdate('nom_complet', e.target.value)}
            placeholder={t('training_placeholder_name')}
          />
        </div>

        <div className="pillar-field-row">
          <div className="pillar-field">
            <label className="pillar-field-label">{t('training_label_company')}</label>
            <input
              className="pillar-field-input"
              value={profil.entreprise}
              onChange={e => onUpdate('entreprise', e.target.value)}
              placeholder={t('training_placeholder_company')}
            />
          </div>
          <div className="pillar-field">
            <label className="pillar-field-label">{t('training_label_job_title')}</label>
            <input
              className="pillar-field-input"
              value={profil.poste}
              onChange={e => onUpdate('poste', e.target.value)}
              placeholder={t('training_placeholder_job_title')}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
