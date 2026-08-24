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

import { memo } from 'react'
import { useTranslation } from 'react-i18next'
import type { ActivityItem } from '../types/activity'
import './ActivityPopover.css'

interface ActivityPopoverProps {
  activities: ActivityItem[]
  onMouseEnter: () => void
  onMouseLeave: () => void
}

export const ActivityPopover = memo(function ActivityPopover({
  activities,
  onMouseEnter,
  onMouseLeave,
}: ActivityPopoverProps) {
  const { t } = useTranslation('common')

  if (activities.length === 0) return null

  return (
    <div
      className="activity-popover"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      role="status"
    >
      <div className="activity-popover__header">
        {t('activity_popover_title')}
      </div>
      <div className="activity-popover__list">
        {activities.map(activity => (
          <div key={activity.id} className="activity-popover__item">
            <span className="activity-popover__dot" data-type={activity.type} />
            <span className="activity-popover__label" title={t(activity.label)}>
              {t(activity.label)}
            </span>
            {activity.progress != null && activity.progress > 0 && activity.progress < 100 && (
              <div className="activity-popover__progress">
                <div
                  className="activity-popover__progress-bar"
                  style={{ width: `${activity.progress}%` }}
                />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
})
