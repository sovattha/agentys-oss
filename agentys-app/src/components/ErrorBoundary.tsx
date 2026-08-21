import { Component, type ReactNode, type ErrorInfo } from 'react'
import * as Sentry from '@sentry/react'
import i18n from '../i18n'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

function isBenignResizeObserverError(message: string): boolean {
  return (
    message.includes('ResizeObserver loop completed with undelivered notifications') ||
    message.includes('ResizeObserver loop limit exceeded')
  )
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary] Caught render error:', error, info.componentStack)
    // Report to Sentry if available
    try {
      Sentry.captureException(error, { extra: { componentStack: info.componentStack } })
    } catch { /* ignore */ }
  }

  componentDidMount() {
    // Catch non-React errors (event handlers, async code) that can crash the app
    // without React's error boundary seeing them
    window.addEventListener('error', this.handleGlobalError)
    window.addEventListener('unhandledrejection', this.handleUnhandledRejection)
  }

  componentWillUnmount() {
    window.removeEventListener('error', this.handleGlobalError)
    window.removeEventListener('unhandledrejection', this.handleUnhandledRejection)
  }

  private handleGlobalError = (event: ErrorEvent) => {
    const message = event.error instanceof Error
      ? event.error.message
      : event.message || ''
    if (isBenignResizeObserverError(message)) return

    console.error('[ErrorBoundary] Global error caught:', event.error || event.message)
    // Check if root was emptied (blank screen crash)
    this.scheduleRootRecoveryCheck()
  }

  private handleUnhandledRejection = (event: PromiseRejectionEvent) => {
    const reason = event.reason;
    // Ignorer silencieusement les erreurs de transition React Router (comportement concurrent attendu)
    if (reason instanceof Error) {
      const name = reason.name || '';
      const msg = reason.message || '';
      if (
        name === 'AbortError' ||
        (name === 'InvalidStateError' && msg.includes('Transition was aborted')) ||
        msg.includes('Transition was skipped')
      ) {
        return; // Transition annulée — comportement normal en mode concurrent React
      }
    }
    console.error('[ErrorBoundary] Unhandled rejection:', reason)
    this.scheduleRootRecoveryCheck()
  }

  /** After a global error, check if the React root was wiped out (blank screen).
   *  If so, force a page reload to recover — this is the last-resort safety net. */
  private recoveryCheckScheduled = false
  private scheduleRootRecoveryCheck = () => {
    if (this.recoveryCheckScheduled) return
    this.recoveryCheckScheduled = true
    requestAnimationFrame(() => {
      this.recoveryCheckScheduled = false
      const root = document.getElementById('root')
      if (root && root.innerHTML.length === 0) {
        console.error('[ErrorBoundary] Root element is empty — reloading app to recover')
        window.location.reload()
      }
    })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback

      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', height: '100%', padding: '48px 24px',
          textAlign: 'center', color: 'var(--text-secondary, #6b7280)',
        }}>
          <div style={{ fontSize: '2rem', marginBottom: '12px' }}>!</div>
          <p style={{ margin: '0 0 16px', fontWeight: 500, color: 'var(--text-primary, #1a1a1a)' }}>
            {i18n.t('errors:generic')}
          </p>
          <p style={{ margin: '0 0 16px', fontSize: '0.875rem' }}>
            {this.state.error?.message}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{
              padding: '8px 20px', borderRadius: '6px', border: 'none',
              background: 'var(--accent-primary, #0d9488)', color: '#fff',
              cursor: 'pointer', fontWeight: 500,
            }}
          >
            {i18n.t('common:reload_page')}
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
