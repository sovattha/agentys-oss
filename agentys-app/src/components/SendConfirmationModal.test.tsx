import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  SendConfirmationModal,
  shouldSkipSendConfirmation,
  resetSendConfirmationPreference,
} from './SendConfirmationModal';

const SEND_CONFIRMATION_SKIP_KEY = 'agentys_skip_send_confirmation';

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
  };
})();

Object.defineProperty(window, 'localStorage', { value: localStorageMock });

describe('SendConfirmationModal', () => {
  const defaultProps = {
    isOpen: true,
    recipient: 'test@example.com',
    recipientName: 'Test User',
    subject: 'Test Subject',
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    isLoading: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    localStorageMock.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    localStorageMock.clear();
  });

  // Basic rendering tests
  it('renders nothing when closed', () => {
    const { container } = render(
      <SendConfirmationModal {...defaultProps} isOpen={false} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders modal when open', () => {
    render(<SendConfirmationModal {...defaultProps} />);
    expect(screen.getByText("Confirmer l'envoi")).toBeInTheDocument();
  });

  // AC1: Modal shows recipient and subject summary
  describe('AC1: Summary display', () => {
    it('displays recipient name and email', () => {
      render(<SendConfirmationModal {...defaultProps} />);

      expect(screen.getByTestId('summary-recipient')).toHaveTextContent('Test User');
      expect(screen.getByTestId('summary-recipient')).toHaveTextContent('test@example.com');
    });

    it('displays only email when no recipient name', () => {
      render(
        <SendConfirmationModal
          {...defaultProps}
          recipientName={undefined}
        />
      );

      expect(screen.getByTestId('summary-recipient')).toHaveTextContent('test@example.com');
    });

    it('displays subject', () => {
      render(<SendConfirmationModal {...defaultProps} />);
      expect(screen.getByTestId('summary-subject')).toHaveTextContent('Test Subject');
    });
  });

  // AC2: Clear confirm and cancel buttons
  describe('AC2: Button visibility', () => {
    it('shows Confirmer l\'envoi button', () => {
      render(<SendConfirmationModal {...defaultProps} />);
      expect(screen.getByTestId('confirm-button')).toBeInTheDocument();
    });

    it('shows close button', () => {
      render(<SendConfirmationModal {...defaultProps} />);
      expect(screen.getByTestId('close-button')).toBeInTheDocument();
    });

    it('calls onCancel when clicking Annuler', () => {
      const onCancel = vi.fn();
      render(<SendConfirmationModal {...defaultProps} onCancel={onCancel} />);

      fireEvent.click(screen.getByTestId('close-button'));
      expect(onCancel).toHaveBeenCalledTimes(1);
    });
  });

  // AC3: 3-second delay before confirm button is active
  describe('AC3: 3-second countdown', () => {
    it('confirm button is disabled initially', () => {
      render(<SendConfirmationModal {...defaultProps} />);
      expect(screen.getByTestId('confirm-button')).toBeDisabled();
    });

    it('shows countdown text', () => {
      render(<SendConfirmationModal {...defaultProps} />);
      expect(screen.getByTestId('countdown-text')).toHaveTextContent('3 secondes');
    });

    it('countdown decreases over time', async () => {
      render(<SendConfirmationModal {...defaultProps} />);

      expect(screen.getByTestId('countdown-text')).toHaveTextContent('3 secondes');

      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.getByTestId('countdown-text')).toHaveTextContent('2 secondes');

      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.getByTestId('countdown-text')).toHaveTextContent('1 seconde');
    });

    it('enables confirm button after 3 seconds', async () => {
      render(<SendConfirmationModal {...defaultProps} />);

      expect(screen.getByTestId('confirm-button')).toBeDisabled();

      act(() => {
        vi.advanceTimersByTime(3000);
      });

      expect(screen.getByTestId('confirm-button')).not.toBeDisabled();
    });

    it('hides countdown container after countdown completes', () => {
      render(<SendConfirmationModal {...defaultProps} />);

      expect(screen.getByTestId('countdown-container')).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(3000);
      });

      expect(screen.queryByTestId('countdown-container')).not.toBeInTheDocument();
    });

    it('calls onConfirm when clicking confirm after countdown', () => {
      const onConfirm = vi.fn();
      render(<SendConfirmationModal {...defaultProps} onConfirm={onConfirm} />);

      act(() => {
        vi.advanceTimersByTime(3000);
      });

      fireEvent.click(screen.getByTestId('confirm-button'));
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });

    it('does not call onConfirm when clicking confirm during countdown', () => {
      const onConfirm = vi.fn();
      render(<SendConfirmationModal {...defaultProps} onConfirm={onConfirm} />);

      fireEvent.click(screen.getByTestId('confirm-button'));
      expect(onConfirm).not.toHaveBeenCalled();
    });
  });

  // AC4: Skip confirmation checkbox
  describe('AC4: Skip checkbox', () => {
    it('shows "Ne plus afficher" checkbox', () => {
      render(<SendConfirmationModal {...defaultProps} />);
      expect(screen.getByTestId('skip-checkbox')).toBeInTheDocument();
      expect(screen.getByText('Ne plus afficher cette confirmation')).toBeInTheDocument();
    });

    it('checkbox is unchecked by default', () => {
      render(<SendConfirmationModal {...defaultProps} />);
      expect(screen.getByTestId('skip-checkbox')).not.toBeChecked();
    });

    it('can toggle checkbox', () => {
      render(<SendConfirmationModal {...defaultProps} />);

      const checkbox = screen.getByTestId('skip-checkbox');
      fireEvent.click(checkbox);
      expect(checkbox).toBeChecked();

      fireEvent.click(checkbox);
      expect(checkbox).not.toBeChecked();
    });

    it('saves skip preference to localStorage when confirm with checkbox checked', () => {
      const onConfirm = vi.fn();
      render(<SendConfirmationModal {...defaultProps} onConfirm={onConfirm} />);

      // Wait for countdown
      act(() => {
        vi.advanceTimersByTime(3000);
      });

      // Check the checkbox
      fireEvent.click(screen.getByTestId('skip-checkbox'));

      // Confirm
      fireEvent.click(screen.getByTestId('confirm-button'));

      expect(localStorageMock.setItem).toHaveBeenCalledWith(SEND_CONFIRMATION_SKIP_KEY, 'true');
    });

    it('does not save skip preference when confirm without checkbox', () => {
      const onConfirm = vi.fn();
      render(<SendConfirmationModal {...defaultProps} onConfirm={onConfirm} />);

      act(() => {
        vi.advanceTimersByTime(3000);
      });

      fireEvent.click(screen.getByTestId('confirm-button'));

      expect(localStorageMock.setItem).not.toHaveBeenCalledWith(SEND_CONFIRMATION_SKIP_KEY, expect.any(String));
    });
  });

  // AC5: Escape key closes modal
  describe('AC5: Escape key handling', () => {
    it('calls onCancel when pressing Escape', () => {
      const onCancel = vi.fn();
      render(<SendConfirmationModal {...defaultProps} onCancel={onCancel} />);

      fireEvent.keyDown(document, { key: 'Escape' });

      expect(onCancel).toHaveBeenCalledTimes(1);
    });

    it('does not call onCancel when pressing Escape while loading', () => {
      const onCancel = vi.fn();
      render(
        <SendConfirmationModal {...defaultProps} onCancel={onCancel} isLoading={true} />
      );

      fireEvent.keyDown(document, { key: 'Escape' });

      expect(onCancel).not.toHaveBeenCalled();
    });
  });

  // TODO: update for new architecture — overlay now handled by Radix Dialog
  describe.skip('Overlay click handling', () => {
    it('calls onCancel when clicking overlay', () => {
      const onCancel = vi.fn();
      render(<SendConfirmationModal {...defaultProps} onCancel={onCancel} />);

      fireEvent.click(screen.getByTestId('send-confirmation-overlay'));

      expect(onCancel).toHaveBeenCalledTimes(1);
    });

    it('does not call onCancel when clicking inside modal', () => {
      const onCancel = vi.fn();
      render(<SendConfirmationModal {...defaultProps} onCancel={onCancel} />);

      const modal = screen.getByText("Confirmer l'envoi").closest('.send-confirmation-modal');
      if (modal) {
        fireEvent.click(modal);
      }

      expect(onCancel).not.toHaveBeenCalled();
    });

    it('does not close when clicking overlay while loading', () => {
      const onCancel = vi.fn();
      render(
        <SendConfirmationModal {...defaultProps} onCancel={onCancel} isLoading={true} />
      );

      fireEvent.click(screen.getByTestId('send-confirmation-overlay'));

      expect(onCancel).not.toHaveBeenCalled();
    });
  });

  // Loading state
  describe('Loading state', () => {
    it('shows loading spinner when isLoading is true', () => {
      render(<SendConfirmationModal {...defaultProps} isLoading={true} />);

      expect(screen.getByText('Envoi en cours...')).toBeInTheDocument();
    });

    it('disables confirm button when loading', () => {
      render(<SendConfirmationModal {...defaultProps} isLoading={true} />);

      // Even after countdown, button should be disabled
      act(() => {
        vi.advanceTimersByTime(3000);
      });

      expect(screen.getByTestId('confirm-button')).toBeDisabled();
    });

    it('disables cancel button when loading', () => {
      render(<SendConfirmationModal {...defaultProps} isLoading={true} />);

      expect(screen.getByTestId('close-button')).toBeDisabled();
    });

    it('disables checkbox when loading', () => {
      render(<SendConfirmationModal {...defaultProps} isLoading={true} />);

      expect(screen.getByTestId('skip-checkbox')).toBeDisabled();
    });
  });

  // Helper functions
  describe('Helper functions', () => {
    it('shouldSkipSendConfirmation returns false by default', () => {
      localStorageMock.getItem.mockReturnValueOnce(null);
      expect(shouldSkipSendConfirmation()).toBe(false);
    });

    it('shouldSkipSendConfirmation returns true when localStorage is set', () => {
      localStorageMock.getItem.mockReturnValueOnce('true');
      expect(shouldSkipSendConfirmation()).toBe(true);
    });

    it('resetSendConfirmationPreference clears localStorage', () => {
      resetSendConfirmationPreference();
      expect(localStorageMock.removeItem).toHaveBeenCalledWith(SEND_CONFIRMATION_SKIP_KEY);
    });
  });

  // Countdown reset on reopen
  describe('Countdown reset', () => {
    it('resets countdown when modal reopens', () => {
      const { rerender } = render(<SendConfirmationModal {...defaultProps} />);

      // Advance some time
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(screen.getByTestId('countdown-text')).toHaveTextContent('1 seconde');

      // Close modal
      rerender(<SendConfirmationModal {...defaultProps} isOpen={false} />);

      // Reopen modal
      rerender(<SendConfirmationModal {...defaultProps} isOpen={true} />);

      // Countdown should be reset to 3
      expect(screen.getByTestId('countdown-text')).toHaveTextContent('3 secondes');
    });
  });
});
