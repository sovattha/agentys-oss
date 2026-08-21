/**
 * Toast manager — émetteur d'événements singleton consommé par <ToastHost />.
 *
 * Usage :
 *   import { toast } from "../lib/toast";
 *   toast.error("Whisper indisponible");
 *   toast.warning("Backend lent");
 *   toast.info("Brouillon prêt");
 *
 * <ToastHost /> doit être monté UNE fois à la racine de l'app (app/_layout.tsx).
 */

export type ToastKind = "error" | "warning" | "info" | "success";

export interface ToastMessage {
  id: number;
  kind: ToastKind;
  text: string;
  /** Durée d'affichage en ms (défaut 3500ms). 0 = sticky (à dismisser manuellement). */
  duration?: number;
}

type Listener = (msg: ToastMessage) => void;

/** Fenêtre de throttle : un même (kind+text) ne se ré-affiche pas avant ce
 *  délai après son dernier affichage. Évite le spam quand le backend flappy
 *  produit la même erreur en boucle. */
const THROTTLE_WINDOW_MS = 5000;

class ToastManager {
  private listeners = new Set<Listener>();
  private nextId = 1;
  /** Timestamps du dernier emit par signature `${kind}::${text}`. */
  private lastEmitAt = new Map<string, number>();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(kind: ToastKind, text: string, duration?: number) {
    // Throttle : si un toast identique est apparu < 5s, on skip.
    const sig = `${kind}::${text}`;
    const now = Date.now();
    const prev = this.lastEmitAt.get(sig);
    if (prev !== undefined && now - prev < THROTTLE_WINDOW_MS) {
      return;
    }
    this.lastEmitAt.set(sig, now);
    // GC opportuniste : retire les entrées expirées pour éviter une croissance
    // monotone du Map sur une session longue.
    if (this.lastEmitAt.size > 50) {
      for (const [k, ts] of this.lastEmitAt) {
        if (now - ts > THROTTLE_WINDOW_MS * 4) this.lastEmitAt.delete(k);
      }
    }
    const msg: ToastMessage = { id: this.nextId++, kind, text, duration };
    this.listeners.forEach((l) => {
      try {
        l(msg);
      } catch {
        // Listener errors don't break other listeners.
      }
    });
  }

  error(text: string, duration?: number): void {
    this.emit("error", text, duration);
  }

  warning(text: string, duration?: number): void {
    this.emit("warning", text, duration);
  }

  info(text: string, duration?: number): void {
    this.emit("info", text, duration);
  }

  success(text: string, duration?: number): void {
    this.emit("success", text, duration);
  }
}

export const toast = new ToastManager();
