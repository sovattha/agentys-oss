import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { useAnimatedUnmount } from '../hooks/useAnimatedUnmount';
import { SearchIcon } from './icons/ActionIcons';
import './CommandPalette.css';

export interface CommandAction {
  id: string;
  label: string;
  section: string;
  /** Optional secondary text shown dimmed after the label (e.g. a contact's email). */
  sublabel?: string;
  /** Extra hidden search terms (e.g. a contact's email) matched alongside the label. */
  keywords?: string;
  shortcut?: string;
  action: () => void;
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  actions: CommandAction[];
  /** Notified on every query change so a parent can fetch dynamic results (e.g. contacts). */
  onQueryChange?: (query: string) => void;
  /** When true, suppress the "no results" empty state — async results may still be loading. */
  searching?: boolean;
}

export function CommandPalette({ isOpen, onClose, actions, onQueryChange, searching }: CommandPaletteProps) {
  const { t } = useTranslation('search');
  const { shouldRender, isClosing, handleClose } = useAnimatedUnmount(isOpen, onClose);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const focusTrapRef = useFocusTrap(isOpen);

  // Filter actions by search query
  const filtered = useMemo(() => {
    if (!query.trim()) return actions;
    const lower = query.toLowerCase();
    return actions.filter(a =>
      a.label.toLowerCase().includes(lower) ||
      a.section.toLowerCase().includes(lower) ||
      (a.keywords?.toLowerCase().includes(lower) ?? false)
    );
  }, [actions, query]);

  // Group filtered actions by section
  const sections = useMemo(() => {
    const map = new Map<string, CommandAction[]>();
    for (const action of filtered) {
      if (!map.has(action.section)) map.set(action.section, []);
      map.get(action.section)!.push(action);
    }
    return map;
  }, [filtered]);

  // Flat list for keyboard navigation
  const flatList = useMemo(() => {
    const list: CommandAction[] = [];
    for (const [, group] of sections) {
      list.push(...group);
    }
    return list;
  }, [sections]);

  // Reset on open
  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [isOpen]);

  // Clamp selected index when list changes
  useEffect(() => {
    setSelectedIndex(i => Math.min(i, Math.max(0, flatList.length - 1)));
  }, [flatList.length]);

  // Scroll selected item into view
  useEffect(() => {
    const item = listRef.current?.querySelector(`[data-index="${selectedIndex}"]`);
    item?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

  const executeAction = useCallback((action: CommandAction) => {
    handleClose();
    // Defer to let the palette close animation start
    requestAnimationFrame(() => action.action());
  }, [handleClose]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex(i => Math.min(i + 1, flatList.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex(i => Math.max(i - 1, 0));
        break;
      case 'Enter':
        e.preventDefault();
        if (flatList[selectedIndex]) {
          executeAction(flatList[selectedIndex]);
        }
        break;
      case 'Escape':
        e.preventDefault();
        handleClose();
        break;
    }
  }, [flatList, selectedIndex, executeAction, handleClose]);

  if (!shouldRender) return null;

  let globalIndex = 0;

  return (
    <div className="command-palette-overlay" onClick={handleClose} role="dialog" aria-modal="true" aria-label={t('command_palette_aria')}>
      <div
        ref={focusTrapRef}
        className={`command-palette${isClosing ? ' closing' : ''}`}
        onClick={e => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="command-palette-input-wrapper">
          <SearchIcon size={16} className="command-palette-search-icon" />
          <input
            ref={inputRef}
            className="command-palette-input"
            type="text"
            placeholder={t('command_palette_placeholder')}
            value={query}
            onChange={e => { setQuery(e.target.value); onQueryChange?.(e.target.value); }}
            autoFocus
            role="combobox"
            aria-expanded={true}
            aria-controls="command-palette-listbox"
            aria-activedescendant={flatList[selectedIndex] ? `command-option-${flatList[selectedIndex].id}` : undefined}
            aria-autocomplete="list"
          />
          <kbd className="command-palette-esc">Esc</kbd>
        </div>

        <div className="command-palette-list" ref={listRef} id="command-palette-listbox" role="listbox" aria-label={t('commands_aria')}>
          {flatList.length === 0 && !searching && (
            <div className="command-palette-empty">{t('no_results')}</div>
          )}
          {Array.from(sections).map(([section, items]) => (
            <div key={section} className="command-palette-section">
              <div className="command-palette-section-label">{section}</div>
              {items.map(action => {
                const idx = globalIndex++;
                return (
                  <button
                    key={action.id}
                    id={`command-option-${action.id}`}
                    className={`command-palette-item ${idx === selectedIndex ? 'selected' : ''}`}
                    data-index={idx}
                    role="option"
                    aria-selected={idx === selectedIndex}
                    onClick={() => executeAction(action)}
                    onMouseEnter={() => setSelectedIndex(idx)}
                  >
                    <span className="command-palette-item-label">
                      <span className="command-palette-item-title">{action.label}</span>
                      {action.sublabel && (
                        <span className="command-palette-item-sublabel">{action.sublabel}</span>
                      )}
                    </span>
                    {action.shortcut && (
                      <kbd className="command-palette-item-shortcut">{action.shortcut}</kbd>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
