import { render, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SttKeytermsManager } from './SttKeytermsManager';
import * as stt from '../../services/stt';

vi.mock('../../services/stt');

const mockGet = vi.mocked(stt.getKeyterms);
const mockAdd = vi.mocked(stt.addKeyterm);
const mockRemove = vi.mocked(stt.removeKeyterm);

function words(n: number): string[] {
  return Array.from({ length: n }, (_, i) => `word${i}`);
}

describe('SttKeytermsManager — effective cap surfacing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAdd.mockResolvedValue({ inserted: true, custom: [] });
    mockRemove.mockResolvedValue({ removed: true, custom: [] });
  });

  it('shows the count against the cap ("X / cap")', async () => {
    mockGet.mockResolvedValue({ auto: [], custom: words(2), cap: 50 });
    const { container } = render(<SttKeytermsManager />);
    await waitFor(() => expect(container.querySelector('.stt-keyterms-block-count')).toBeTruthy());
    expect(container.querySelector('.stt-keyterms-block-count')).toHaveTextContent('2 / 50');
  });

  it('at the cap, disables the input + Add button and shows the limit hint', async () => {
    mockGet.mockResolvedValue({ auto: [], custom: words(3), cap: 3 });
    const { container } = render(<SttKeytermsManager />);

    await waitFor(() => expect(container.querySelector('.stt-keyterms-input')).toBeTruthy());

    const input = container.querySelector('.stt-keyterms-input') as HTMLInputElement;
    const addBtn = container.querySelector('.stt-keyterms-add-btn') as HTMLButtonElement;

    expect(input).toBeDisabled();
    expect(addBtn).toBeDisabled();
    // A visible hint explains why adding is blocked.
    expect(container.querySelector('.stt-keyterms-limit-hint')).toBeInTheDocument();
  });

  it('below the cap, the input is enabled and no hint is shown', async () => {
    mockGet.mockResolvedValue({ auto: [], custom: words(2), cap: 3 });
    const { container } = render(<SttKeytermsManager />);

    await waitFor(() => expect(container.querySelector('.stt-keyterms-input')).toBeTruthy());

    expect(container.querySelector('.stt-keyterms-input')).not.toBeDisabled();
    expect(container.querySelector('.stt-keyterms-limit-hint')).toBeNull();
  });

  it('falls back to a default cap when the API omits it', async () => {
    // Older backend response without `cap` — must not crash or block adds.
    mockGet.mockResolvedValue({ auto: [], custom: words(2) } as never);
    const { container } = render(<SttKeytermsManager />);
    await waitFor(() => expect(container.querySelector('.stt-keyterms-input')).toBeTruthy());
    expect(container.querySelector('.stt-keyterms-input')).not.toBeDisabled();
    expect(container.querySelector('.stt-keyterms-block-count')).toHaveTextContent('2 / 50');
  });
});
