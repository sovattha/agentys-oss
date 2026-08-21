import { useTranslation } from 'react-i18next';
import { Button } from './ui/button';
import './TrainingCommon.css';

interface TrainingFooterProps {
  hasChanges: boolean;
  saving: boolean;
  onSave: () => void;
  onReset: () => void;
}

export function TrainingFooter({ hasChanges, saving, onSave, onReset }: TrainingFooterProps) {
  const { t } = useTranslation('agents');

  return (
    <div className="training-footer">
      <div className="training-actions">
        <Button
          variant="outline"
          onClick={onReset}
          disabled={!hasChanges || saving}
          type="button"
        >
          {t('training_btn_cancel')}
        </Button>
        <Button
          onClick={onSave}
          disabled={!hasChanges || saving}
          type="button"
        >
          {saving ? t('training_btn_saving') : t('training_btn_save')}
        </Button>
      </div>
    </div>
  );
}
