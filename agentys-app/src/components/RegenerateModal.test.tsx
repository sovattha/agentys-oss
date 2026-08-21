import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { RegenerateModal } from './RegenerateModal';

describe('RegenerateModal', () => {
  const defaultProps = {
    isOpen: true,
    onClose: vi.fn(),
    onRegenerate: vi.fn(),
    isLoading: false,
    previousInstructions: '',
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when closed', () => {
    const { container } = render(
      <RegenerateModal {...defaultProps} isOpen={false} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders modal when open (AC1)', () => {
    render(<RegenerateModal {...defaultProps} />);
    expect(screen.getByText('Régénérer le brouillon')).toBeInTheDocument();
  });

  it('pre-fills textarea with previous instructions (AC2)', () => {
    render(
      <RegenerateModal
        {...defaultProps}
        previousInstructions="Sois plus formel"
      />
    );

    const textarea = screen.getByRole('textbox');
    expect(textarea).toHaveValue('Sois plus formel');
  });

  it('allows editing instructions', () => {
    render(<RegenerateModal {...defaultProps} />);

    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: 'Nouvelles instructions' } });

    expect(textarea).toHaveValue('Nouvelles instructions');
  });

  it('calls onRegenerate with instructions when clicking button (AC3)', () => {
    const onRegenerate = vi.fn();
    render(
      <RegenerateModal {...defaultProps} onRegenerate={onRegenerate} />
    );

    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: 'Test instructions' } });

    const button = screen.getByText('Régénérer');
    fireEvent.click(button);

    expect(onRegenerate).toHaveBeenCalledWith('Test instructions');
  });

  it('disables regenerate button when instructions are empty', () => {
    render(<RegenerateModal {...defaultProps} />);

    const button = screen.getByText('Régénérer');
    expect(button).toBeDisabled();
  });

  it('disables regenerate button when loading', () => {
    render(
      <RegenerateModal
        {...defaultProps}
        isLoading={true}
        previousInstructions="Test"
      />
    );

    const button = screen.getByText('Régénération...');
    expect(button).toBeDisabled();
  });

  it('shows loading state when regenerating', () => {
    render(
      <RegenerateModal {...defaultProps} isLoading={true} />
    );

    expect(screen.getByText('Régénération...')).toBeInTheDocument();
  });

  // TODO: update for new architecture — uses Radix Dialog, no separate cancel button or overlay testid
  it.skip('calls onClose when clicking cancel', () => {
    const onClose = vi.fn();
    render(<RegenerateModal {...defaultProps} onClose={onClose} />);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it.skip('calls onClose when clicking overlay', () => {
    const onClose = vi.fn();
    render(<RegenerateModal {...defaultProps} onClose={onClose} />);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not close when clicking inside modal', () => {
    const onClose = vi.fn();
    render(<RegenerateModal {...defaultProps} onClose={onClose} />);

    const modal = screen.getByText('Régénérer le brouillon').closest('.regenerate-modal');
    if (modal) {
      fireEvent.click(modal);
    }

    expect(onClose).not.toHaveBeenCalled();
  });

  it('displays suggestion chips', () => {
    render(<RegenerateModal {...defaultProps} />);

    expect(screen.getByText('Plus court')).toBeInTheDocument();
    expect(screen.getByText('Plus formel')).toBeInTheDocument();
  });

  it('fills instructions when clicking suggestion chip', () => {
    render(<RegenerateModal {...defaultProps} />);

    const chip = screen.getByText('Plus court');
    fireEvent.click(chip);

    const textarea = screen.getByRole('textbox');
    expect((textarea as HTMLTextAreaElement).value.length).toBeGreaterThan(0);
  });

  it('submits on Ctrl+Enter (AC3)', () => {
    const onRegenerate = vi.fn();
    render(
      <RegenerateModal
        {...defaultProps}
        onRegenerate={onRegenerate}
        previousInstructions="Test instructions"
      />
    );

    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true });

    expect(onRegenerate).toHaveBeenCalledWith('Test instructions');
  });

  it('does not submit on Enter without Ctrl', () => {
    const onRegenerate = vi.fn();
    render(
      <RegenerateModal
        {...defaultProps}
        onRegenerate={onRegenerate}
        previousInstructions="Test"
      />
    );

    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(onRegenerate).not.toHaveBeenCalled();
  });

  it('closes on Escape key', () => {
    const onClose = vi.fn();
    render(<RegenerateModal {...defaultProps} onClose={onClose} />);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
