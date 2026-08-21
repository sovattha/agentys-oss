/**
 * Microphone permission state + soft-ask acknowledgment.
 *
 * Browsers expose `navigator.permissions.query({name:'microphone'})` on Chromium
 * and recent Safari/Firefox. When unavailable we degrade to 'prompt' so the
 * soft-ask still runs the first time.
 */

export type MicPermissionState = 'granted' | 'denied' | 'prompt' | 'unsupported'

const ACK_STORAGE_KEY = 'agentys_mic_softask_ack_v1'

export async function queryMicPermissionState(): Promise<MicPermissionState> {
  if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
    return 'unsupported'
  }
  const permApi = (navigator as Navigator & { permissions?: Permissions }).permissions
  if (!permApi?.query) return 'prompt'
  try {
    const status = await permApi.query({ name: 'microphone' as PermissionName })
    if (status.state === 'granted' || status.state === 'denied' || status.state === 'prompt') {
      return status.state
    }
    return 'prompt'
  } catch {
    // Firefox throws TypeError for 'microphone' name — treat as unknown / prompt.
    return 'prompt'
  }
}

export function hasUserAcknowledgedMicSoftAsk(): boolean {
  if (typeof localStorage === 'undefined') return false
  try {
    return localStorage.getItem(ACK_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export function setUserAcknowledgedMicSoftAsk(): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(ACK_STORAGE_KEY, '1')
  } catch {
    /* quota or privacy mode — silently skip; user just sees the soft-ask again */
  }
}

export function clearMicSoftAskAcknowledgment(): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.removeItem(ACK_STORAGE_KEY)
  } catch {
    /* noop */
  }
}
