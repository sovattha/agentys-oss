import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAutoSave } from './useAutoSave';

describe('useAutoSave', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('starts with idle status', () => {
    const onSave = vi.fn();
    const { result } = renderHook(() =>
      useAutoSave({
        data: { text: 'initial' },
        onSave,
        debounceMs: 2000,
      })
    );

    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
  });

  it('changes status to saving when data changes', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(
      ({ data }) =>
        useAutoSave({
          data,
          onSave,
          debounceMs: 2000,
        }),
      { initialProps: { data: { text: 'initial' } } }
    );

    // Change data
    rerender({ data: { text: 'changed' } });

    expect(result.current.status).toBe('saving');
  });

  it('calls onSave after debounce period', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { rerender } = renderHook(
      ({ data }) =>
        useAutoSave({
          data,
          onSave,
          debounceMs: 2000,
        }),
      { initialProps: { data: { text: 'initial' } } }
    );

    // Change data
    rerender({ data: { text: 'changed' } });

    // onSave should not be called immediately
    expect(onSave).not.toHaveBeenCalled();

    // Fast forward past debounce
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    expect(onSave).toHaveBeenCalledWith({ text: 'changed' });
  });

  it('changes status to saved after successful save', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(
      ({ data }) =>
        useAutoSave({
          data,
          onSave,
          debounceMs: 2000,
        }),
      { initialProps: { data: { text: 'initial' } } }
    );

    // Change data
    rerender({ data: { text: 'changed' } });

    // Fast forward past debounce and flush promises
    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
    });

    // Wait for state update
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.status).toBe('saved');
  });

  it('changes status to error on save failure', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('Save failed'));
    const { result, rerender } = renderHook(
      ({ data }) =>
        useAutoSave({
          data,
          onSave,
          debounceMs: 2000,
        }),
      { initialProps: { data: { text: 'initial' } } }
    );

    // Change data
    rerender({ data: { text: 'changed' } });

    // Fast forward past debounce and flush promises
    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
    });

    // Wait for error state update
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBe('Save failed');
  });

  it('does not save when enabled is false', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(
      ({ data, enabled }) =>
        useAutoSave({
          data,
          onSave,
          debounceMs: 2000,
          enabled,
        }),
      { initialProps: { data: { text: 'initial' }, enabled: false } }
    );

    // Change data
    rerender({ data: { text: 'changed' }, enabled: false });

    // Fast forward past debounce
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    expect(onSave).not.toHaveBeenCalled();
    expect(result.current.status).toBe('idle');
  });

  it('debounces multiple rapid changes', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { rerender } = renderHook(
      ({ data }) =>
        useAutoSave({
          data,
          onSave,
          debounceMs: 2000,
        }),
      { initialProps: { data: { text: 'initial' } } }
    );

    // Multiple rapid changes
    rerender({ data: { text: 'change1' } });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    rerender({ data: { text: 'change2' } });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    rerender({ data: { text: 'change3' } });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    // onSave should not be called yet
    expect(onSave).not.toHaveBeenCalled();

    // Fast forward past debounce from last change
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    // Only called once with final value
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith({ text: 'change3' });
  });

  it('manual save works', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    // Use a stable data reference outside the callback to prevent auto-save
    // from triggering on every re-render (new object literals create new references)
    const stableData = { text: 'test' };
    const { result } = renderHook(() =>
      useAutoSave({
        data: stableData,
        onSave,
        debounceMs: 2000,
      })
    );

    await act(async () => {
      await result.current.save();
    });

    expect(onSave).toHaveBeenCalledWith({ text: 'test' });
    expect(result.current.status).toBe('saved');
  });
});
