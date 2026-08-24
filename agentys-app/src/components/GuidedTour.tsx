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

import { useEffect, useLayoutEffect, useState, useRef, useCallback } from 'react'
import type { GuidedTourState } from '../hooks/useGuidedTour'
import './GuidedTour.css'

interface GuidedTourProps {
  tour: GuidedTourState
}

const PADDING = 8
const TOOLTIP_GAP = 12
const VIEWPORT_MARGIN = 12

export function GuidedTour({ tour }: GuidedTourProps) {
  const [spotlightRect, setSpotlightRect] = useState<DOMRect | null>(null)
  const [isClosing, setIsClosing] = useState(false)
  const tooltipRef = useRef<HTMLDivElement>(null)

  const animateOut = useCallback((callback: () => void) => {
    setIsClosing(true)
    setTimeout(() => {
      setIsClosing(false)
      callback()
    }, 200)
  }, [])

  const handleSkip = useCallback(() => {
    animateOut(tour.skip)
  }, [animateOut, tour.skip])

  const handleNext = useCallback(() => {
    if (tour.currentStep === tour.totalSteps - 1) {
      animateOut(tour.next)
    } else {
      tour.next()
    }
  }, [animateOut, tour])

  useEffect(() => {
    if (!tour.isActive || !tour.step) return

    const findTarget = () => {
      const el = document.querySelector(tour.step!.target)
      if (el) {
        const rect = el.getBoundingClientRect()
        setSpotlightRect(rect)
      }
    }

    findTarget()

    // Recalculate on resize
    window.addEventListener('resize', findTarget)
    return () => window.removeEventListener('resize', findTarget)
  }, [tour.isActive, tour.step, tour.currentStep])

  // Clamp tooltip within viewport bounds after render
  useLayoutEffect(() => {
    if (!tooltipRef.current || !spotlightRect) return
    const tooltip = tooltipRef.current
    const rect = tooltip.getBoundingClientRect()

    // If tooltip overflows below viewport, flip above the spotlight target
    if (rect.bottom > window.innerHeight - VIEWPORT_MARGIN) {
      tooltip.style.top = 'auto'
      tooltip.style.bottom = `${window.innerHeight - spotlightRect.top + PADDING + TOOLTIP_GAP}px`
    }

    // If tooltip overflows right of viewport, align to right edge
    if (rect.right > window.innerWidth - VIEWPORT_MARGIN) {
      tooltip.style.left = `${window.innerWidth - rect.width - VIEWPORT_MARGIN}px`
    }
  }, [spotlightRect, tour.currentStep])

  if ((!tour.isActive && !isClosing) || !tour.step || !spotlightRect) return null

  // Tooltip position based on step.position
  const tooltipStyle: React.CSSProperties = {}
  if (tour.step.position === 'right') {
    tooltipStyle.left = spotlightRect.right + PADDING + TOOLTIP_GAP
    tooltipStyle.top = spotlightRect.top
  } else if (tour.step.position === 'bottom') {
    tooltipStyle.left = spotlightRect.left
    tooltipStyle.top = spotlightRect.bottom + PADDING + TOOLTIP_GAP
  } else {
    tooltipStyle.left = spotlightRect.left
    tooltipStyle.bottom = window.innerHeight - spotlightRect.top + PADDING + TOOLTIP_GAP
  }

  return (
    <div className={`guided-tour-overlay${isClosing ? ' gt-closing' : ''}`}>
      <div className="guided-tour-backdrop" onClick={handleSkip} />
      <div
        className="guided-tour-spotlight"
        style={{
          left: spotlightRect.left - PADDING,
          top: spotlightRect.top - PADDING,
          width: spotlightRect.width + PADDING * 2,
          height: spotlightRect.height + PADDING * 2,
        }}
      />
      <div
        className="guided-tour-tooltip"
        ref={tooltipRef}
        style={tooltipStyle}
      >
        <div className="guided-tour-step-label">
          Étape {tour.currentStep + 1}/{tour.totalSteps}
        </div>
        <h3>{tour.step.title}</h3>
        <p>{tour.step.description}</p>
        <div className="guided-tour-footer">
          <div className="guided-tour-dots">
            {Array.from({ length: tour.totalSteps }, (_, i) => (
              <div
                key={i}
                className={`guided-tour-dot${
                  i === tour.currentStep ? ' active' : i < tour.currentStep ? ' done' : ''
                }`}
              />
            ))}
          </div>
          <div className="guided-tour-btns">
            <button className="guided-tour-btn-skip" onClick={handleSkip}>
              Passer
            </button>
            <button className="guided-tour-btn-next" onClick={handleNext}>
              {tour.currentStep === tour.totalSteps - 1 ? 'Terminer' : 'Suivant'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
