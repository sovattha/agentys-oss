/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'

const STORAGE_KEY = 'agentys_tooltips_enabled'

interface TooltipSettingsContextValue {
  tooltipsEnabled: boolean
  setTooltipsEnabled: (enabled: boolean) => void
}

const TooltipSettingsContext = createContext<TooltipSettingsContextValue | null>(null)

export function TooltipSettingsProvider({ children }: { children: ReactNode }) {
  const [tooltipsEnabled, setTooltipsEnabledState] = useState(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === null ? true : stored === 'true'
  })

  const setTooltipsEnabled = useCallback((enabled: boolean) => {
    setTooltipsEnabledState(enabled)
    localStorage.setItem(STORAGE_KEY, String(enabled))
  }, [])

  // Listen for storage changes from other tabs/windows
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && e.newValue !== null) {
        setTooltipsEnabledState(e.newValue === 'true')
      }
    }

    window.addEventListener('storage', handleStorageChange)
    return () => window.removeEventListener('storage', handleStorageChange)
  }, [])

  return (
    <TooltipSettingsContext.Provider value={{ tooltipsEnabled, setTooltipsEnabled }}>
      {children}
    </TooltipSettingsContext.Provider>
  )
}

export function useTooltipSettings(): TooltipSettingsContextValue {
  const context = useContext(TooltipSettingsContext)
  if (!context) {
    // Return default values if not wrapped in provider (for backward compatibility)
    return {
      tooltipsEnabled: true,
      setTooltipsEnabled: () => {},
    }
  }
  return context
}
