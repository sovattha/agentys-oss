import { useState, useEffect, useRef, type MutableRefObject, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { ContactStyleProfile, FormalityLevel, LanguageVariant } from '../types/training';
import { InlineRule } from './InlineRule';
import { ContactAutocomplete } from './compose/ContactAutocomplete';
import { LanguagePicker, LocaleVariantPicker } from './LocalePickers';
import { formatLanguageLabel, formatVariantLabel } from './localePickerLabels';
import { Button } from './ui/button';
import { GhostAddRow } from './ui/GhostAddRow';
import { ChevronRightIcon, EditIcon, TrashIcon } from './icons/ActionIcons';
import { getInitials as getAvatarInitials } from './Avatar';

interface DraftRuleItem {
  id: string;
  rule_text: string;
  contact: string;
  confidence: number;
  active: boolean;
  [key: string]: unknown;
}

interface ContactStyleEditorProps {
  contacts: ContactStyleProfile[];
  onSave: (data: {
    contact_email: string;
    formality_override: FormalityLevel | null;
    preferred_greeting: string | null;
    preferred_closing: string | null;
    langue_variante?: LanguageVariant | null;
    langue?: string | null;
    nickname?: string | null;
    formality_locked?: boolean;
  }) => Promise<{ error?: string }>;
  onDelete: (email: string) => void;
  contactRules?: DraftRuleItem[];
  onToggleRule?: (id: string, active: boolean) => void;
  onDeleteRule?: (id: string) => void;
  pendingCardSaveRef?: MutableRefObject<(() => Promise<{ error?: string } | void>) | null>;
}

// ── Helpers ──────────────────────────────────────────────────────────

// Initiales : déléguées au canon Avatar.getInitials (règle unique « toujours
// 2 lettres », 2026-06-09) — la signature locale email-only est conservée.
function getInitials(email: string): string {
  return getAvatarInitials(null, email);
}

const AVATAR_COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#3b82f6', '#ef4444', '#14b8a6'];
function avatarColor(email: string): string {
  const hash = [...email].reduce((acc, c) => acc + c.charCodeAt(0), 0);
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

/**
 * Hide contacts that the learning pipeline picked up but could not classify:
 * no formality, no greeting/closing, no language info and no persisted nickname.
 * Empty cards otherwise pollute the list and look like bugs to the user.
 * Manual edits always produce at least one truthy field, so they stay visible.
 */
function hasClassification(c: ContactStyleProfile): boolean {
  return !!(
    c.nickname ||
    c.formality_override ||
    c.preferred_greeting ||
    c.preferred_closing ||
    c.langue ||
    c.langue_variante
  );
}

function detectVariantFromDomain(email: string): string {
  const domain = email.split('@')[1]?.toLowerCase() || '';
  if (domain.includes('.qc.ca') || domain.endsWith('.gouv.qc.ca')) return 'fr-CA';
  if (domain.endsWith('.fr') || domain.includes('.gouv.fr')) return 'fr-FR';
  if (domain.endsWith('.be')) return 'fr-BE';
  if (domain.endsWith('.ch')) return 'fr-CH';
  if (domain.endsWith('.co.uk') || domain.endsWith('.uk')) return 'en-GB';
  if (domain.endsWith('.es')) return 'es-ES';
  if (domain.endsWith('.com.br') || domain.endsWith('.br')) return 'pt-BR';
  if (domain.endsWith('.com.au') || domain.endsWith('.au')) return 'en-AU';
  if (domain.endsWith('.mx')) return 'es-MX';
  return '';
}

// ── Greeting template helpers ────────────────────────────────────────
//
// Per-contact greetings are stored as templates with {first_name} so the
// recipient's name isn't duplicated with the separately-stored nickname.
// The UI renders expanded form for readability; save tokenizes back.
// Mirrors Python app/prompts/identity.py:_tokenize_greeting and
// smart_routing.py:_expand_greeting_template — same anchor list.

const GREETING_ANCHORS_SRC =
  '(?:Bonjour|Salut|Hi|Hello|Hey|Dear|Coucou|Ol[aá]|Hola|Cher|Ch[eèéê]res?)';

function expandGreetingPreview(template: string, nickname: string): string {
  if (!template || !template.includes('{')) return template;
  const first = nickname || '';
  return template
    .replace(/\{first_name\}/g, first)
    .replace(/\{last_name\}/g, first)
    .replace(/\{civility\}/g, '')
    .replace(/\s+/g, ' ')
    .replace(/\s+,/g, ',')
    .trim();
}

function tokenizeGreeting(text: string, nickname: string): string {
  if (!text || !nickname) return text;
  if (text.includes('{first_name}') || text.includes('{last_name}') || text.includes('{civility}')) {
    return text;
  }
  const escaped = nickname.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`(^\\s*${GREETING_ANCHORS_SRC}\\s+)${escaped}\\b`, 'i');
  return text.replace(pattern, '$1{first_name}');
}

// Locate the recipient's name inside an (expanded) greeting, anchored right
// after a greeting word — the same anchored position tokenizeGreeting
// recognises, so we never match a name that appears incidentally in body-like
// text. Returns the expanded greeting plus the [start, end) span of the name,
// or null when there's no nickname / no anchored match. Shared by the chip
// renderer and the nickname-row dedup so they can never disagree.
function findGreetingNameMatch(
  greeting: string,
  nickname: string,
): { expanded: string; start: number; end: number } | null {
  const expanded = expandGreetingPreview(greeting, nickname);
  const name = nickname.trim();
  if (!expanded || !name) return null;
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`(^\\s*${GREETING_ANCHORS_SRC}\\s+)(${escaped})\\b`, 'i').exec(expanded);
  if (!match) return null;
  const start = match.index + match[1].length;
  return { expanded, start, end: start + match[2].length };
}

// True when the greeting already surfaces the nickname (chipped) — used to drop
// the now-redundant standalone "Nickname" row in the read view.
function greetingContainsNickname(greeting: string, nickname: string): boolean {
  return findGreetingNameMatch(greeting, nickname) !== null;
}

// Render a greeting with the recipient's name shown as an inline chip, so the
// per-contact card makes the greeting↔nickname link explicit instead of
// reading as the name typed twice (the "I see the nickname in the greeting"
// confusion). Works on both tokenized greetings ("Bonjour {first_name},") and
// legacy literal ones ("Bonjour Alexandre,").
function renderGreetingChips(greeting: string, nickname: string): ReactNode {
  const m = findGreetingNameMatch(greeting, nickname);
  if (!m) return expandGreetingPreview(greeting, nickname);
  const { expanded, start, end } = m;
  const after = expanded.slice(end);
  // When punctuation hugs the name ("…amour,") the chip's symmetric padding
  // shoves the comma off the word ("amour ,"), which reads wrong — especially
  // in French. Tighten the trailing edge so the comma sits against the name.
  const punctFollows = /^[,.!?;:]/.test(after);
  return (
    <>
      {expanded.slice(0, start)}
      <span className={`greeting-name-chip${punctFollows ? ' greeting-name-chip--tight-end' : ''}`}>
        {expanded.slice(start, end)}
      </span>
      {after}
    </>
  );
}

// ── Constants ────────────────────────────────────────────────────────

const FORMALITY_OPTIONS: FormalityLevel[] = ['formal', 'mixed', 'casual'];

// ── Relative-time formatter ──────────────────────────────────────────
//
// Used by the per-contact card to render the "Updated <…>" caption next
// to the auto/locked badge. Falls back to `Intl.RelativeTimeFormat` when
// available (every modern Tauri/WebView2 build), otherwise a tiny manual
// path that still produces a sensible string.

function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return '';
  const diffSec = Math.round((ts - Date.now()) / 1000);
  const abs = Math.abs(diffSec);
  // Pick the right unit. Stay coarse on purpose — a "Updated 12 days ago"
  // copy is more digestible than "Updated 1,043,200 seconds ago".
  const cuts: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['year',   60 * 60 * 24 * 365],
    ['month',  60 * 60 * 24 * 30],
    ['week',   60 * 60 * 24 * 7],
    ['day',    60 * 60 * 24],
    ['hour',   60 * 60],
    ['minute', 60],
    ['second', 1],
  ];
  for (const [unit, seconds] of cuts) {
    if (abs >= seconds || unit === 'second') {
      const value = Math.round(diffSec / seconds);
      try {
        const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
        return rtf.format(value, unit);
      } catch {
        const rounded = Math.abs(value);
        const suffix = diffSec < 0 ? ' ago' : ' from now';
        return `${rounded} ${unit}${rounded === 1 ? '' : 's'}${suffix}`;
      }
    }
  }
  return '';
}

// ── Sub-component: ContactCard ────────────────────────────────────────

interface ContactCardProps {
  c: ContactStyleProfile;
  isExpanded: boolean;
  isEditing: boolean;
  rulesForContact: DraftRuleItem[];
  onToggleExpand: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onDelete: () => void;
  onSave: (data: {
    contact_email: string;
    formality_override: FormalityLevel | null;
    preferred_greeting: string | null;
    preferred_closing: string | null;
    langue_variante?: LanguageVariant | null;
    langue?: string | null;
    nickname?: string | null;
    formality_locked?: boolean;
  }) => Promise<{ error?: string }>;
  onToggleRule?: (id: string, active: boolean) => void;
  onDeleteRule?: (id: string) => void;
  pendingCardSaveRef?: MutableRefObject<(() => Promise<{ error?: string } | void>) | null>;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function ContactCard({
  c, isExpanded, isEditing, rulesForContact,
  onToggleExpand, onStartEdit, onCancelEdit, onDelete, onSave,
  onToggleRule, onDeleteRule, pendingCardSaveRef, t,
}: ContactCardProps) {
  const [formality, setFormality] = useState<FormalityLevel>(
    c.formality_override || 'casual'
  );
  // Greeting is held as two pieces:
  //  • greetingTemplate — the canonical, persisted form ("Bonjour {first_name},").
  //    Seeded by tokenising the stored value against the nickname so legacy
  //    literal greetings ("Bonjour Alexandre,") become token-backed on edit.
  //  • greetingDraft — the raw text shown in the input. Kept separate so typing
  //    stays lossless (re-expanding every keystroke would let
  //    expandGreetingPreview's trim/whitespace-collapse eat a trailing space).
  // Changing the *nickname* re-derives the draft from the template, so the
  // greeting re-syncs instead of freezing a stale name — the desync footgun fix
  // (save-time re-tokenisation used to persist "Bonjour Alexandre," next to a
  // nickname of "Alex").
  const [greetingTemplate, setGreetingTemplate] = useState(() =>
    tokenizeGreeting(c.preferred_greeting || '', c.nickname || '')
  );
  const [greetingDraft, setGreetingDraft] = useState(() =>
    expandGreetingPreview(
      tokenizeGreeting(c.preferred_greeting || '', c.nickname || ''),
      (c.nickname || '').trim(),
    )
  );
  const [closing, setClosing] = useState(c.preferred_closing || '');
  const [langueVariante, setLangueVariante] = useState<string>(c.langue_variante || '');
  const [langue, setLangue] = useState(c.langue || '');
  const [localNickname, setLocalNickname] = useState(c.nickname || '');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  // Sync localNickname with the persisted value whenever edit mode closes so
  // the form always opens with the value currently shown in the badge.
  useEffect(() => {
    if (!isEditing) setLocalNickname(c.nickname || '')
  }, [c.nickname, isEditing])

  const formalityLabel = (f: FormalityLevel) =>
    f === 'formal' ? t('style_contact_formality_formal')
    : f === 'mixed' ? t('style_contact_formality_semi_formal')
    : t('style_contact_formality_casual');

  // Release the formality lock — next sent email will re-derive the
  // override from the body. We pass `formality_locked: false` explicitly;
  // the backend keeps the current value (no clear) so the user still sees
  // a sensible chip until the next send produces a different level.
  const handleReleaseLock = async () => {
    if (!c.formality_override) return;
    setSaving(true);
    setError('');
    const result = await onSave({
      contact_email: c.email,
      formality_override: c.formality_override,
      preferred_greeting: c.preferred_greeting,
      preferred_closing: c.preferred_closing,
      langue_variante: c.langue_variante,
      langue: c.langue,
      nickname: c.nickname || null,
      formality_locked: false,
    });
    setSaving(false);
    if (result?.error) setError(result.error);
  };

  const handleSave = async (): Promise<{ error?: string } | void> => {
    setSaving(true);
    setError('');
    const trimmedNick = localNickname.trim();
    // Manual edits in the Training UI always lock the formality field —
    // otherwise the next sent email would silently overwrite the user's
    // chosen value via the post-send auto-derivation path.
    // `greetingTemplate` is already tokenised (kept in sync on every keystroke
    // against the live nickname), so persist it verbatim — no fragile
    // save-time re-tokenisation that could miss a since-changed nickname.
    const result = await onSave({
      contact_email: c.email,
      formality_override: formality,
      preferred_greeting: greetingTemplate.trim() || null,
      preferred_closing: closing.trim() || null,
      langue_variante: langueVariante || null,
      langue: langue || null,
      nickname: trimmedNick || null,
      formality_locked: true,
    });
    setSaving(false);
    if (result?.error === 'contact_blocked') {
      const msg = t('style_contact_error_blocked');
      setError(msg);
      return { error: msg };
    } else if (result?.error === 'contact_noise') {
      const msg = t('style_contact_error_noise');
      setError(msg);
      return { error: msg };
    } else if (result?.error) {
      setError(result.error);
      return { error: result.error };
    } else {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: t('common:toasts.contact_style_saved'), type: 'success' },
      }));
      onCancelEdit();
      return;
    }
  };

  // Register this card's save fn so the main footer Save in TrainingPage
  // can flush in-flight edits before serializing the markdown. The
  // ref-of-ref pattern keeps the registered function stable across
  // renders while always calling the latest ``handleSave`` closure.
  const handleSaveRef = useRef(handleSave);
  handleSaveRef.current = handleSave;
  useEffect(() => {
    if (!pendingCardSaveRef) return;
    if (isEditing) {
      pendingCardSaveRef.current = () => handleSaveRef.current();
    }
    return () => {
      if (pendingCardSaveRef && pendingCardSaveRef.current) {
        pendingCardSaveRef.current = null;
      }
    };
  }, [isEditing, pendingCardSaveRef]);

  const initials = getInitials(c.email);
  const color = avatarColor(c.email);

  return (
    <div className={`contact-card${isExpanded ? ' contact-card--expanded' : ''}`}>
      {/* Card header — always visible. Outer wrapper is a flex row, not a
          button, so we can sit the pencil/delete actions inside the header
          (HTML forbids nested buttons). The toggle is a child button that
          covers avatar + name + badges. */}
      <div className="contact-card-header">
        <button
          type="button"
          className="contact-card-header-toggle"
          onClick={onToggleExpand}
          aria-expanded={isExpanded}
        >
          <div className="contact-card-avatar" style={{ backgroundColor: color }}>
            {initials}
          </div>
          <div className="contact-card-header-main">
            <span className="contact-card-name">{c.email}</span>
            {/* Badges duplicate the field rows once the card is expanded, so
                only show them as the collapsed summary. */}
            {!isExpanded && (
              <div className="contact-card-badges">
                {c.nickname && (
                  <span className="contact-card-badge contact-card-badge--nickname">
                    {c.nickname}
                  </span>
                )}
                {c.formality_override && (
                  <span className="contact-card-badge contact-card-badge--alt">
                    {formalityLabel(c.formality_override)}
                  </span>
                )}
                {c.langue && (
                  <span className="contact-card-badge contact-card-badge--alt">
                    {formatLanguageLabel(c.langue)}
                  </span>
                )}
                {c.langue_variante && (
                  <span className="contact-card-badge contact-card-badge--variant">
                    {c.langue_variante}
                  </span>
                )}
              </div>
            )}
            {/* "Updated <relative>" lifted out of the Formality value row and
                shown as a card-level caption next to the email — it's metadata
                about the card, not a property of any single field. */}
            {isExpanded && c.formality_updated_at && (
              <span className="contact-card-header-meta">
                {t('style_contact_updated')} {formatRelativeTime(c.formality_updated_at)}
              </span>
            )}
          </div>
        </button>
        <div className="contact-card-header-actions">
          {isExpanded && !isEditing && (
            <>
              <button
                type="button"
                className="contact-card-icon-btn"
                onClick={e => { e.stopPropagation(); onStartEdit(); }}
                title={t('style_contact_edit')}
                aria-label={t('style_contact_edit')}
              >
                <EditIcon size={14} />
              </button>
              <button
                type="button"
                className="contact-card-icon-btn"
                onClick={e => { e.stopPropagation(); onDelete(); }}
                title={t('style_contact_delete')}
                aria-label={t('style_contact_delete')}
              >
                <TrashIcon size={14} />
              </button>
            </>
          )}
          <ChevronRightIcon
            size={14}
            className={`contact-card-chevron${isExpanded ? ' expanded' : ''}`}
          />
        </div>
      </div>

      {/* Card body — only when expanded */}
      {isExpanded && (
        <div className="contact-card-body">
          {!isEditing ? (
            /* View mode — same order as edit mode */
            <div className="contact-card-view">
              {/* Show the standalone nickname only when it isn't already
                  surfaced (chipped) in the greeting below — otherwise the same
                  name reads twice in one card. */}
              {c.nickname && !greetingContainsNickname(c.preferred_greeting || '', c.nickname) && (
                <div className="contact-card-view-row">
                  <label>{t('style_contact_nicknames')}</label>
                  <span>{c.nickname}</span>
                </div>
              )}
              {c.formality_override && (
                <div className="contact-card-view-row">
                  <label>{t('style_contact_formality')}</label>
                  <span className="contact-card-formality-value">
                    {formalityLabel(c.formality_override)}
                    {/* "Auto" is the default state for every contact, so badging it adds noise
                        without conveying anything. Only show the badge when the row is locked
                        (= user-overridden, won't change automatically). */}
                    {c.formality_locked && (
                      <span
                        className="contact-card-formality-mode contact-card-formality-mode--locked"
                        title={t('style_contact_formality_locked_hint')}
                      >
                        {`🔒 ${t('style_contact_formality_locked')}`}
                      </span>
                    )}
                    {c.formality_locked && (
                      <button
                        type="button"
                        className="contact-card-formality-unlock"
                        onClick={(e) => { e.stopPropagation(); handleReleaseLock(); }}
                        disabled={saving}
                        title={t('style_contact_formality_unlock_hint')}
                      >
                        {t('style_contact_formality_unlock')}
                      </button>
                    )}
                  </span>
                </div>
              )}
              {/* Language + regional variant collapse into one row: the variant
                  already encodes the language (the "fr" in "fr-CA" IS Français),
                  so two label→value pairs on one line read as redundant noise.
                  Render as a single "Langue" value ("Français · Québec (fr-CA)"),
                  keeping the one-field-per-line rhythm of the rest of the card.
                  Either piece may be absent — join only what's present. */}
              {(c.langue || c.langue_variante) && (
                <div className="contact-card-view-row">
                  <label>{t('style_contact_langue')}</label>
                  <span>
                    {[
                      c.langue ? formatLanguageLabel(c.langue) : null,
                      c.langue_variante ? formatVariantLabel(c.langue_variante) : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </div>
              )}
              {c.preferred_greeting && (
                <div className="contact-card-view-row contact-card-view-row--content">
                  <label>{t('style_contact_greeting')}</label>
                  <span>{renderGreetingChips(c.preferred_greeting, c.nickname || '')}</span>
                </div>
              )}
              {c.preferred_closing && (
                <div className="contact-card-view-row contact-card-view-row--content">
                  <label>{t('style_contact_closing')}</label>
                  <span>{c.preferred_closing}</span>
                </div>
              )}
            </div>
          ) : (
            /* Edit mode — mirrors default style structure */
            <div className="contact-card-form">
              {/* 1. Surnom (= nom complet du contact) */}
              <div className="pillar-field">
                <label className="pillar-field-label">{t('style_contact_nicknames')}</label>
                <input
                  className="pillar-field-input"
                  value={localNickname}
                  onChange={e => {
                    const v = e.target.value;
                    setLocalNickname(v);
                    // Re-derive the greeting from the canonical template against
                    // the new name — this is what makes the greeting follow the
                    // nickname instead of freezing.
                    setGreetingDraft(expandGreetingPreview(greetingTemplate, v.trim()));
                  }}
                  placeholder={t('style_add_nickname')}
                  autoFocus
                />
                <span className="pillar-field-hint">{t('style_contact_nickname_hint')}</span>
              </div>

              {/* 3. Formalité (chips — same as default style) */}
              <div className="pillar-field">
                <label className="pillar-field-label">{t('style_contact_formality')}</label>
                <div className="style-emotion-control">
                  {FORMALITY_OPTIONS.map(o => (
                    <button
                      key={o || '__default'}
                      type="button"
                      className={`style-emotion-option${formality === o ? ' active' : ''}`}
                      onClick={() => setFormality(o)}
                    >
                      {formalityLabel(o)}
                    </button>
                  ))}
                </div>
              </div>

              {/* 3b. Langue parlée */}
              <div className="pillar-field">
                <label className="pillar-field-label">{t('style_contact_langue')}</label>
                <LanguagePicker
                  value={langue}
                  onChange={setLangue}
                  autoLabel={t('style_contact_langue_placeholder')}
                  ariaLabel={t('style_contact_langue')}
                />
                <span className="pillar-field-hint">{t('style_contact_langue_hint')}</span>
              </div>

              {/* 3c. Variante linguistique (= variante dans style par défaut) */}
              <div className="pillar-field">
                <label className="pillar-field-label">{t('style_contact_langue_variante')}</label>
                <LocaleVariantPicker
                  value={langueVariante}
                  onChange={setLangueVariante}
                  autoLabel={t('style_langue_variante_none')}
                  ariaLabel={t('style_contact_langue_variante')}
                />
                <span className="pillar-field-hint">{t('style_contact_langue_variante_hint')}</span>
              </div>

              {/* 4. Salutation + Clôture (= salutation/clôture dans style par défaut) */}
              <div className="pillar-field-row">
                <div className="pillar-field">
                  <label className="pillar-field-label">{t('style_contact_greeting')}</label>
                  <input
                    className="pillar-field-input"
                    value={greetingDraft}
                    onChange={e => {
                      const v = e.target.value;
                      setGreetingDraft(v);
                      setGreetingTemplate(tokenizeGreeting(v, localNickname.trim()));
                    }}
                    placeholder={t('style_greeting_placeholder_named', { first_name: 'Jean' })}
                  />
                  <span className="pillar-field-hint">{t('style_contact_nicknames_hint')}</span>
                </div>
                <div className="pillar-field">
                  <label className="pillar-field-label">{t('style_contact_closing')}</label>
                  <input
                    className="pillar-field-input"
                    value={closing}
                    onChange={e => setClosing(e.target.value)}
                    placeholder={t('style_closing_placeholder_formal')}
                  />
                </div>
              </div>

              {error && <p className="style-contact-error">{error}</p>}

              <div className="contact-card-form-actions">
                <Button type="button" onClick={handleSave} disabled={saving}>
                  {saving ? '...' : t('style_contact_save')}
                </Button>
                <Button type="button" variant="outline" onClick={onCancelEdit}>
                  {t('style_contact_cancel')}
                </Button>
              </div>

            </div>
          )}

          {/* Inline learned rules for this contact */}
          {onToggleRule && onDeleteRule && rulesForContact.length > 0 && (
            <div className="style-inline-rules style-inline-rules--contact">
              <span className="style-inline-rules-title">
                {t('style_learned_rules_title')} · {rulesForContact.length}
              </span>
              {rulesForContact.map(rule => (
                <InlineRule key={rule.id} rule={rule} onToggle={onToggleRule} onDelete={onDeleteRule} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── New-contact form card ─────────────────────────────────────────────

interface NewContactCardProps {
  onSave: (data: {
    contact_email: string;
    formality_override: FormalityLevel | null;
    preferred_greeting: string | null;
    preferred_closing: string | null;
    langue_variante?: LanguageVariant | null;
    langue?: string | null;
    nickname?: string | null;
    formality_locked?: boolean;
  }) => Promise<{ error?: string }>;
  onCancel: () => void;
  onCreated: (email: string) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function NewContactCard({ onSave, onCancel, onCreated, t }: NewContactCardProps) {
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [formality, setFormality] = useState<FormalityLevel>('casual');
  // Canonical template + raw input draft (see ContactCard for the rationale).
  // Keeping them separate makes typing lossless while the name still re-syncs
  // when the nickname changes.
  const [greetingTemplate, setGreetingTemplate] = useState('');
  const [greetingDraft, setGreetingDraft] = useState('');
  const [closing, setClosing] = useState('');
  const [langueVariante, setLangueVariante] = useState('');
  const [langue, setLangue] = useState('');
  const [nickname, setNickname] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const formalityLabel = (f: FormalityLevel) =>
    f === 'formal' ? t('style_contact_formality_formal')
    : f === 'mixed' ? t('style_contact_formality_semi_formal')
    : t('style_contact_formality_casual');

  const handleSave = async () => {
    const trimmed = email.trim().toLowerCase();
    if (!trimmed) return;
    setSaving(true);
    setError('');
    const trimmedNick = nickname.trim();
    const result = await onSave({
      contact_email: trimmed,
      formality_override: formality,
      preferred_greeting: greetingTemplate.trim() || null,
      preferred_closing: closing.trim() || null,
      langue_variante: langueVariante || null,
      langue: langue || null,
      nickname: trimmedNick || null,
    });
    setSaving(false);
    if (result?.error === 'contact_blocked') {
      setError(t('style_contact_error_blocked'));
    } else if (result?.error === 'contact_noise') {
      setError(t('style_contact_error_noise'));
    } else if (result?.error) {
      setError(result.error);
    } else {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: t('common:toasts.contact_saved'), type: 'success' },
      }));
      onCreated(trimmed);
    }
  };

  return (
    <div className="contact-card contact-card--new contact-card--expanded">
      <div className="contact-card-body" style={{ paddingTop: 12 }}>
        <div className="contact-card-form">
          {/* 1. Email du contact */}
          <div className="pillar-field">
            <label className="pillar-field-label">{t('style_contact_email')}</label>
            <ContactAutocomplete
              value={email}
              onChange={val => {
                setEmail(val);
                if (!langueVariante) {
                  const detected = detectVariantFromDomain(val);
                  if (detected) setLangueVariante(detected);
                }
              }}
              onContactSelect={contact => {
                const val = contact.email.toLowerCase();
                setEmail(val);
                if (!fullName && contact.name && contact.name !== contact.email) {
                  setFullName(contact.name);
                }
                if (!langueVariante) {
                  const detected = detectVariantFromDomain(val);
                  if (detected) setLangueVariante(detected);
                }
              }}
              multi={false}
              placeholder="alex@agentys.app"
              className="pillar-contact-autocomplete"
              includeAllContacts
            />
          </div>

          {/* 2. Nom complet */}
          <div className="pillar-field">
            <label className="pillar-field-label">{t('style_contact_fullname')}</label>
            <input
              className="pillar-field-input"
              value={fullName}
              onChange={e => setFullName(e.target.value)}
              placeholder={t('style_contact_fullname_placeholder')}
            />
          </div>

          {/* 3. Surnom */}
          <div className="pillar-field">
            <label className="pillar-field-label">{t('style_contact_nickname_label')}</label>
            <input
              className="pillar-field-input"
              value={nickname}
              onChange={e => {
                const v = e.target.value;
                setNickname(v);
                setGreetingDraft(expandGreetingPreview(greetingTemplate, v.trim()));
              }}
              placeholder={t('style_add_nickname')}
            />
            <span className="pillar-field-hint">{t('style_contact_nickname_hint')}</span>
          </div>

          <div className="pillar-field">
            <label className="pillar-field-label">{t('style_contact_formality')}</label>
            <div className="style-emotion-control">
              {FORMALITY_OPTIONS.map(o => (
                <button
                  key={o || '__default'}
                  type="button"
                  className={`style-emotion-option${formality === o ? ' active' : ''}`}
                  onClick={() => setFormality(o)}
                >
                  {formalityLabel(o)}
                </button>
              ))}
            </div>
          </div>

          <div className="pillar-field">
            <label className="pillar-field-label">{t('style_contact_langue')}</label>
            <LanguagePicker
              value={langue}
              onChange={setLangue}
              autoLabel={t('style_contact_langue_placeholder')}
              ariaLabel={t('style_contact_langue')}
            />
            <span className="pillar-field-hint">{t('style_contact_langue_hint')}</span>
          </div>

          <div className="pillar-field">
            <label className="pillar-field-label">{t('style_contact_langue_variante')}</label>
            <LocaleVariantPicker
              value={langueVariante}
              onChange={setLangueVariante}
              autoLabel={t('style_langue_variante_none')}
              ariaLabel={t('style_contact_langue_variante')}
            />
            <span className="pillar-field-hint">{t('style_contact_langue_variante_hint')}</span>
          </div>

          <div className="pillar-field-row">
            <div className="pillar-field">
              <label className="pillar-field-label">{t('style_contact_greeting')}</label>
              <input
                className="pillar-field-input"
                value={greetingDraft}
                onChange={e => {
                  const v = e.target.value;
                  setGreetingDraft(v);
                  setGreetingTemplate(tokenizeGreeting(v, nickname.trim()));
                }}
                placeholder={t('style_greeting_placeholder_named', { first_name: 'Jean' })}
              />
              <span className="pillar-field-hint">{t('style_contact_nicknames_hint')}</span>
            </div>
            <div className="pillar-field">
              <label className="pillar-field-label">{t('style_contact_closing')}</label>
              <input
                className="pillar-field-input"
                value={closing}
                onChange={e => setClosing(e.target.value)}
                placeholder={t('style_closing_placeholder_formal')}
              />
            </div>
          </div>

          {error && <p className="style-contact-error">{error}</p>}

          <div className="contact-card-form-actions">
            <Button type="button" onClick={handleSave} disabled={!email.trim() || saving}>
              {saving ? '...' : t('style_contact_save')}
            </Button>
            <Button type="button" variant="outline" onClick={onCancel}>
              {t('style_contact_cancel')}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────

export function ContactStyleEditor({
  contacts, onSave, onDelete,
  contactRules = [], onToggleRule, onDeleteRule, pendingCardSaveRef,
}: ContactStyleEditorProps) {
  const { t } = useTranslation('agents');
  const [expandedEmail, setExpandedEmail] = useState<string | null>(null);
  const [editingEmail, setEditingEmail] = useState<string | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [filter, setFilter] = useState('');

  const toggleExpand = (email: string) => {
    if (expandedEmail === email) {
      setExpandedEmail(null);
      if (editingEmail === email) setEditingEmail(null);
    } else {
      setExpandedEmail(email);
      setEditingEmail(null);
    }
  };

  const classifiedContacts = contacts.filter(c => hasClassification(c));

  if (classifiedContacts.length === 0 && !showNewForm) {
    return (
      <div className="style-contact-editor">
        <p className="style-detected-empty">{t('style_contact_empty')}</p>
        <p className="pillar-field-hint">{t('style_contact_empty_hint')}</p>
        <button
          type="button"
          className="pillar-add-btn"
          onClick={() => setShowNewForm(true)}
          style={{ marginTop: 8 }}
        >
          + {t('style_contact_add')}
        </button>
      </div>
    );
  }

  const filterLower = filter.toLowerCase();
  const filteredContacts = filter
    ? classifiedContacts.filter(c =>
        c.email.toLowerCase().includes(filterLower) ||
        (c.nickname || '').toLowerCase().includes(filterLower)
      )
    : classifiedContacts;

  return (
    <div className="style-contact-editor">
      {classifiedContacts.length >= 5 && (
        <input
          className="pillar-field-input style-contact-filter"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder={t('style_contact_filter_placeholder')}
        />
      )}
      {filteredContacts.map(c => (
        <ContactCard
          key={c.email}
          c={c}
          isExpanded={expandedEmail === c.email}
          isEditing={editingEmail === c.email}
          rulesForContact={contactRules.filter(r => r.contact === c.email)}
          onToggleExpand={() => toggleExpand(c.email)}
          onStartEdit={() => setEditingEmail(c.email)}
          onCancelEdit={() => setEditingEmail(null)}
          onDelete={() => {
            onDelete(c.email);
            if (expandedEmail === c.email) setExpandedEmail(null);
          }}
          onSave={onSave}
          onToggleRule={onToggleRule}
          onDeleteRule={onDeleteRule}
          pendingCardSaveRef={pendingCardSaveRef}
          t={t}
        />
      ))}

      {showNewForm ? (
        <NewContactCard
          onSave={onSave}
          onCancel={() => setShowNewForm(false)}
          onCreated={email => {
            setShowNewForm(false);
            setExpandedEmail(email);
          }}
          t={t}
        />
      ) : (
        <GhostAddRow
          label={t('style_contact_add')}
          onClick={() => setShowNewForm(true)}
        />
      )}
    </div>
  );
}
