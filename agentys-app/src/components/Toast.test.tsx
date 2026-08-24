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

import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Toast, ToastContainer, useToast, type ToastData } from './Toast';
import { renderHook } from '@testing-library/react';

describe('Toast', () => {
  const mockToast: ToastData = {
    id: 'toast-1',
    message: 'Test message',
    type: 'success',
  };

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  describe('rendering', () => {
    it('should render toast message', () => {
      render(<Toast toast={mockToast} onDismiss={vi.fn()} />);
      expect(screen.getByText('Test message')).toBeInTheDocument();
    });

    it('should render success icon for success type', () => {
      render(<Toast toast={mockToast} onDismiss={vi.fn()} />);
      expect(screen.getByText('✓')).toBeInTheDocument();
    });

    it('should render error icon for error type', () => {
      const errorToast = { ...mockToast, type: 'error' as const };
      const { container } = render(<Toast toast={errorToast} onDismiss={vi.fn()} />);
      const icon = container.querySelector('.toast-icon');
      expect(icon).toHaveTextContent('✕');
    });

    it('should render info icon for info type', () => {
      const infoToast = { ...mockToast, type: 'info' as const };
      render(<Toast toast={infoToast} onDismiss={vi.fn()} />);
      expect(screen.getByText('ℹ')).toBeInTheDocument();
    });

    it('should have correct CSS class for toast type', () => {
      const { container } = render(<Toast toast={mockToast} onDismiss={vi.fn()} />);
      expect(container.querySelector('.toast-success')).toBeInTheDocument();
    });

    it('should have role="alert" for accessibility', () => {
      render(<Toast toast={mockToast} onDismiss={vi.fn()} />);
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });

  describe('auto-dismiss', () => {
    it('should call onDismiss after default duration', () => {
      const onDismiss = vi.fn();
      render(<Toast toast={mockToast} onDismiss={onDismiss} />);

      // Wait for timeout plus animation duration
      act(() => {
        vi.advanceTimersByTime(3000);
      });

      act(() => {
        vi.advanceTimersByTime(200);
      });

      expect(onDismiss).toHaveBeenCalledWith('toast-1');
    });

    it('should call onDismiss after custom duration', () => {
      const onDismiss = vi.fn();
      render(<Toast toast={mockToast} onDismiss={onDismiss} defaultDuration={5000} />);

      act(() => {
        vi.advanceTimersByTime(3000);
      });

      expect(onDismiss).not.toHaveBeenCalled();

      act(() => {
        vi.advanceTimersByTime(2000);
      });

      act(() => {
        vi.advanceTimersByTime(200);
      });

      expect(onDismiss).toHaveBeenCalledWith('toast-1');
    });
  });

  describe('manual dismiss', () => {
    it('should call onDismiss when dismiss button is clicked', () => {
      const onDismiss = vi.fn();
      render(<Toast toast={mockToast} onDismiss={onDismiss} />);

      const dismissButton = screen.getByRole('button', { name: 'Fermer' });
      fireEvent.click(dismissButton);

      // Wait for animation
      act(() => {
        vi.advanceTimersByTime(200);
      });

      expect(onDismiss).toHaveBeenCalledWith('toast-1');
    });

    it('should add exit class when dismissing', () => {
      const { container } = render(<Toast toast={mockToast} onDismiss={vi.fn()} />);

      const dismissButton = screen.getByRole('button', { name: 'Fermer' });
      fireEvent.click(dismissButton);

      expect(container.querySelector('.toast-exit')).toBeInTheDocument();
    });
  });
});

describe('ToastContainer', () => {
  const mockToasts: ToastData[] = [
    { id: 'toast-1', message: 'First message', type: 'success' },
    { id: 'toast-2', message: 'Second message', type: 'error' },
  ];

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('should render nothing when toasts array is empty', () => {
    const { container } = render(<ToastContainer toasts={[]} onDismiss={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it('should render all toasts', () => {
    render(<ToastContainer toasts={mockToasts} onDismiss={vi.fn()} />);

    expect(screen.getByText('First message')).toBeInTheDocument();
    expect(screen.getByText('Second message')).toBeInTheDocument();
  });

  it('should have correct aria-label', () => {
    render(<ToastContainer toasts={mockToasts} onDismiss={vi.fn()} />);
    expect(screen.getByLabelText('Notifications')).toBeInTheDocument();
  });

  it('should pass onDismiss to each toast', () => {
    const onDismiss = vi.fn();
    render(<ToastContainer toasts={mockToasts} onDismiss={onDismiss} />);

    const dismissButtons = screen.getAllByRole('button', { name: 'Fermer' });
    fireEvent.click(dismissButtons[0]);

    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(onDismiss).toHaveBeenCalledWith('toast-1');
  });
});

describe('useToast hook', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('should initialize with empty toasts array', () => {
    const { result } = renderHook(() => useToast());
    expect(result.current.toasts).toEqual([]);
  });

  it('should add toast with addToast', () => {
    const { result } = renderHook(() => useToast());

    act(() => {
      result.current.addToast('Test message', 'success');
    });

    expect(result.current.toasts).toHaveLength(1);
    expect(result.current.toasts[0].message).toBe('Test message');
    expect(result.current.toasts[0].type).toBe('success');
  });

  it('should add toast with default info type', () => {
    const { result } = renderHook(() => useToast());

    act(() => {
      result.current.addToast('Test message');
    });

    expect(result.current.toasts[0].type).toBe('info');
  });

  it('should generate unique ids for toasts', () => {
    const { result } = renderHook(() => useToast());

    act(() => {
      result.current.addToast('First');
      result.current.addToast('Second');
    });

    const ids = result.current.toasts.map((t) => t.id);
    expect(ids[0]).not.toBe(ids[1]);
  });

  it('should dismiss toast with dismissToast', () => {
    const { result } = renderHook(() => useToast());

    act(() => {
      result.current.addToast('Test message');
    });

    const toastId = result.current.toasts[0].id;

    act(() => {
      result.current.dismissToast(toastId);
    });

    expect(result.current.toasts).toHaveLength(0);
  });

  it('should clear all toasts with clearAllToasts', () => {
    const { result } = renderHook(() => useToast());

    act(() => {
      result.current.addToast('First');
      result.current.addToast('Second');
      result.current.addToast('Third');
    });

    expect(result.current.toasts).toHaveLength(3);

    act(() => {
      result.current.clearAllToasts();
    });

    expect(result.current.toasts).toHaveLength(0);
  });
});
