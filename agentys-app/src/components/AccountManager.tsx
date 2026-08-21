import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { getApiClient, ApiError, type Account, type CreateAccountRequest, type AccountTokenStatus } from "../services/api";
import { ConnectGmailButton } from "./ConnectGmailButton";
import { ConnectOutlookButton } from "./ConnectOutlookButton";
import { setActiveAccountId } from "../api/emails";
import { setAccountSignatureCache } from "../hooks/useAccountSignature";
import { clearAllUserData } from "../services/clearUserData";
import { safeRandomUUID } from "../utils/uuid";
import ConfirmationDialog from "./ConfirmationDialog";
import { ChevronLeftIcon, CloseIcon, TrashIcon } from "./icons/ActionIcons";
import { Avatar } from "./Avatar";
import { uploadAccountAvatar } from "../api/accounts";
import "./AccountManager.css";

const TriangleLogo = ({ size = 48 }: { size?: number }) => (
  <svg aria-hidden="true" width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M16 2.5L1.5 29.5h29z" stroke="#2dd4bf" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" fill="none" opacity="0.7"/>
    <path d="M16 12L8.5 25h15L16 12z" fill="#0d9488"/>
    <path d="M16 16.5L11.5 23.5h9L16 16.5z" fill="var(--surface-primary, #f0f1f5)"/>
  </svg>
)

interface AccountManagerProps {
  onClose: () => void;
  onBack?: () => void;
  onAccountChanged?: () => void;
  initialReconnect?: { email?: string; provider?: string } | null;
}

type ProviderType = "gmail" | "outlook" | "imap_smtp";

interface NewAccountForm {
  name: string;
  email: string;
  provider: ProviderType;
  signature: string;
  // IMAP/SMTP
  imap_host: string;
  imap_port: string;
  imap_user: string;
  imap_password: string;
  smtp_host: string;
  smtp_port: string;
  smtp_user: string;
  smtp_password: string;
}

const INITIAL_FORM: NewAccountForm = {
  name: "",
  email: "",
  provider: "gmail",
  signature: "",
  imap_host: "",
  imap_port: "993",
  imap_user: "",
  imap_password: "",
  smtp_host: "",
  smtp_port: "587",
  smtp_user: "",
  smtp_password: "",
};

const PROVIDER_LABELS: Record<ProviderType, string> = {
  imap_smtp: "IMAP/SMTP",
  gmail: "Gmail",
  outlook: "Outlook",
};

const IMAP_PRESETS: Record<string, { imap_host: string; imap_port: string; smtp_host: string; smtp_port: string }> = {
  "imap.gmail.com":            { imap_host: "imap.gmail.com",        imap_port: "993", smtp_host: "smtp.gmail.com",        smtp_port: "587" },
  "outlook.office365.com":     { imap_host: "outlook.office365.com", imap_port: "993", smtp_host: "smtp.office365.com",     smtp_port: "587" },
  "imap.mail.yahoo.com":       { imap_host: "imap.mail.yahoo.com",   imap_port: "993", smtp_host: "smtp.mail.yahoo.com",   smtp_port: "587" },
  "imap.mail.me.com":          { imap_host: "imap.mail.me.com",      imap_port: "993", smtp_host: "smtp.mail.me.com",      smtp_port: "587" },
};

function getStatusLabels(tc: (key: string) => string): Record<string, { label: string; className: string }> {
  return {
    active: { label: tc('active'), className: "status-active" },
    inactive: { label: tc('inactive'), className: "status-inactive" },
    error: { label: tc('error'), className: "status-error" },
    expired: { label: tc('expired'), className: "status-expired" },
    rate_limited: { label: tc('limited'), className: "status-limited" },
  };
}

// Statuses that require reconnection
const RECONNECT_STATUSES = ["error", "expired"];

export function AccountManager({ onClose, onBack, onAccountChanged, initialReconnect }: AccountManagerProps) {
  const { t } = useTranslation('settings');
  const { t: tc } = useTranslation('common');
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [currentAccountId, setCurrentAccountId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [formData, setFormData] = useState<NewAccountForm>(INITIAL_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  // Id of the account whose DELETE is in flight. Backend cleanup can take
  // >20s; without this guard the row stays clickable and a second delete
  // races the first one (2026-06-09 "Failed to delete account" incident).
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [gmailAccountId, setGmailAccountId] = useState<string | null>(null);
  const [outlookAccountId, setOutlookAccountId] = useState<string | null>(null);
  const [reconnectingAccount, setReconnectingAccount] = useState<Account | null>(null);
  const [tokenStatuses, setTokenStatuses] = useState<Record<string, AccountTokenStatus>>({});
  const [avatarLoading, setAvatarLoading] = useState<string | null>(null);
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const avatarInputRef = useRef<HTMLInputElement>(null);
  const avatarTargetRef = useRef<string | null>(null);
  const initialReconnectKeyRef = useRef<string | null>(null);

  const api = getApiClient();
  const initialReconnectKey = `${initialReconnect?.provider ?? ''}:${initialReconnect?.email ?? ''}`;

  const handleAvatarClick = useCallback((accountId: string) => {
    setAvatarError(null);
    avatarTargetRef.current = accountId;
    avatarInputRef.current?.click();
  }, []);

  const handleAvatarFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    const accountId = avatarTargetRef.current;
    if (!file || !accountId) return;
    e.target.value = '';
    setAvatarLoading(accountId);
    setAvatarError(null);
    try {
      const url = await uploadAccountAvatar(accountId, file);
      setAccounts(prev => prev.map(a => a.id === accountId ? { ...a, avatar_url: url } : a));
    } catch (err) {
      setAvatarError(err instanceof Error ? err.message : t('account_avatar_upload_failed', 'Échec upload'));
    } finally {
      setAvatarLoading(null);
    }
  }, [t]);

  // Generate UUIDs for both providers when the add form opens
  useEffect(() => {
    if (showAddForm) {
      if (!gmailAccountId) setGmailAccountId(safeRandomUUID());
      if (!outlookAccountId) setOutlookAccountId(safeRandomUUID());
    } else {
      setGmailAccountId(null);
      setOutlookAccountId(null);
    }

  }, [showAddForm]);

  const loadAccounts = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await api.listAccounts();
      setAccounts(response.accounts);
      setCurrentAccountId(response.current_account_id);
      if (response.current_account_id) {
        setActiveAccountId(response.current_account_id);
      }

      // Fetch token statuses for OAuth accounts (Gmail/Outlook)
      const oauthAccounts = response.accounts.filter(
        (a) => a.provider === "gmail" || a.provider === "outlook"
      );
      const statuses: Record<string, AccountTokenStatus> = {};
      await Promise.all(
        oauthAccounts.map(async (account) => {
          try {
            const status = await api.getAccountTokenStatus(account.id);
            statuses[account.id] = status;
          } catch {
            // Ignore errors for individual account status fetches
          }
        })
      );
      setTokenStatuses(statuses);
    } catch (err) {
      const raw = err instanceof Error ? err.message : '';
      setError(raw === 'Failed to fetch' ? tc('status_disconnected_tooltip') : (raw || t('account_error_loading')));
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    loadAccounts();
  }, [loadAccounts]);

  useEffect(() => {
    if (!initialReconnect || loading || accounts.length === 0) return;
    if (initialReconnectKeyRef.current === initialReconnectKey) return;

    const targetEmail = initialReconnect.email?.trim().toLowerCase();
    const targetProvider = initialReconnect.provider?.trim().toLowerCase();
    const providerMatches = (account: Account) => !targetProvider || account.provider === targetProvider;
    const emailMatches = (account: Account) => !targetEmail || account.email.trim().toLowerCase() === targetEmail;
    const account =
      accounts.find((candidate) => providerMatches(candidate) && emailMatches(candidate)) ??
      accounts.find((candidate) => !!targetEmail && emailMatches(candidate)) ??
      accounts.find((candidate) => !!targetProvider && providerMatches(candidate));

    if (!account || (account.provider !== "gmail" && account.provider !== "outlook")) return;

    initialReconnectKeyRef.current = initialReconnectKey;
    setShowAddForm(false);
    setReconnectingAccount(account);
  }, [accounts, initialReconnect, initialReconnectKey, loading]);

  // Auto-show add form when no accounts configured
  useEffect(() => {
    if (!loading && accounts.length === 0) setShowAddForm(true);
  }, [loading, accounts.length]);

  // Escape key closes the modal — skip when typing in fields so inner popups
  // (autocompletes, calendar dropdowns) handle Escape themselves first.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const tgt = e.target as HTMLElement | null;
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable)) {
        return;
      }
      onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const handleActivate = async (accountId: string) => {
    // F05 (HIGH): snapshot prev state so we can roll back atomically if
    // any step after `api.activateAccount` (e.g. localStorage iteration,
    // setActiveAccountId triggering a hook crash, or the parent's
    // onAccountChanged callback) blows up. Pre-fix, a partial failure
    // left the AccountManager showing the new account as "current" while
    // the inbox below still rendered the previous account → inconsistent
    // state with no recovery path. Now: any throw rolls back AND surfaces
    // a toast so the user knows the switch failed.
    const prevCurrentId = currentAccountId;
    const prevAccounts = accounts;
    try {
      await api.activateAccount(accountId);
      setCurrentAccountId(accountId);
      // Invalider le cache des groupes de contacts de l'ancien compte
      try {
        Object.keys(localStorage)
          .filter(k => k.startsWith('agentys_contact_groups_'))
          .forEach(k => localStorage.removeItem(k));
      } catch { /* ignore */ }
      setActiveAccountId(accountId);
      // FIX UI-002 (audit P0): bust the module-level signature cache so the
      // next compose re-fetches with the new active account. Without this,
      // useAccountSignature short-circuits on the cached value and outgoing
      // emails leave with the previous account's signature attached
      // (identity leak across mailboxes).
      try {
        setAccountSignatureCache(null, null);
      } catch { /* defensive: hook may be unavailable in some test builds */ }
      setAccounts((prev) =>
        prev.map((a) => ({
          ...a,
          is_current: a.id === accountId,
        }))
      );
      onAccountChanged?.();
    } catch (err) {
      // Rollback both state slots so the UI stays consistent
      setCurrentAccountId(prevCurrentId);
      setAccounts(prevAccounts);
      // Restore the underlying active account id too (if it had been flipped)
      if (prevCurrentId) {
        try { setActiveAccountId(prevCurrentId); } catch { /* ignore */ }
      }
      const message = err instanceof Error ? err.message : t('account_error_activate');
      setError(message);
      // Global toast so the user actually sees the failure even if the
      // AccountManager modal is dismissed before the inline error renders.
      try {
        window.dispatchEvent(
          new CustomEvent('agentys:toast', {
            detail: {
              message: `${t('account_error_activate')}: ${message}`,
              type: 'error',
              duration: 6000,
            },
          }),
        );
      } catch { /* defensive */ }
    }
  };

  const handleDelete = async (accountId: string) => {
    if (deletingId) return;
    // Target the SPECIFIC mailbox. (Launch audit 2026-05-30 Tier-0: this used
    // to set 'reset' → confirmDelete called clearAllUserData() which deletes
    // EVERY account + wipes local data. A 2-mailbox user removing one mailbox
    // lost everything.)
    setDeleteConfirmId(accountId);
  };

  const confirmDelete = async () => {
    if (!deleteConfirmId || deletingId) return;
    const targetId = deleteConfirmId;
    setDeletingId(targetId);
    try {
      if (targetId === 'reset') {
        // Explicit full-reset path ("Réinitialiser Agentys") — deletes every
        // account + local data. Reachable only when invoked with 'reset'.
        await clearAllUserData();
        window.location.reload();
        return;
      }
      // Normal per-mailbox removal: account-scoped DELETE /api/accounts/<id>
      // (cascades emails backend-side). Other accounts and all local data are
      // preserved; the list refreshes in place.
      await api.deleteAccount(targetId);
      setDeleteConfirmId(null);
      await loadAccounts();
    } catch (err) {
      // 404 = the account is already gone (e.g. a duplicate request won the
      // race) — that IS the state the user asked for, so refresh silently.
      if (err instanceof ApiError && err.status === 404) {
        setDeleteConfirmId(null);
        await loadAccounts();
      } else {
        setError(err instanceof Error ? err.message : t('account_error_delete'));
        setDeleteConfirmId(null);
      }
    } finally {
      setDeletingId(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!formData.name.trim() || !formData.email.trim()) {
      setError(t('account_name_required'));
      return;
    }

    try {
      setSubmitting(true);
      setError(null);

      const request: CreateAccountRequest = {
        name: formData.name.trim(),
        email: formData.email.trim(),
        provider: formData.provider,
      };

      if (formData.signature.trim()) {
        request.signature = formData.signature.trim();
      }

      // IMAP/SMTP fields
      if (formData.provider === "imap_smtp") {
        request.imap_host = formData.imap_host || undefined;
        request.imap_port = formData.imap_port ? parseInt(formData.imap_port) : undefined;
        request.imap_user = formData.imap_user || undefined;
        request.imap_password = formData.imap_password || undefined;
        request.smtp_host = formData.smtp_host || undefined;
        request.smtp_port = formData.smtp_port ? parseInt(formData.smtp_port) : undefined;
        request.smtp_user = formData.smtp_user || undefined;
        request.smtp_password = formData.smtp_password || undefined;
      }

      const response = await api.createAccount(request);
      setAccounts((prev) => [...prev, response.account]);
      setFormData(INITIAL_FORM);
      setShowAddForm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('account_error_create'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleFormChange = (
    field: keyof NewAccountForm,
    value: string
  ) => {
    setFormData((prev) => {
      const next = { ...prev, [field]: value };
      // Auto-fill SMTP fields when picking an IMAP preset
      if (field === "imap_host" && IMAP_PRESETS[value]) {
        const preset = IMAP_PRESETS[value];
        next.imap_port = preset.imap_port;
        next.smtp_host = preset.smtp_host;
        next.smtp_port = preset.smtp_port;
      }
      return next;
    });
  };

  const getStatusInfo = (status: string) => {
    return getStatusLabels(tc)[status] || { label: status, className: "" };
  };

  // Handle successful Gmail OAuth connection

  const handleGmailConnected = useCallback(async (_email: string) => {
    // Refresh accounts list to show the newly connected Gmail account
    await loadAccounts();
    setShowAddForm(false);
    setFormData(INITIAL_FORM);
    setGmailAccountId(null);
  }, [loadAccounts]);

  // Handle Gmail OAuth error
  const handleGmailError = useCallback((errorMessage: string) => {
    setError(errorMessage);
  }, []);

  // Handle successful Outlook OAuth connection

  const handleOutlookConnected = useCallback(async (_email: string) => {
    // Refresh accounts list to show the newly connected Outlook account
    await loadAccounts();
    setShowAddForm(false);
    setFormData(INITIAL_FORM);
    setOutlookAccountId(null);
  }, [loadAccounts]);

  // Handle Outlook OAuth error
  const handleOutlookError = useCallback((errorMessage: string) => {
    setError(errorMessage);
  }, []);

  // Handle reconnection for accounts with error/expired status
  const handleReconnect = useCallback((account: Account) => {
    setReconnectingAccount(account);
  }, []);

  // Handle successful reconnection

  const handleReconnectSuccess = useCallback(async (_email: string) => {
    await loadAccounts();
    setReconnectingAccount(null);
  }, [loadAccounts]);

  // Handle reconnection error
  const handleReconnectError = useCallback((errorMessage: string) => {
    setError(errorMessage);
    setReconnectingAccount(null);
  }, []);

  // Cancel reconnection
  const handleCancelReconnect = useCallback(() => {
    setReconnectingAccount(null);
  }, []);

  const reconnectProviderLabel = reconnectingAccount
    ? PROVIDER_LABELS[reconnectingAccount.provider]
    : "";

  return (
    <div className="account-manager">
      <input
        ref={avatarInputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={handleAvatarFileChange}
      />
      {avatarError && (
        <div className="avatar-error-banner" onClick={() => setAvatarError(null)}>
          {avatarError}
        </div>
      )}
      <ConfirmationDialog
        isOpen={deleteConfirmId !== null}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteConfirmId(null)}
        title={t('account_delete')}
        message={t('account_delete_confirm')}
        confirmLabel={tc('delete')}
        destructive
      />
      <div className="account-manager-header">
        <div className="account-manager-header-left">
          {onBack && (
            <button
              className="account-manager-back"
              onClick={onBack}
              aria-label={tc('back')}
              title={tc('back')}
            >
              <ChevronLeftIcon size={20} />
            </button>
          )}
          <h2>{t('account_user')}</h2>
        </div>
        <button
          className="account-manager-close"
          onClick={onClose}
          aria-label={tc('close')}
        >
          <CloseIcon />
        </button>
      </div>

      {error && (
        <div id="account-form-error" className="account-manager-error" role="alert">
          <span>{error}</span>
          <button onClick={() => setError(null)} aria-label={tc('close_error')}>
            <CloseIcon size={16} />
          </button>
        </div>
      )}

      <div className="account-manager-content">
        {loading ? (
          <div className="account-manager-loading">{tc('loading')}</div>
        ) : (
          <>
            <div className="account-list">
              {accounts.length === 0 ? (
                !showAddForm && (
                  <div className="account-empty">
                    <span className="account-empty-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="4" />
                        <path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94" />
                      </svg>
                    </span>
                    <p className="account-empty-title">{t('account_no_accounts')}</p>
                    <p className="account-empty-hint">
                      {t('account_no_accounts_sub')}
                    </p>
                  </div>
                )
              ) : (
                accounts.map((account) => {
                  const statusInfo = getStatusInfo(account.status);
                  const tokenStatus = tokenStatuses[account.id];
                  return (
                    <div
                      key={account.id}
                      className={`account-item ${
                        account.id === currentAccountId ? "account-item-current" : ""
                      }`}
                    >
                      <div className="account-item-main">
                        <button
                          className="account-item-avatar-btn"
                          onClick={() => handleAvatarClick(account.id)}
                          title="Changer la photo"
                          disabled={avatarLoading === account.id}
                        >
                          <Avatar
                            name={account.name}
                            email={account.email}
                            size="md"
                            photoUrl={account.avatar_url ?? undefined}
                          />
                          <span className="account-avatar-edit-overlay">
                            {avatarLoading === account.id ? '…' : '✎'}
                          </span>
                        </button>
                        <div className="account-item-info">
                          <div className="account-item-name-row">
                            <span className="account-item-name">{account.name}</span>
                            <span className={`account-item-status ${statusInfo.className}`}>
                              {statusInfo.label}
                            </span>
                          </div>
                          <span className="account-item-email">{account.email}</span>
                          <div className="account-item-provider-row">
                            <span className="account-item-provider">
                              {PROVIDER_LABELS[account.provider]}
                            </span>
                            {tokenStatus && (
                              <div className="account-item-capabilities">
                                {tokenStatus.has_email && (
                                  <span className="capability-badge capability-email" title={t('account_email_connected')}>
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
                                    {t('account_badge_email')}
                                  </span>
                                )}
                                {tokenStatus.has_calendar && (
                                  <span className="capability-badge capability-calendar" title={t('account_calendar_connected')}>
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                                    {t('account_badge_calendar')}
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                        <button
                          className="account-btn-delete-icon icon-btn--delete"
                          onClick={() => handleDelete(account.id)}
                          disabled={deletingId !== null}
                          title={deletingId === account.id ? t('account_deleting', { defaultValue: 'Deleting…' }) : t('account_delete')}
                        >
                          {deletingId === account.id ? '…' : <TrashIcon size={14} />}
                        </button>
                      </div>

                      {/* Action buttons — only rendered when there are real actions */}
                      {((accounts.length > 1 && account.id !== currentAccountId) ||
                        (RECONNECT_STATUSES.includes(account.status) && (account.provider === "gmail" || account.provider === "outlook")) ||
                        (tokenStatus && !tokenStatus.has_calendar && !RECONNECT_STATUSES.includes(account.status) && (account.provider === "gmail" || account.provider === "outlook"))) && (
                        <div className="account-item-actions">
                          {accounts.length > 1 && account.id !== currentAccountId && (
                            <button
                              className="account-btn account-btn-activate"
                              onClick={() => handleActivate(account.id)}
                              title={t('account_use')}
                            >
                              {tc('activate')}
                            </button>
                          )}
                          {RECONNECT_STATUSES.includes(account.status) &&
                            (account.provider === "gmail" || account.provider === "outlook") && (
                            <button
                              className="account-btn account-btn-reconnect"
                              onClick={() => handleReconnect(account)}
                              title={t('account_reconnect')}
                            >
                              {tc('reconnect')}
                            </button>
                          )}
                          {(tokenStatus &&
                            !tokenStatus.has_calendar &&
                            !RECONNECT_STATUSES.includes(account.status) &&
                            (account.provider === "gmail" || account.provider === "outlook")) && (
                            <button
                              className="account-btn account-btn-reconnect"
                              onClick={() => handleReconnect(account)}
                              title={t('account_reconnect_calendar')}
                            >
                              {t('account_add_calendar')}
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            {showAddForm ? (
              <div className="account-form">
                {accounts.length > 0 && <h3>{t('account_new')}</h3>}

                {/* Hero — deux boutons OAuth côte à côte, comme l'onboarding */}
                {formData.provider !== "imap_smtp" && gmailAccountId && outlookAccountId && (
                  <>
                    {accounts.length === 0 && (
                      <div className="am-oauth-branding">
                        <div className="am-oauth-branding-logo">
                          <TriangleLogo />
                        </div>
                        <h2 className="am-oauth-branding-title">Agentys</h2>
                      </div>
                    )}
                    <div className="am-oauth-hero">
                      <ConnectGmailButton
                        accountId={gmailAccountId}
                        onConnected={handleGmailConnected}
                        onError={handleGmailError}
                      />
                      <ConnectOutlookButton
                        accountId={outlookAccountId}
                        onConnected={handleOutlookConnected}
                        onError={handleOutlookError}
                      />
                    </div>
                    {accounts.length > 0 && (
                      <button
                        type="button"
                        className="account-add-imap-link"
                        onClick={() => handleFormChange("provider", "imap_smtp")}
                      >
                        {t('account_imap')} →
                      </button>
                    )}
                  </>
                )}

                {formData.provider === "imap_smtp" && (
                  <form onSubmit={handleSubmit}>
                    <label className="account-form-field">
                      <span>{t('account_name_label')}</span>
                      <input
                        type="text"
                        value={formData.name}
                        onChange={(e) => handleFormChange("name", e.target.value)}
                        placeholder={t('account_name_placeholder')}
                        required
                        aria-describedby={error ? "account-form-error" : undefined}
                        aria-invalid={!!error}
                      />
                    </label>

                    <label className="account-form-field">
                      <span>{t('account_email_label')}</span>
                      <input
                        type="email"
                        value={formData.email}
                        onChange={(e) => handleFormChange("email", e.target.value)}
                        placeholder={t('account_email_placeholder')}
                        required
                        aria-describedby={error ? "account-form-error" : undefined}
                        aria-invalid={!!error}
                      />
                    </label>

                    {(formData.imap_host.includes('outlook') || formData.imap_host.includes('office365') || formData.imap_host.includes('hotmail')) && (
                      <div className="account-form-warning">
                        {t('imap_outlook_warning')}
                      </div>
                    )}

                    <div className="account-form-section-label">IMAP</div>

                    <div className="account-form-row">
                      <label className="account-form-field">
                        <span>{t('imap_host')}</span>
                        <input type="text" list="imap-presets" value={formData.imap_host} onChange={(e) => handleFormChange("imap_host", e.target.value)} placeholder="imap.gmail.com" required />
                        <datalist id="imap-presets">
                          <option value="imap.gmail.com">Gmail</option>
                          <option value="outlook.office365.com">Outlook</option>
                          <option value="imap.mail.yahoo.com">Yahoo</option>
                          <option value="imap.mail.me.com">iCloud</option>
                        </datalist>
                      </label>
                      <label className="account-form-field account-form-field-small">
                        <span>{t('imap_port')}</span>
                        <input type="number" value={formData.imap_port} onChange={(e) => handleFormChange("imap_port", e.target.value)} placeholder="993" required />
                      </label>
                    </div>

                    <label className="account-form-field">
                      <span>{t('imap_user')}</span>
                      <input type="text" value={formData.imap_user} onChange={(e) => handleFormChange("imap_user", e.target.value)} placeholder="user@example.com" required />
                    </label>

                    <label className="account-form-field">
                      <span>{t('imap_password')}</span>
                      <input type="password" value={formData.imap_password} onChange={(e) => handleFormChange("imap_password", e.target.value)} placeholder="••••••••" required />
                    </label>

                    <div className="account-form-section-label">SMTP</div>

                    <div className="account-form-row">
                      <label className="account-form-field">
                        <span>{t('smtp_host')}</span>
                        <input type="text" list="smtp-presets" value={formData.smtp_host} onChange={(e) => handleFormChange("smtp_host", e.target.value)} placeholder="smtp.gmail.com" required />
                        <datalist id="smtp-presets">
                          <option value="smtp.gmail.com">Gmail</option>
                          <option value="smtp.office365.com">Outlook</option>
                          <option value="smtp.mail.yahoo.com">Yahoo</option>
                          <option value="smtp.mail.me.com">iCloud</option>
                        </datalist>
                      </label>
                      <label className="account-form-field account-form-field-small">
                        <span>{t('smtp_port')}</span>
                        <input type="number" value={formData.smtp_port} onChange={(e) => handleFormChange("smtp_port", e.target.value)} placeholder="587" required />
                      </label>
                    </div>

                    <label className="account-form-field">
                      <span>{t('smtp_user')}</span>
                      <input type="text" value={formData.smtp_user} onChange={(e) => handleFormChange("smtp_user", e.target.value)} placeholder="user@example.com" required />
                    </label>

                    <label className="account-form-field">
                      <span>{t('smtp_password')}</span>
                      <input type="password" value={formData.smtp_password} onChange={(e) => handleFormChange("smtp_password", e.target.value)} placeholder="••••••••" required />
                    </label>

                    <label className="account-form-field">
                      <span>{t('account_signature_label')}</span>
                      <textarea
                        value={formData.signature}
                        onChange={(e) => handleFormChange("signature", e.target.value)}
                        placeholder={t('account_signature_placeholder')}
                        rows={3}
                      />
                    </label>

                    <div className="account-form-actions">
                      <button
                        type="button"
                        className="account-btn account-btn-cancel"
                        onClick={() => {
                          setShowAddForm(false);
                          setFormData(INITIAL_FORM);
                          setGmailAccountId(null);
                          setOutlookAccountId(null);
                        }}
                      >
                        {tc('cancel')}
                      </button>
                      <button
                        type="submit"
                        className="account-btn account-btn-submit"
                        disabled={submitting}
                      >
                        {submitting ? tc('creating') : tc('create')}
                      </button>
                    </div>
                  </form>
                )}

                {accounts.length > 0 && (formData.provider === "gmail" || formData.provider === "outlook") && (
                  <div className="account-form-actions">
                    <button
                      type="button"
                      className="account-btn account-btn-cancel"
                      onClick={() => {
                        setShowAddForm(false);
                        setFormData(INITIAL_FORM);
                        setGmailAccountId(null);
                        setOutlookAccountId(null);
                      }}
                    >
                      {tc('cancel')}
                    </button>
                  </div>
                )}
              </div>
            ) : (
              accounts.length === 0 && (
                <button
                  className="account-add-btn"
                  onClick={() => setShowAddForm(true)}
                >
                  {t('account_add')}
                </button>
              )
            )}
          </>
        )}
      </div>

      {/* Reconnection Modal */}
      {reconnectingAccount && (
        <div className="account-reconnect-overlay">
          <div className="account-reconnect-modal">
            <div className="account-reconnect-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
                <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
                <path d="M21 21v-5h-5" />
              </svg>
            </div>
            <h3>{t('reconnect_title', { email: reconnectingAccount.email })}</h3>
            <p className="account-reconnect-info">
              {t('reconnect_desc', { provider: reconnectProviderLabel })}
            </p>
            <ol className="account-reconnect-steps">
              <li>{t('reconnect_step_provider', { provider: reconnectProviderLabel })}</li>
              <li>{t('reconnect_step_permissions')}</li>
              <li>{t('reconnect_step_return')}</li>
            </ol>

            {reconnectingAccount.provider === "gmail" && (
              <ConnectGmailButton
                accountId={reconnectingAccount.id}
                onConnected={handleReconnectSuccess}
                onError={handleReconnectError}
                forceReconnect
              />
            )}

            {reconnectingAccount.provider === "outlook" && (
              <ConnectOutlookButton
                accountId={reconnectingAccount.id}
                onConnected={handleReconnectSuccess}
                onError={handleReconnectError}
                forceReconnect
              />
            )}

            <p className="account-reconnect-note">
              {t('reconnect_note')}
            </p>

            <div className="account-reconnect-actions">
              <button
                type="button"
                className="account-btn account-btn-cancel"
                onClick={handleCancelReconnect}
              >
                {tc('cancel')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
