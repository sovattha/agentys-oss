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

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchNewsletters, unsubscribeAndPurge, bulkDeleteNewsletters, labelNewsletter, type Newsletter } from '../api/emails';
import { openUrl } from '../utils/openUrl';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { ChevronLeftIcon, CloseIcon, TrashIcon, CheckIcon } from './icons/ActionIcons';
import './NewslettersModal.css';

const NL_LABELS_KEY = 'agentys_nl_labels';

interface NewslettersModalProps {
  onClose: () => void;
}

type ModalState = 'loading' | 'loaded' | 'error' | 'empty';
type LabelState = 'FYI' | 'Noise' | null;
type UnsubStatus = 'pending' | 'done' | 'partial' | 'failed';

const COLORS = [
  '#059669', '#0891b2', '#2563eb', '#7c3aed',
  '#c026d3', '#e11d48', '#dc2626', '#ea580c',
  '#d97706', '#65a30d',
];

function getColorForDomain(domain: string): string {
  let hash = 0;
  for (let i = 0; i < domain.length; i++) {
    hash = domain.charCodeAt(i) + ((hash << 5) - hash);
  }
  return COLORS[Math.abs(hash) % COLORS.length];
}

function loadSavedLabels(): Record<string, LabelState> {
  try {
    const stored = localStorage.getItem(NL_LABELS_KEY);
    return stored ? JSON.parse(stored) : {};
  } catch {
    return {};
  }
}

function saveLabels(labels: Record<string, LabelState>) {
  try {
    localStorage.setItem(NL_LABELS_KEY, JSON.stringify(labels));
  } catch { /* silent */ }
}

export function NewslettersModal({ onClose }: NewslettersModalProps) {
  const { t } = useTranslation('settings');
  const [newsletters, setNewsletters] = useState<Newsletter[]>([]);
  const [state, setState] = useState<ModalState>('loading');
  const [errorMessage, setErrorMessage] = useState('');
  const [unsubscribing, setUnsubscribing] = useState<Record<string, UnsubStatus>>({});
  const [unsubMessages, setUnsubMessages] = useState<Record<string, string>>({});
  const [removingDomain, setRemovingDomain] = useState<string | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [labels, setLabels] = useState<Record<string, LabelState>>(loadSavedLabels);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);

  const loadNewsletters = useCallback(async () => {
    setState('loading');
    setErrorMessage('');
    try {
      const data = await fetchNewsletters();
      setNewsletters(data.newsletters);
      setState(data.newsletters.length === 0 ? 'empty' : 'loaded');
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : t('newsletters_loading'));
      setState('error');
    }
  }, [t]);

  useEffect(() => {
    loadNewsletters();
  }, [loadNewsletters]);


  const handleLabel = useCallback(async (nl: Newsletter, label: LabelState) => {
    // Functional updater évite toute stale closure — toujours l'état le plus récent
    let prevLabel: LabelState = null;
    let next: LabelState = label;
    setLabels(prev => {
      const current = prev[nl.domain];
      prevLabel = current ?? null;
      next = current === label ? null : label;
      const updated = { ...prev, [nl.domain]: next };
      saveLabels(updated);
      return updated;
    });
    try {
      await labelNewsletter(nl.sender, next);
    } catch {
      // FE-04: the server rejected the change. Roll back the optimistic
      // local + localStorage update (it used to silently diverge from the
      // server and only snap back on the next reload) and tell the user.
      setLabels(prev => {
        const reverted = { ...prev, [nl.domain]: prevLabel };
        saveLabels(reverted);
        return reverted;
      });
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: t('newsletter_label_failed'), type: 'error', duration: 5000 },
      }));
    }
  }, [t]);

  const handleUnsubscribe = useCallback(async (nl: Newsletter) => {
    setUnsubscribing(prev => ({ ...prev, [nl.domain]: 'pending' }));
    setUnsubMessages(prev => { const n = { ...prev }; delete n[nl.domain]; return n; });
    try {
      const result = await unsubscribeAndPurge(
        nl.sender,
        nl.unsubscribe_url || '',
        nl.unsubscribe_mailto || '',
      );

      // Fallback UI : si aucune méthode distante n'a marché ET qu'on n'a même
      // pas bloqué localement, on ouvre l'URL dans le navigateur pour que
      // l'utilisateur puisse se désabonner manuellement.
      if (result.unsubscribe_method === 'none' && !result.blocked && nl.unsubscribe_url) {
        try { await openUrl(nl.unsubscribe_url); } catch { /* silent */ }
      }

      const remoteOk =
        result.unsubscribe_method !== 'none' && result.unsubscribe_method !== 'blocked_only';
      const finalStatus: UnsubStatus = remoteOk
        ? 'done'
        : result.blocked
          ? 'partial'
          : 'failed';

      setUnsubMessages(prev => ({ ...prev, [nl.domain]: result.message }));

      if (finalStatus === 'failed') {
        setUnsubscribing(prev => ({ ...prev, [nl.domain]: 'failed' }));
        return;
      }

      setUnsubscribing(prev => ({ ...prev, [nl.domain]: finalStatus }));
      setRemovingDomain(nl.domain);
      setTimeout(() => {
        setNewsletters(prev => prev.filter(n => n.domain !== nl.domain));
        setRemovingDomain(null);
        setUnsubscribing(prev => { const n = { ...prev }; delete n[nl.domain]; return n; });
        setLabels(prev => { const n = { ...prev }; delete n[nl.domain]; saveLabels(n); return n; });
      }, 800);
    } catch {
      setUnsubscribing(prev => ({ ...prev, [nl.domain]: 'failed' }));
    }
  }, []);

  const handleBulkDelete = useCallback(async () => {
    if (bulkDeleting) return;
    if (!confirmBulkDelete) {
      setConfirmBulkDelete(true);
      setTimeout(() => setConfirmBulkDelete(false), 4000);
      return;
    }
    setConfirmBulkDelete(false);
    setBulkDeleting(true);
    try {
      await bulkDeleteNewsletters(0);
      await loadNewsletters();
    } catch (err) {
      // Audit Cluster D (2026-05-17) F-12: a silently swallowed bulk delete
      // left the list looking unchanged, so the user assumed the button was
      // broken. Surface the failure and let them retry.
      console.warn('[NewslettersModal] bulkDeleteNewsletters failed:', err);
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: t('common:toasts.newsletters_bulk_delete_failed'),
          type: 'error',
          duration: 6000,
        },
      }));
    }
    finally { setBulkDeleting(false); }
  }, [bulkDeleting, confirmBulkDelete, loadNewsletters, t]);

  const totalEmails = newsletters.reduce((sum, nl) => sum + nl.email_count, 0);

  return (
    <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
      <DialogContent className="newsletters-modal" showCloseButton={false} aria-describedby={undefined}>

        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="nl-header">
          <button className="nl-back" onClick={onClose} aria-label={t('common:back', 'Retour')}>
            <ChevronLeftIcon size={16} />
          </button>
          <div className="nl-header-center">
            <DialogTitle className="nl-title">{t('newsletters_title')}</DialogTitle>
            <p className="nl-subtitle">{t('newsletters_subtitle')}</p>
          </div>
          <button className="nl-close" onClick={onClose} aria-label={t('newsletters_close', 'Fermer')}>
            <CloseIcon size={16} />
          </button>
        </div>

        {/* ── Loading ────────────────────────────────────────────────────── */}
        {state === 'loading' && (
          <div className="nl-state-center">
            <span className="nl-spinner" />
            <p>{t('newsletters_loading')}</p>
          </div>
        )}

        {/* ── Error ─────────────────────────────────────────────────────── */}
        {state === 'error' && (
          <div className="nl-state-center nl-state-error">
            <p>{errorMessage}</p>
            <button className="nl-retry-btn" onClick={loadNewsletters}>
              {t('newsletters_error_retry')}
            </button>
          </div>
        )}

        {/* ── Empty ─────────────────────────────────────────────────────── */}
        {state === 'empty' && (
          <div className="nl-state-center">
            <span className="nl-empty-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                <polyline points="22,6 12,13 2,6" />
              </svg>
            </span>
            <p>{t('newsletters_empty')}</p>
          </div>
        )}

        {/* ── Loaded ────────────────────────────────────────────────────── */}
        {state === 'loaded' && (
          <>
            {/* Stats bar */}
            <div className="nl-stats-bar">
              <span className="nl-stats-count">
                <strong>{newsletters.length}</strong> {t('newsletters_count_label', 'infolettres')}
                <span className="nl-stats-sep">&middot;</span>
                <strong>{totalEmails}</strong> emails
              </span>

              <div className="nl-stats-actions">
                <button
                  className={`nl-bulk-delete-btn ${confirmBulkDelete ? 'nl-bulk-delete-btn--confirm' : ''}`}
                  onClick={handleBulkDelete}
                  disabled={bulkDeleting}
                >
                  {bulkDeleting ? (
                    <><span className="nl-btn-spinner" />{t('newsletters_deleting', 'Suppression…')}</>
                  ) : confirmBulkDelete ? (
                    <>{t('newsletters_confirm_delete', 'Confirmer la suppression ?')}</>
                  ) : (
                    <>
                      <TrashIcon size={12} />
                      {t('newsletters_delete_all', 'Tout supprimer')}
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* List */}
            <div className="nl-list">
              {newsletters.map((nl, idx) => {
                const status = unsubscribing[nl.domain];
                const currentLabel = labels[nl.domain] ?? null;
                const isRemoving = removingDomain === nl.domain;

                return (
                  <div
                    key={nl.domain}
                    className={[
                      'nl-item',
                      status === 'done'     ? 'nl-item--done'    : '',
                      isRemoving            ? 'nl-item--removing' : '',
                      currentLabel === 'FYI'   ? 'nl-item--info'  : '',
                      currentLabel === 'Noise' ? 'nl-item--bruit' : '',
                    ].filter(Boolean).join(' ')}
                    style={{ '--nl-idx': idx } as React.CSSProperties}
                  >
                    <div
                      className="nl-avatar"
                      style={{ backgroundColor: getColorForDomain(nl.domain) }}
                      aria-hidden="true"
                    >
                      {nl.service_name.charAt(0).toUpperCase()}
                    </div>

                    <div className="nl-info">
                      <div className="nl-name-row">
                        <span className="nl-name">{nl.service_name}</span>
                        <span className={`nl-count ${nl.email_count > 10 ? 'nl-count--high' : ''}`}>
                          ({nl.email_count})
                        </span>
                      </div>
                      <span className="nl-sender-addr">{nl.sender}</span>
                    </div>

                    <div className="nl-label-actions">
                      <button
                        className={`nl-label-btn nl-label-btn--info ${currentLabel === 'FYI' ? 'nl-label-btn--active' : ''}`}
                        onClick={() => handleLabel(nl, 'FYI')}
                        title={t('newsletters_label_info_title', 'Garder et étiqueter Info')}
                        aria-pressed={currentLabel === 'FYI'}
                      >
                        Info
                      </button>
                      <button
                        className={`nl-label-btn nl-label-btn--bruit ${currentLabel === 'Noise' ? 'nl-label-btn--active' : ''}`}
                        onClick={() => handleLabel(nl, 'Noise')}
                        title={t('newsletters_label_noise_title', 'Étiqueter comme Bruit')}
                        aria-pressed={currentLabel === 'Noise'}
                      >
                        Bruit
                      </button>
                    </div>

                    <div className="nl-unsub-cell">
                      {status === 'done' ? (
                        <span className="nl-done-badge" style={{ color: '#059669' }} aria-label={t('newsletters_unsubscribed', 'Désabonné')} title={unsubMessages[nl.domain] || ''}>
                          <CheckIcon size={14} />
                        </span>
                      ) : status === 'partial' ? (
                        <span className="nl-done-badge nl-done-badge--partial" style={{ color: '#d97706' }} aria-label={t('newsletters_blocked_only', 'Bloqué localement')} title={unsubMessages[nl.domain] || ''}>
                          <CloseIcon size={14} />
                        </span>
                      ) : status === 'pending' ? (
                        <span className="nl-pending-spinner" />
                      ) : (
                        <button
                          className="nl-unsub-btn"
                          onClick={() => handleUnsubscribe(nl)}
                          title={status === 'failed'
                            ? (unsubMessages[nl.domain] || t('newsletters_unsub_failed', 'Échec — réessayer'))
                            : t('newsletters_unsub_and_delete', 'Se désabonner et supprimer')}
                          aria-label={t('newsletters_unsubscribe_label', { name: nl.service_name })}
                        >
                          <CloseIcon size={14} />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
