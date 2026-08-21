import type { ReactNode } from "react";
import "./EmptyState.css";

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  subtitle?: string;
}

/** Inbox Zero — simple line-art illustration */
export const InboxZeroIcon = () => (
  <svg aria-hidden="true" width="56" height="56" viewBox="0 0 56 56" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="8" y="14" width="40" height="30" rx="4" />
    <polyline points="8,18 28,34 48,18" />
    <path d="M24 42 L28 46 L36 36" strokeWidth="2" />
  </svg>
);

/** Search / no results — magnifier with X */
export const NoResultsIcon = () => (
  <svg aria-hidden="true" width="56" height="56" viewBox="0 0 56 56" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="24" cy="24" r="14" />
    <line x1="34" y1="34" x2="48" y2="48" strokeWidth="2" />
    <line x1="19" y1="19" x2="29" y2="29" />
    <line x1="29" y1="19" x2="19" y2="29" />
  </svg>
);

/** Scheduled / later — clock face */
export const ScheduledIcon = () => (
  <svg aria-hidden="true" width="56" height="56" viewBox="0 0 56 56" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="28" cy="28" r="20" />
    <polyline points="28 16 28 28 36 33" />
  </svg>
);

/** Generic empty folder — open box */
export const EmptyFolderIcon = () => (
  <svg aria-hidden="true" width="56" height="56" viewBox="0 0 56 56" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 22 L28 10 L50 22 L28 34 Z" />
    <path d="M6 22 L6 38 L28 50 L50 38 L50 22" />
    <line x1="28" y1="34" x2="28" y2="50" />
  </svg>
);

export function EmptyState({ icon, title, subtitle }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <span className="empty-state-icon">{icon}</span>
      <h3 className="empty-state-title">{title}</h3>
      {subtitle && <p className="empty-state-subtitle">{subtitle}</p>}
    </div>
  );
}
