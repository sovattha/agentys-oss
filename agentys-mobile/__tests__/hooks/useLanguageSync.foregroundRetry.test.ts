/**
 * F15 (LOW) — language drift regression guard.
 *
 * Pre-patch: when `updateUserPreferences` failed (offline / Railway cold-
 * start abort / 502), the lang change was lost. The web app and the mobile
 * app would silently drift to different languages with no UI feedback.
 *
 * Post-patch: a failed push is stashed in a ref, and an AppState listener
 * replays it when the app returns to foreground. Pure side effect — no
 * UI change, no toast. This test pins the contract.
 */
import { renderHook, act, waitFor } from '@testing-library/react-native';
import { AppState } from 'react-native';
import { useLanguageSync } from '../../src/hooks/useLanguageSync';

// Mock useAuth to keep `isAuthenticated=false` so the GET /preferences
// branch stays out of the way and we can focus on the push side.
jest.mock('../../src/hooks/useAuth', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    isLoading: false,
    login: jest.fn(),
    logout: jest.fn(),
  }),
}));

// Mock api: getUserPreferences not exercised here; updateUserPreferences is.
jest.mock('../../src/services/api', () => ({
  getUserPreferences: jest.fn().mockResolvedValue({ preferred_language: 'en' }),
  updateUserPreferences: jest.fn(),
}));

// Mock i18n init + applyLanguage so changeLanguage doesn't actually run.
jest.mock('../../src/i18n', () => ({
  initI18n: jest.fn(),
  normalizeLanguage: (l: string) => (l === 'fr' || l === 'en' ? l : 'en'),
  setLanguage: jest.fn().mockResolvedValue(undefined),
  SUPPORTED_LANGUAGES: ['en', 'fr'],
  DEFAULT_LANGUAGE: 'en',
}));

import { updateUserPreferences } from '../../src/services/api';

const mockUpdate = updateUserPreferences as jest.Mock;

describe('useLanguageSync — F15 foreground retry on failed backend push', () => {
  // Capture the AppState change listener so we can fire it manually.
  let listener: ((s: string) => void) | null = null;
  let removeSpy: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    listener = null;
    removeSpy = jest.fn();
    jest
      .spyOn(AppState, 'addEventListener')
      .mockImplementation((event: any, cb: any) => {
        if (event === 'change') listener = cb;
        return { remove: removeSpy } as any;
      });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('replays the last failed lang push when the app comes to foreground', async () => {
    // First push fails; second (foreground retry) succeeds.
    mockUpdate
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ ok: true });

    const { result } = renderHook(() => useLanguageSync());

    await act(async () => {
      await result.current.setLanguage('fr');
    });

    // The first push was attempted and failed.
    expect(mockUpdate).toHaveBeenCalledTimes(1);
    expect(mockUpdate).toHaveBeenCalledWith({ preferred_language: 'fr' });

    // Now simulate the app returning to foreground.
    expect(listener).not.toBeNull();
    await act(async () => {
      listener?.('active');
      // Allow promise microtasks to flush.
      await Promise.resolve();
    });

    // Retry should have been issued.
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(2));
    expect(mockUpdate).toHaveBeenLastCalledWith({ preferred_language: 'fr' });
  });

  it('does NOT retry when the initial push succeeds', async () => {
    mockUpdate.mockResolvedValueOnce({ ok: true });

    const { result } = renderHook(() => useLanguageSync());

    await act(async () => {
      await result.current.setLanguage('en');
    });

    expect(mockUpdate).toHaveBeenCalledTimes(1);

    await act(async () => {
      listener?.('active');
      await Promise.resolve();
    });

    // No second call — pendingPushRef was cleared on success.
    expect(mockUpdate).toHaveBeenCalledTimes(1);
  });

  it('keeps retrying across multiple foreground cycles if backend stays down', async () => {
    mockUpdate
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('still offline'))
      .mockResolvedValueOnce({ ok: true });

    const { result } = renderHook(() => useLanguageSync());

    await act(async () => {
      await result.current.setLanguage('fr');
    });
    expect(mockUpdate).toHaveBeenCalledTimes(1);

    // First foreground tick: still failing.
    await act(async () => {
      listener?.('active');
      await Promise.resolve();
    });
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(2));

    // Second foreground tick: backend recovers.
    await act(async () => {
      listener?.('active');
      await Promise.resolve();
    });
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(3));

    // After success, no more retries on subsequent tick.
    await act(async () => {
      listener?.('active');
      await Promise.resolve();
    });
    expect(mockUpdate).toHaveBeenCalledTimes(3);
  });

  it('ignores non-active AppState transitions', async () => {
    mockUpdate.mockRejectedValueOnce(new Error('offline'));

    const { result } = renderHook(() => useLanguageSync());

    await act(async () => {
      await result.current.setLanguage('fr');
    });
    expect(mockUpdate).toHaveBeenCalledTimes(1);

    await act(async () => {
      listener?.('background');
      listener?.('inactive');
      await Promise.resolve();
    });
    // No retry triggered by background/inactive transitions.
    expect(mockUpdate).toHaveBeenCalledTimes(1);
  });
});
