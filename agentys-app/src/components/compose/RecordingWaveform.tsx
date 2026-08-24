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

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import './RecordingWaveform.css'

interface RecordingWaveformProps {
  isRecording: boolean
  audioLevels: number[]
}

function buildWavePath(levels: number[], w: number, h: number): string {
  const mid = h / 2
  const n = levels.length
  if (n < 2) return `M0,${mid}L${w},${mid}Z`
  const pts = levels.map((l, i) => ({ x: (i / (n - 1)) * w, amp: l * (mid - 1.5) }))
  const seg = (
    a: { x: number; y: number }, b: { x: number; y: number },
    c: { x: number; y: number }, d: { x: number; y: number },
  ) => {
    const c1x = b.x + (c.x - a.x) / 6; const c1y = b.y + (c.y - a.y) / 6
    const c2x = c.x - (d.x - b.x) / 6; const c2y = c.y - (d.y - b.y) / 6
    return `C${c1x},${c1y} ${c2x},${c2y} ${c.x},${c.y}`
  }
  const top = pts.map(p => ({ x: p.x, y: mid - p.amp }))
  let d = `M${top[0].x},${top[0].y}`
  for (let i = 0; i < top.length - 1; i++)
    d += seg(top[Math.max(0, i - 1)], top[i], top[i + 1], top[Math.min(top.length - 1, i + 2)])
  const bot = pts.map(p => ({ x: p.x, y: mid + p.amp }))
  d += `L${bot[bot.length - 1].x},${bot[bot.length - 1].y}`
  for (let i = bot.length - 1; i > 0; i--)
    d += seg(bot[Math.min(bot.length - 1, i + 1)], bot[i], bot[i - 1], bot[Math.max(0, i - 2)])
  return d + 'Z'
}

export function RecordingWaveform({ isRecording, audioLevels }: RecordingWaveformProps) {
  // Snapshot the last "live" frame so the drain animation has a real shape to drain.
  const lastAudioLevelsRef = useRef<number[]>(new Array(48).fill(0.1))
  useEffect(() => {
    if (isRecording && audioLevels.some(l => l > 0.15)) {
      lastAudioLevelsRef.current = [...audioLevels]
    }
  }, [isRecording, audioLevels])

  // Keep the strip mounted ~1.1s after recording stops so the "Liquid
  // Crystallization" exit animation runs to completion (without it, the
  // unmount happens 1 frame after `isRecording` flips to false → no exit).
  const [waveExiting, setWaveExiting] = useState(false)
  const wasRecordingRef = useRef(false)
  useLayoutEffect(() => {
    if (wasRecordingRef.current && !isRecording) {
      setWaveExiting(true)
      const t = setTimeout(() => setWaveExiting(false), 1100)
      wasRecordingRef.current = false
      return () => clearTimeout(t)
    }
    if (isRecording) wasRecordingRef.current = true
  }, [isRecording])

  if (!isRecording && !waveExiting) return null

  const levels = waveExiting ? lastAudioLevelsRef.current : audioLevels
  // Floor the amplitude at ~0.32 so the aurora always has visible body even
  // during silence — at the previous floor of 0.1 the wave collapsed to a
  // ~2.5px stripe that read as "nothing rendered" to the user.
  const boosted = levels.map(l => Math.max(0.32, l))
  const path = buildWavePath(boosted, 200, 28)
  const corePath = buildWavePath(boosted.map(l => l * 0.45), 200, 28)

  return (
    <div className={`nmm-rec-strip${waveExiting ? ' nmm-rec-exiting' : ''}`}>
      <div className="nmm-rec-waveform" aria-hidden="true">
        <div className={waveExiting ? 'nmm-wave-svg-wrap nmm-wf-draining' : 'nmm-wave-svg-wrap'}>
          <svg className="nmm-wave-svg" viewBox="0 0 200 28" preserveAspectRatio="none">
            <defs>
              <linearGradient id="nmmGradOuter" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#0d9488" stopOpacity="0.2" />
                <stop offset="50%" stopColor="#2dd4bf" stopOpacity="0.75" />
                <stop offset="100%" stopColor="#0d9488" stopOpacity="0.2" />
              </linearGradient>
              <linearGradient id="nmmGradVert" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#0d9488" stopOpacity="0.25" />
                <stop offset="45%" stopColor="#2dd4bf" stopOpacity="0.9" />
                <stop offset="50%" stopColor="#5eead4" stopOpacity="1" />
                <stop offset="55%" stopColor="#2dd4bf" stopOpacity="0.9" />
                <stop offset="100%" stopColor="#0d9488" stopOpacity="0.25" />
              </linearGradient>
              <linearGradient id="nmmGradCore" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#5eead4" stopOpacity="0" />
                <stop offset="50%" stopColor="#99f6e4" stopOpacity="0.9" />
                <stop offset="100%" stopColor="#5eead4" stopOpacity="0" />
              </linearGradient>
              <filter id="nmmGlow">
                <feGaussianBlur in="SourceGraphic" stdDeviation="1.8" />
              </filter>
            </defs>
            <path d={path} fill="url(#nmmGradOuter)" filter="url(#nmmGlow)" className="nmm-wf-outer" />
            <path d={path} fill="url(#nmmGradVert)" />
            <path d={path} fill="url(#nmmGradOuter)" opacity="0.45" style={{ mixBlendMode: 'screen' }} />
            <path d={corePath} fill="url(#nmmGradCore)" filter="url(#nmmGlow)" className="nmm-wf-core" />
            <path d={corePath} fill="url(#nmmGradCore)" />
            <line x1="0" y1="14" x2="200" y2="14" stroke="#5eead4" strokeOpacity="0.06" strokeWidth="0.5" />
          </svg>
        </div>

        {waveExiting && (
          <div className="nmm-logo-liquid" aria-hidden="true">
            <svg width="28" height="28" viewBox="0 0 32 32" fill="none" overflow="visible">
              <defs>
                <filter id="nmmCG" x="-60%" y="-60%" width="220%" height="220%">
                  <feGaussianBlur in="SourceGraphic" stdDeviation="1.4" result="b" />
                  <feComposite in="SourceGraphic" in2="b" operator="over" />
                </filter>
                <filter id="nmmCGS" x="-150%" y="-150%" width="400%" height="400%">
                  <feGaussianBlur in="SourceGraphic" stdDeviation="3.8" />
                </filter>
                <linearGradient id="nmmFG" x1="0.5" y1="0" x2="0.5" y2="1">
                  <stop offset="0%" stopColor="#0d9488" stopOpacity="0.10" />
                  <stop offset="50%" stopColor="#2dd4bf" stopOpacity="0.22" />
                  <stop offset="100%" stopColor="#0d9488" stopOpacity="0.06" />
                </linearGradient>
              </defs>

              <rect className="nmm-floor-pool"
                x="2" y="27" width="28" height="5" rx="2.5"
                fill="#2dd4bf" filter="url(#nmmCGS)"
              />

              <g className="nmm-burst-group">
                <path className="nmm-cglow"
                  d="M16 29.5 L30.5 29.5 L16 2.5 L1.5 29.5 L16 29.5"
                  stroke="#2dd4bf" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round"
                  fill="none" opacity="0.10" filter="url(#nmmCGS)"
                />
                <path className="nmm-cpath"
                  d="M16 29.5 L30.5 29.5 L16 2.5 L1.5 29.5 L16 29.5"
                  stroke="#5eead4" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"
                  fill="none" opacity="0.40" filter="url(#nmmCG)"
                />
                <path className="nmm-cpath"
                  d="M16 29.5 L30.5 29.5 L16 2.5 L1.5 29.5 L16 29.5"
                  stroke="#2dd4bf" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
                  fill="none"
                />
                <path className="nmm-cpath"
                  d="M16 29.5 L30.5 29.5 L16 2.5 L1.5 29.5 L16 29.5"
                  stroke="#b2f5ea" strokeWidth="0.55" strokeLinecap="round" strokeLinejoin="round"
                  fill="none" opacity="0.85"
                />

                <path className="nmm-cfill"
                  d="M16 2.5 L1.5 29.5 L30.5 29.5 Z"
                  fill="url(#nmmFG)"
                />
                <path className="nmm-cmid"
                  d="M16 12 L8.5 25 L23.5 25 Z"
                  fill="#0d9488" opacity="0.62"
                />
                <path className="nmm-cinner"
                  d="M16 16.5 L11.5 23.5 L20.5 23.5 Z"
                  fill="var(--surface-primary, #f0f1f5)"
                />

                <path className="nmm-burst-flash"
                  d="M16 2.5 L1.5 29.5 L30.5 29.5 Z"
                  fill="#ccfbf1"
                />
              </g>

              <circle className="nmm-apex-micro"
                cx="16" cy="2.5" r="2"
                fill="#99f6e4" filter="url(#nmmCG)"
              />

              <circle className="nmm-burst-ring"
                cx="16" cy="20.5" r="9"
                fill="none" stroke="#2dd4bf" strokeWidth="1.4"
              />
              <circle className="nmm-burst-ring-2"
                cx="16" cy="20.5" r="9"
                fill="none" stroke="#2dd4bf" strokeWidth="0.7" opacity="0.55"
              />

              {([
                { tx: '0px', ty: '-15px' },
                { tx: '11px', ty: '-11px' },
                { tx: '15px', ty: '0px' },
                { tx: '11px', ty: '11px' },
                { tx: '0px', ty: '15px' },
                { tx: '-11px', ty: '11px' },
                { tx: '-15px', ty: '0px' },
                { tx: '-11px', ty: '-11px' },
              ] as Array<{ tx: string; ty: string }>).map((s, i) => (
                <circle key={i}
                  className="nmm-shard"
                  cx="16" cy="20.5" r="1.2"
                  fill="#2dd4bf"
                  style={{ '--tx': s.tx, '--ty': s.ty } as React.CSSProperties}
                />
              ))}
            </svg>
          </div>
        )}
      </div>
    </div>
  )
}
