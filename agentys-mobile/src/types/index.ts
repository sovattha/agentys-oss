/**
 * Types partagés pour l'app mobile Agentys.
 */

export interface SpeakableEmail {
  id: string;
  subject: string;
  sender_name: string;
  speakable_text: string;
}

export interface VoiceDraftResponse {
  draft_id: string;
  email_id: string;
  content: string;
  status: string;
}

export interface Draft {
  id: string;
  email_id: string;
  email_sender: string;
  email_sender_name?: string;
  email_subject: string;
  draft_subject: string;
  draft_body: string;
  status: string;
  created_at: string;
}

export interface EmailLabel {
  name: string;
  color: string;
  confidence?: number;
}

export interface Email {
  id: string;
  sender: string;
  sender_name?: string;
  subject: string;
  body?: string;
  received_at: string;
  classification?: "Action" | "FYI" | "Noise" | null;
  priority?: number;
  labels?: EmailLabel[];
}

/** Resolve effective classification: pending draft > persistent label */
export function getEmailClassification(email: Email): "Action" | "FYI" | "Noise" | null {
  if (email.classification) return email.classification;
  if (email.labels) {
    for (const lbl of email.labels) {
      if (lbl.name === "Action") return "Action";
      if (lbl.name === "FYI") return "FYI";
      if (lbl.name === "Noise") return "Noise";
    }
  }
  return null;
}

export type DriveState =
  | "idle"
  | "loading"
  | "speaking"
  | "choosing"
  | "listening"
  | "confirming_dictation"
  | "processing"
  | "generating"
  | "asking_preview"
  | "asking_send"
  | "reviewing"
  | "undo_window"
  | "paused"
  | "completed"
  | "error"
;

export type SessionMode = "actions" | "infos" | "mixed";

export interface SessionStats {
  started: number;
  totalEmails: number;
  replied: number;
  approved: number;
  skipped: number;
  archived: number;
  deleted: number;
}

export type ReplyMode = "reply" | "reply_all" | "forward";

// ─── TTS (ElevenLabs) ────────────────────────────────────────────────────
export interface TtsVoice {
  voice_id: string;
  name: string;
  category: "premade" | "cloned" | "generated" | "professional";
  preview_url: string | null;
  labels: Record<string, string> | null;
  language: string | null;
}

export interface TtsSpeakResponse {
  audio_url: string;  // chemin relatif: /api/tts/audio/<hash>.mp3
  cached: boolean;
  chars: number;
}
