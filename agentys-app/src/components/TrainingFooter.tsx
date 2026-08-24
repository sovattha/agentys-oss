/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

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
