import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { DiplomaIcon } from '../icons/AgentysIcons'
import { ChevronRightIcon } from '../icons/ActionIcons'
import { ApprentissagesModal } from './ApprentissagesModal'
import { getAvailableSpecialties, type SpecialtySummary } from '../../services/specialties'
import './SpecialtiesSection.css'

export function SpecialtiesSection() {
  const { t } = useTranslation('agents')
  const DOMAIN_NAMES: Record<string, string> = {
    'marketing-growth': 'Marketing',
    'legal-qc': t('common:domain_legal'),
    'real-estate-qc': t('common:domain_real_estate'),
  }
  const [specialties, setSpecialties] = useState<SpecialtySummary[]>([])
  const [showModal, setShowModal] = useState(false)

  const loadSpecialties = useCallback(() => {
    getAvailableSpecialties()
      .then(setSpecialties)
      .catch(() => setSpecialties([]))
  }, [])

  useEffect(() => { loadSpecialties() }, [loadSpecialties])

  const active = specialties.filter(s => s.is_active)
  const title = t('specialties_your_title')

  const desc = active.length > 0
    ? active.map(s => DOMAIN_NAMES[s.id] ?? s.name).join(', ') + ' ' + t('expert_context_active')
    : t('expert_context_hint')

  return (
    <>
      <section className="settings-section">
        <button
          className="settings-training-card"
          onClick={() => setShowModal(true)}
          type="button"
        >
          <span className="training-card-icon spec-icon-wrap">
            <DiplomaIcon size={24} />
            <span className="training-card-pulse" />
          </span>
          <span className="training-card-body">
            <span className="training-card-title">
              {title}
            </span>
            <span className="training-card-desc">{desc}</span>
          </span>
          <span className="training-card-arrow">
            <ChevronRightIcon size={16} />
          </span>
        </button>
      </section>

      <ApprentissagesModal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        onChanged={loadSpecialties}
      />
    </>
  )
}
