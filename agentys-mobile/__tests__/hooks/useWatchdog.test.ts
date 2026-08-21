/**
 * useWatchdog — le gel du tour de parole devient un état VISIBLE au lieu
 * d'un écran muet (Phase 1 fondations §1.6).
 */
import { renderHook, act } from '@testing-library/react-native';
import { useWatchdog } from '../../src/hooks/useWatchdog';
import { clearEvents, getRecentEvents } from '../../src/lib/eventLog';

jest.useFakeTimers();

describe('useWatchdog', () => {
  beforeEach(() => clearEvents());
  afterEach(() => jest.clearAllTimers());

  it('déclare le gel après timeoutMs sans progrès en état actif', () => {
    const onStall = jest.fn();
    const { result } = renderHook(() => useWatchdog(true, ['choosing'], 1000, onStall));
    expect(result.current.stalled).toBe(false);
    act(() => { jest.advanceTimersByTime(1100); });
    expect(result.current.stalled).toBe(true);
    expect(onStall).toHaveBeenCalledTimes(1);
    // Événement watchdog tracé dans le ring buffer.
    expect(getRecentEvents(5).some((e) => e.kind === 'watchdog')).toBe(true);
  });

  it('tout changement de signal réarme le timer (pas de gel)', () => {
    const { result, rerender } = renderHook(
      (props: { sig: string }) => useWatchdog(true, [props.sig], 1000),
      { initialProps: { sig: 'a' } },
    );
    act(() => { jest.advanceTimersByTime(700); });
    rerender({ sig: 'b' }); // progrès
    act(() => { jest.advanceTimersByTime(700); });
    expect(result.current.stalled).toBe(false); // 1400ms écoulées mais réarmé à 700
    act(() => { jest.advanceTimersByTime(400); });
    expect(result.current.stalled).toBe(true);
  });

  it('inactif → jamais de gel', () => {
    const { result } = renderHook(() => useWatchdog(false, ['idle'], 1000));
    act(() => { jest.advanceTimersByTime(5000); });
    expect(result.current.stalled).toBe(false);
  });

  it('un progrès APRÈS le gel le dissout', () => {
    const { result, rerender } = renderHook(
      (props: { sig: string }) => useWatchdog(true, [props.sig], 1000),
      { initialProps: { sig: 'a' } },
    );
    act(() => { jest.advanceTimersByTime(1100); });
    expect(result.current.stalled).toBe(true);
    rerender({ sig: 'b' });
    expect(result.current.stalled).toBe(false);
  });

  it('acknowledge() efface le gel (tap du bandeau)', () => {
    const { result } = renderHook(() => useWatchdog(true, ['x'], 1000));
    act(() => { jest.advanceTimersByTime(1100); });
    expect(result.current.stalled).toBe(true);
    act(() => result.current.acknowledge());
    expect(result.current.stalled).toBe(false);
  });
});
