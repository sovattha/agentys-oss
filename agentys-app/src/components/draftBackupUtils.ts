/**
 * Utility for clearing localStorage draft backups.
 * Lives in its own file so DraftEditor.tsx only exports React components,
 * keeping Vite Fast Refresh working correctly.
 */
export function clearDraftBackup(draftId: string): void {
  try {
    localStorage.removeItem(`draft-backup-${draftId}`);
  } catch {
    // Ignore errors
  }
}
