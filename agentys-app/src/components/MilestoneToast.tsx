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

import { useEffect, useState } from 'react'
import type { Milestone } from '../hooks/useMilestones'
import { CloseIcon } from './icons/ActionIcons'
import './MilestoneToast.css'

interface MilestoneToastProps {
  milestone: Milestone
  onDismiss: () => void
}

export function MilestoneToast({ milestone, onDismiss }: MilestoneToastProps) {
  const [exiting, setExiting] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => {
      setExiting(true)
      setTimeout(onDismiss, 300)
    }, 5000)
    return () => clearTimeout(timer)
  }, [onDismiss])

  const handleClose = () => {
    setExiting(true)
    setTimeout(onDismiss, 300)
  }

  return (
    <div className="milestone-toasts-container">
      <div className={`milestone-toast${exiting ? ' exiting' : ''}`}>
        <div className="mt-icon">{milestone.icon}</div>
        <div className="mt-content">
          <div className="mt-title">{milestone.title}</div>
          <div className="mt-desc">{milestone.description}</div>
        </div>
        <button className="mt-close" onClick={handleClose}><CloseIcon /></button>
        <div className="mt-progress" />
      </div>
    </div>
  )
}
