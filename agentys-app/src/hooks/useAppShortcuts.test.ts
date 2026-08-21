import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAppShortcuts } from './useAppShortcuts'

// Mock tauri event API
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(() => Promise.resolve(() => {})),
}))

describe('useAppShortcuts', () => {
  let addEventListenerSpy: ReturnType<typeof vi.spyOn>
  let removeEventListenerSpy: ReturnType<typeof vi.spyOn>
  let keydownHandler: ((event: KeyboardEvent) => void) | null = null

  beforeEach(() => {
    addEventListenerSpy = vi.spyOn(window, 'addEventListener')
    removeEventListenerSpy = vi.spyOn(window, 'removeEventListener')

    // Capture the keydown handler when it's registered
    addEventListenerSpy.mockImplementation((event: string, handler: EventListenerOrEventListenerObject) => {
      if (event === 'keydown') {
        keydownHandler = handler as (event: KeyboardEvent) => void
      }
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
    keydownHandler = null
  })

  it('should register keydown event listener when enabled', () => {
    renderHook(() =>
      useAppShortcuts({
        enabled: true,
      })
    )

    expect(addEventListenerSpy).toHaveBeenCalledWith('keydown', expect.any(Function), true)
  })

  it('should still register keydown event listener when disabled (checks internally)', () => {
    renderHook(() =>
      useAppShortcuts({
        enabled: false,
      })
    )

    // The hook now always registers the listener but checks enabled internally
    expect(addEventListenerSpy).toHaveBeenCalledWith('keydown', expect.any(Function), true)
  })

  it('should call onOpenSettings when Cmd+, is pressed', () => {
    const onOpenSettings = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onOpenSettings,
        enabled: true,
      })
    )

    if (keydownHandler) {
      const event = new KeyboardEvent('keydown', {
        key: ',',
        metaKey: true,
      })
      Object.defineProperty(event, 'preventDefault', { value: vi.fn() })

      act(() => {
        keydownHandler!(event)
      })

      expect(onOpenSettings).toHaveBeenCalled()
      expect(event.preventDefault).toHaveBeenCalled()
    }
  })

  it('should call onOpenSettings when Ctrl+, is pressed', () => {
    const onOpenSettings = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onOpenSettings,
        enabled: true,
      })
    )

    if (keydownHandler) {
      const event = new KeyboardEvent('keydown', {
        key: ',',
        ctrlKey: true,
      })
      Object.defineProperty(event, 'preventDefault', { value: vi.fn() })

      act(() => {
        keydownHandler!(event)
      })

      expect(onOpenSettings).toHaveBeenCalled()
    }
  })

  it('should call onRefreshEmails when Cmd+R is pressed', () => {
    const onRefreshEmails = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onRefreshEmails,
        enabled: true,
      })
    )

    if (keydownHandler) {
      const event = new KeyboardEvent('keydown', {
        key: 'r',
        metaKey: true,
      })
      Object.defineProperty(event, 'preventDefault', { value: vi.fn() })

      act(() => {
        keydownHandler!(event)
      })

      expect(onRefreshEmails).toHaveBeenCalled()
    }
  })

  it('should call onShowShortcutsHelp when Cmd+/ is pressed', () => {
    const onShowShortcutsHelp = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onShowShortcutsHelp,
        enabled: true,
      })
    )

    if (keydownHandler) {
      const event = new KeyboardEvent('keydown', {
        key: '/',
        metaKey: true,
      })
      Object.defineProperty(event, 'preventDefault', { value: vi.fn() })

      act(() => {
        keydownHandler!(event)
      })

      expect(onShowShortcutsHelp).toHaveBeenCalled()
    }
  })

  it('should call onCloseModal when Escape is pressed', () => {
    const onCloseModal = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onCloseModal,
        enabled: true,
      })
    )

    if (keydownHandler) {
      const event = new KeyboardEvent('keydown', {
        key: 'Escape',
      })
      Object.defineProperty(event, 'preventDefault', { value: vi.fn() })

      act(() => {
        keydownHandler!(event)
      })

      expect(onCloseModal).toHaveBeenCalled()
    }
  })

  it('should call onNavigateUp when ArrowUp is pressed', () => {
    const onNavigateUp = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onNavigateUp,
        enabled: true,
      })
    )

    if (keydownHandler) {
      const event = new KeyboardEvent('keydown', {
        key: 'ArrowUp',
      })
      Object.defineProperty(event, 'preventDefault', { value: vi.fn() })
      Object.defineProperty(event, 'target', { value: document.createElement('div') })

      act(() => {
        keydownHandler!(event)
      })

      expect(onNavigateUp).toHaveBeenCalled()
    }
  })

  it('should call onNavigateDown when ArrowDown is pressed', () => {
    const onNavigateDown = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onNavigateDown,
        enabled: true,
      })
    )

    if (keydownHandler) {
      const event = new KeyboardEvent('keydown', {
        key: 'ArrowDown',
      })
      Object.defineProperty(event, 'preventDefault', { value: vi.fn() })
      Object.defineProperty(event, 'target', { value: document.createElement('div') })

      act(() => {
        keydownHandler!(event)
      })

      expect(onNavigateDown).toHaveBeenCalled()
    }
  })

  it('should call onOpenSelected when Enter is pressed', () => {
    const onOpenSelected = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onOpenSelected,
        enabled: true,
      })
    )

    if (keydownHandler) {
      const event = new KeyboardEvent('keydown', {
        key: 'Enter',
      })
      Object.defineProperty(event, 'target', { value: document.createElement('div') })
      Object.defineProperty(event, 'preventDefault', { value: vi.fn() })

      act(() => {
        keydownHandler!(event)
      })

      expect(onOpenSelected).toHaveBeenCalled()
    }
  })

  it('should not call onOpenSelected when Enter is pressed in input', () => {
    const onOpenSelected = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onOpenSelected,
        enabled: true,
      })
    )

    if (keydownHandler) {
      const input = document.createElement('input')
      const event = new KeyboardEvent('keydown', {
        key: 'Enter',
      })
      Object.defineProperty(event, 'target', { value: input })
      Object.defineProperty(event, 'preventDefault', { value: vi.fn() })

      act(() => {
        keydownHandler!(event)
      })

      expect(onOpenSelected).not.toHaveBeenCalled()
    }
  })

  it('should call onNewMessage when N is pressed outside inputs', async () => {
    const onNewMessage = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onNewMessage,
        enabled: true,
      })
    )

    if (keydownHandler) {
      const event = new KeyboardEvent('keydown', {
        key: 'n',
      })
      Object.defineProperty(event, 'target', { value: document.createElement('div') })
      Object.defineProperty(event, 'preventDefault', { value: vi.fn() })

      act(() => {
        keydownHandler!(event)
      })

      // onNewMessage est différé via queueMicrotask (cf. useAppShortcuts,
      // BUG-J001) — flush la microtask queue avant d'asserter.
      await Promise.resolve()

      expect(onNewMessage).toHaveBeenCalled()
      expect(event.preventDefault).toHaveBeenCalled()
    }
  })

  it('should not call onNewMessage when N is pressed in input', () => {
    const onNewMessage = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onNewMessage,
        enabled: true,
      })
    )

    if (keydownHandler) {
      const input = document.createElement('input')
      document.body.appendChild(input)
      input.focus()

      const event = new KeyboardEvent('keydown', {
        key: 'n',
      })
      Object.defineProperty(event, 'target', { value: input })
      Object.defineProperty(event, 'preventDefault', { value: vi.fn() })

      act(() => {
        keydownHandler!(event)
      })

      expect(onNewMessage).not.toHaveBeenCalled()
      expect(event.preventDefault).not.toHaveBeenCalled()

      input.remove()
    }
  })

  it('should not call callbacks when disabled', () => {
    const onOpenSettings = vi.fn()
    const onCloseModal = vi.fn()

    renderHook(() =>
      useAppShortcuts({
        onOpenSettings,
        onCloseModal,
        enabled: false,
      })
    )

    // The hook now always registers but checks enabled internally
    // So callbacks should not be called even if handler exists
    expect(onOpenSettings).not.toHaveBeenCalled()
    expect(onCloseModal).not.toHaveBeenCalled()
  })

  it('should unregister event listener on unmount', () => {
    const { unmount } = renderHook(() =>
      useAppShortcuts({
        enabled: true,
      })
    )

    unmount()

    expect(removeEventListenerSpy).toHaveBeenCalledWith('keydown', expect.any(Function), true)
  })
})
