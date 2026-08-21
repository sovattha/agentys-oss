import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import './UpdateBell.css'

interface UpdateEntry {
  version: string
  date: string
  itemKeys: string[]
}

const CHANGELOG: UpdateEntry[] = [
  {
    version: '1.0.0',
    date: '2026-06-09',
    itemKeys: [
      'whats_new_v100_1',
      'whats_new_v100_2',
      'whats_new_v100_3',
      'whats_new_v100_4',
      'whats_new_v100_5',
      'whats_new_v100_6',
      'whats_new_v100_7',
    ],
  },
  {
    version: '0.3.0',
    date: '2026-05-06',
    itemKeys: [
      'whats_new_v030_1',
      'whats_new_v030_2',
      'whats_new_v030_3',
      'whats_new_v030_4',
      'whats_new_v030_5',
      'whats_new_v030_6',
      'whats_new_v030_7',
    ],
  },
  {
    version: '0.2.0',
    date: '2026-04-16',
    itemKeys: [
      'whats_new_v020_1',
      'whats_new_v020_2',
      'whats_new_v020_3',
      'whats_new_v020_4',
    ],
  },
  {
    version: '0.1.0',
    date: '2026-02-05',
    itemKeys: [
      'whats_new_v010_1',
      'whats_new_v010_2',
      'whats_new_v010_3',
      'whats_new_v010_4',
      'whats_new_v010_5',
      'whats_new_v010_6',
    ],
  },
]

const LATEST_VERSION = CHANGELOG[0]?.version ?? ''
const LAST_SEEN_KEY = 'agentys_whats_new_last_seen'

function loadLastSeen(): string | null {
  try { return localStorage.getItem(LAST_SEEN_KEY) } catch { return null }
}

export function UpdateBell({ sidebar = false }: { sidebar?: boolean }) {
  const { t } = useTranslation('common')
  const [isOpen, setIsOpen] = useState(false)
  const bellRef = useRef<HTMLDivElement>(null)
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({})
  const [lastSeen, setLastSeen] = useState<string | null>(() => loadLastSeen())
  const hasNew = LATEST_VERSION !== '' && lastSeen !== LATEST_VERSION

  // Calcule la position du dropdown en fixed quand on est dans la sidebar
  // pour éviter que overflow:hidden de la sidebar ne coupe le panel
  const computeDropdownStyle = () => {
    if (!bellRef.current) return
    const rect = bellRef.current.getBoundingClientRect()
    if (sidebar) {
      const MARGIN = 8
      // Décalage gauche pour ne pas chevaucher les badges "Action" de la liste email
      const LEFT_OFFSET = 16
      // QA 2026-05-19 — Bug #15: previously hardcoded 400px for the CSS
      // max-height AND this positioning math. On short viewports (~720px)
      // the panel could still extend past the bottom and clip the oldest
      // entry. Mirror the CSS cap (`min(400px, calc(100vh - 24px))`) here so
      // the `top` we compute matches the height the panel actually renders.
      const effectiveHeight = Math.min(400, window.innerHeight - 2 * MARGIN)
      // Si pas assez de place en bas, ouvre vers le haut
      const spaceBelow = window.innerHeight - rect.top
      const top = spaceBelow < effectiveHeight + MARGIN
        ? Math.max(MARGIN, window.innerHeight - effectiveHeight - MARGIN)
        : Math.max(MARGIN, rect.top)
      setDropdownStyle({
        position: 'fixed',
        top,
        left: rect.right + LEFT_OFFSET,
        zIndex: 9999,
        maxHeight: effectiveHeight,
      })
    } else {
      setDropdownStyle({})
    }
  }

  // Ouvre/ferme avec recalcul de position. Mark le changelog courant comme
  // vu au moment de l'ouverture — le dot disparaît jusqu'à la prochaine
  // bump de version dans CHANGELOG.
  const openDropdown = () => {
    computeDropdownStyle()
    setIsOpen(true)
    if (LATEST_VERSION && lastSeen !== LATEST_VERSION) {
      try { localStorage.setItem(LAST_SEEN_KEY, LATEST_VERSION) } catch { /* ignore */ }
      setLastSeen(LATEST_VERSION)
    }
  }

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return
    const handleClick = (e: MouseEvent) => {
      if (bellRef.current && !bellRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [isOpen])

  // Close on Escape key (BUG-003 — QA 2026-04-10)
  // Uses capture phase to intercept BEFORE useAppShortcuts which calls handleCloseModal.
  // This prevents Escape from propagating to App's global handler when the panel is open,
  // avoiding potential state conflicts that caused BUG-001 blank screen crashes.
  useEffect(() => {
    if (!isOpen) return
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopImmediatePropagation()
        e.preventDefault()
        setIsOpen(false)
      }
    }
    window.addEventListener('keydown', handleEscape, true) // capture phase
    return () => window.removeEventListener('keydown', handleEscape, true)
  }, [isOpen])

  const dropdown = isOpen ? (
    <div className="update-bell-dropdown" style={dropdownStyle}>
      <div className="update-bell-header">
        <span>{t('whats_new')}</span>
      </div>
      <div className="update-bell-content">
        {CHANGELOG.map((entry) => (
          <div key={entry.version} className="update-entry">
            <div className="update-entry-header">
              <span className="update-entry-version">v{entry.version}</span>
              <span className="update-entry-date">{entry.date}</span>
            </div>
            <ul className="update-entry-list">
              {entry.itemKeys.map((key, i) => (
                <li key={i}>{t(key)}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  ) : null

  return (
    <div
      className={`update-bell${sidebar ? ' update-bell-sidebar' : ''}`}
      ref={bellRef}
      // En mode sidebar : click-only — le hover interfère avec le premier clic (ouvre avant le click, puis le click ferme)
      onMouseEnter={!sidebar ? openDropdown : undefined}
      onMouseLeave={!sidebar ? () => setIsOpen(false) : undefined}
    >
      <button
        className={`${sidebar ? 'sidebar-item' : 'header-icon-btn'} update-bell-btn ${hasNew ? 'has-new' : ''}`}
        onClick={() => {
          if (isOpen) setIsOpen(false)
          else openDropdown()
        }}
        title={t('whats_new')}
        aria-label={t('whats_new')}
        aria-expanded={isOpen}
      >
        <svg aria-hidden="true" className={sidebar ? 'sidebar-icon' : ''} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
          <path d="M11 6a13 13 0 0 0 8.4-2.8A1 1 0 0 1 21 4v12a1 1 0 0 1-1.6.8A13 13 0 0 0 11 14H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"/>
          <path d="M6 14a12 12 0 0 0 2.4 7.2 2 2 0 0 0 3.2-2.4A8 8 0 0 1 10 14"/>
          <path d="M8 6v8"/>
        </svg>
        {hasNew && <span className="update-bell-dot" />}
        {sidebar && <span className="sidebar-label">{t('whats_new')}</span>}
      </button>

      {/* En mode sidebar: portal au body pour échapper au overflow:hidden de la sidebar */}
      {sidebar
        ? createPortal(dropdown, document.body)
        : dropdown
      }
    </div>
  )
}
