import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import './LocalePickers.css';
import { LANGUAGES, LEGACY_NAME_TO_CODE, VARIANT_GROUPS, getLanguage, getVariant } from './localePickerLabels';

// ── Disclosure (outside-click + Escape) ───────────────────────────────

function useDisclosure(rootRef: React.RefObject<HTMLDivElement | null>, panelRef: React.RefObject<HTMLDivElement | null>) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // Escape closes only this dropdown. We must also stop the event so it
      // never reaches an ancestor modal's document keydown handler — the
      // Training/Settings modal closes on Escape, and its listener is
      // registered earlier (on mount), so without this it fires first and the
      // whole settings panel disappears "tout seul" while editing a per-contact
      // writing style. Capture phase runs before that bubble-phase listener.
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
    };
    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [open, rootRef]);

  // Focus the checked chip (or first) when panel opens
  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;
    const id = window.setTimeout(() => {
      const target =
        panel.querySelector<HTMLButtonElement>('[role="radio"][aria-checked="true"]') ||
        panel.querySelector<HTMLButtonElement>('[role="radio"]');
      target?.focus({ preventScroll: true });
    }, 60);
    return () => window.clearTimeout(id);
  }, [open, panelRef]);

  return { open, setOpen, toggle: () => setOpen(v => !v) };
}

// ── Roving keyboard navigation within the open grid ───────────────────

function useRovingKeyboard(panelRef: React.RefObject<HTMLDivElement | null>) {
  return useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      const keys = ['ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown', 'Home', 'End'];
      if (!keys.includes(e.key)) return;
      const container = panelRef.current;
      if (!container) return;
      const chips = Array.from(
        container.querySelectorAll<HTMLButtonElement>('[role="radio"]:not([disabled])')
      );
      if (!chips.length) return;
      e.preventDefault();
      const active = document.activeElement as HTMLButtonElement | null;
      const idx = active ? chips.indexOf(active) : -1;
      let next: number;
      if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = chips.length - 1;
      else {
        const forward = e.key === 'ArrowRight' || e.key === 'ArrowDown';
        const step = forward ? 1 : -1;
        next = idx >= 0 ? (idx + step + chips.length) % chips.length : 0;
      }
      chips[next].focus({ preventScroll: false });
      chips[next].click();
    },
    [panelRef]
  );
}

// ── Shared Trigger button ─────────────────────────────────────────────

interface TriggerProps {
  flag: string;
  label: string;
  code?: string;
  placeholder: boolean;
  open: boolean;
  onToggle: () => void;
  ariaLabel?: string;
}

function Trigger({ flag, label, code, placeholder, open, onToggle, ariaLabel }: TriggerProps) {
  return (
    <button
      type="button"
      className={[
        'locale-trigger',
        open ? 'locale-trigger--open' : '',
        placeholder ? 'locale-trigger--placeholder' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={onToggle}
      aria-expanded={open}
      aria-haspopup="listbox"
      aria-label={ariaLabel}
    >
      <span className="locale-trigger-flag" aria-hidden="true">{flag}</span>
      <span className="locale-trigger-body">
        <span className="locale-trigger-label">{label}</span>
        {code && <span className="locale-trigger-code">{code}</span>}
      </span>
      <svg
        className="locale-trigger-chevron"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>
  );
}

// ── Shared Chip ───────────────────────────────────────────────────────

interface ChipProps {
  active: boolean;
  flag: string;
  label: string;
  code?: string;
  ariaLabel: string;
  onSelect: () => void;
  isAuto?: boolean;
  open: boolean;
}

function Chip({ active, flag, label, code, ariaLabel, onSelect, isAuto, open }: ChipProps) {
  const tabIndex = !open ? -1 : active ? 0 : -1;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      aria-label={ariaLabel}
      tabIndex={tabIndex}
      className={[
        'locale-chip',
        active ? 'locale-chip--active' : '',
        isAuto ? 'locale-chip--auto' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={onSelect}
    >
      <span className="locale-chip-flag" aria-hidden="true">{flag}</span>
      {code ? (
        <span className="locale-chip-body">
          <span className="locale-chip-label">{label}</span>
          <span className="locale-chip-code">{code}</span>
        </span>
      ) : (
        <span className="locale-chip-label">{label}</span>
      )}
    </button>
  );
}

// ── LanguagePicker ────────────────────────────────────────────────────

interface LanguagePickerProps {
  value: string;
  onChange: (value: string) => void;
  autoLabel?: string;
  ariaLabel?: string;
}

export function LanguagePicker({
  value,
  onChange,
  autoLabel,
  ariaLabel,
}: LanguagePickerProps) {
  // Key already exists in the agents namespace (same string ContactStyleEditor
  // passes explicitly) — resolved at render so language switches apply.
  const { t } = useTranslation('agents');
  const resolvedAutoLabel = autoLabel ?? t('style_contact_langue_placeholder', 'Auto (même langue que l\'email reçu)');
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const { open, setOpen, toggle } = useDisclosure(rootRef, panelRef);
  const handleKeyDown = useRovingKeyboard(panelRef);

  const selected = getLanguage(value);
  const handleSelect = (newValue: string) => {
    onChange(newValue);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="locale-root">
      <Trigger
        flag={selected ? selected.flag : '✨'}
        label={selected ? selected.native : resolvedAutoLabel}
        placeholder={!selected}
        open={open}
        onToggle={toggle}
        ariaLabel={ariaLabel}
      />
      <div
        className={`locale-panel-wrap${open ? ' locale-panel-wrap--open' : ''}`}
        aria-hidden={!open}
      >
        <div
          ref={panelRef}
          className="locale-picker locale-picker--language"
          role="radiogroup"
          aria-label={ariaLabel}
          onKeyDown={handleKeyDown}
        >
          <Chip
            active={!value}
            flag="✨"
            label={resolvedAutoLabel}
            ariaLabel={resolvedAutoLabel}
            onSelect={() => handleSelect('')}
            isAuto
            open={open}
          />
          {LANGUAGES.map(lang => (
            <Chip
              key={lang.value}
              active={value === lang.value}
              flag={lang.flag}
              label={lang.native}
              ariaLabel={lang.latin}
              onSelect={() => handleSelect(lang.value)}
              open={open}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── LocaleVariantPicker ───────────────────────────────────────────────

interface LocaleVariantPickerProps {
  value: string;
  onChange: (code: string) => void;
  autoLabel?: string;
  ariaLabel?: string;
}

export function LocaleVariantPicker({
  value,
  onChange,
  autoLabel = 'Aucune (automatique)',
  ariaLabel,
}: LocaleVariantPickerProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const { open, setOpen, toggle } = useDisclosure(rootRef, panelRef);
  const handleKeyDown = useRovingKeyboard(panelRef);

  const normalized = LEGACY_NAME_TO_CODE[value] || value;
  const selected = getVariant(normalized);

  const handleSelect = (code: string) => {
    onChange(code);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="locale-root">
      <Trigger
        flag={selected ? selected.v.flag : '✨'}
        label={selected ? selected.v.country : autoLabel}
        code={selected ? selected.v.code : undefined}
        placeholder={!selected}
        open={open}
        onToggle={toggle}
        ariaLabel={ariaLabel}
      />
      <div
        className={`locale-panel-wrap${open ? ' locale-panel-wrap--open' : ''}`}
        aria-hidden={!open}
      >
        <div
          ref={panelRef}
          className="locale-picker locale-picker--variant"
          role="radiogroup"
          aria-label={ariaLabel}
          onKeyDown={handleKeyDown}
        >
          <Chip
            active={!normalized}
            flag="✨"
            label={autoLabel}
            ariaLabel={autoLabel}
            onSelect={() => handleSelect('')}
            isAuto
            open={open}
          />
          {VARIANT_GROUPS.map(group => (
            <div key={group.label} className="locale-group">
              <span className="locale-group-header">
                <span className="locale-group-flag" aria-hidden="true">{group.flag}</span>
                <span className="locale-group-label">{group.label}</span>
              </span>
              <div className="locale-group-chips">
                {group.variants.map(v => (
                  <Chip
                    key={v.code}
                    active={normalized === v.code}
                    flag={v.flag}
                    label={v.country}
                    code={v.code}
                    ariaLabel={`${v.country} — ${v.code}`}
                    onSelect={() => handleSelect(v.code)}
                    open={open}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
