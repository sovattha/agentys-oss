import { useState, useCallback } from 'react'
import { useFocusTrap } from './useFocusTrap'

export interface ModalState {
  showSettings: boolean
  showMyStyle: boolean
  showAccounts: boolean
  showShortcutsHelp: boolean
  showLabelLibrary: boolean
  showSnippetLibrary: boolean
  showCommandPalette: boolean
  showComposeModal: boolean
  showNewMessage: boolean
  showMonthlyRecap: boolean
  showTraining: boolean
  showSupportPanel: boolean
  showLearningDashboard: boolean
  showMeetingReminders: boolean
  closingModal: string | null
}

export function useModals() {
  const [showSettings, setShowSettings] = useState(false)
  const [showMyStyle, setShowMyStyle] = useState(false)
  const [showAccounts, setShowAccounts] = useState(false)
  const [showShortcutsHelp, setShowShortcutsHelp] = useState(false)
  const [showLabelLibrary, setShowLabelLibrary] = useState(false)
  const [showSnippetLibrary, setShowSnippetLibrary] = useState(false)
  const [showCommandPalette, setShowCommandPalette] = useState(false)
  const [showComposeModal, setShowComposeModal] = useState(false)
  const [showNewMessage, setShowNewMessage] = useState(false)
  const [showMonthlyRecap, setShowMonthlyRecap] = useState(false)
  const [showTraining, setShowTraining] = useState(false)
  const [showSupportPanel, setShowSupportPanel] = useState(false)
  const [showLearningDashboard, setShowLearningDashboard] = useState(false)
  const [showMeetingReminders, setShowMeetingReminders] = useState(false)
  const [closingModal, setClosingModal] = useState<string | null>(null)

  // Focus traps for accessible modals
  const settingsTrapRef = useFocusTrap(showSettings)
  const myStyleTrapRef = useFocusTrap(showMyStyle)
  const accountsTrapRef = useFocusTrap(showAccounts)
  const trainingTrapRef = useFocusTrap(showTraining)
  const learningTrapRef = useFocusTrap(showLearningDashboard)

  // Animate modal close: add 'closing' class, then unmount after animation
  const closeWithAnimation = useCallback((setter: (v: boolean) => void, modalId: string) => {
    setClosingModal(modalId)
    setTimeout(() => {
      setter(false)
      setClosingModal(null)
    }, 150)
  }, [])

  return {
    // State
    showSettings, setShowSettings,
    showMyStyle, setShowMyStyle,
    showAccounts, setShowAccounts,
    showShortcutsHelp, setShowShortcutsHelp,
    showLabelLibrary, setShowLabelLibrary,
    showSnippetLibrary, setShowSnippetLibrary,
    showCommandPalette, setShowCommandPalette,
    showComposeModal, setShowComposeModal,
    showNewMessage, setShowNewMessage,
    showMonthlyRecap, setShowMonthlyRecap,
    showTraining, setShowTraining,
    showSupportPanel, setShowSupportPanel,
    showLearningDashboard, setShowLearningDashboard,
    showMeetingReminders, setShowMeetingReminders,
    closingModal,
    // Focus traps
    settingsTrapRef,
    myStyleTrapRef,
    accountsTrapRef,
    trainingTrapRef,
    learningTrapRef,
    // Actions
    closeWithAnimation,
  }
}
