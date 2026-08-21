#!/usr/bin/env python3
"""
Génère les earcons (signaux audio non-verbaux) du mode conduite.

Earcons = le canal de "protocole" qui REMPLACE les questions parlées
("J'envoie ?", "Tu veux l'écouter ?"). Voir docs/voice-first-redesign.md.

Quatre clips ~40-260ms, 16-bit PCM mono 44.1kHz, fade 5ms (anti-clic) :
  - turn.wav   : 2 notes ascendantes  -> "à toi (j'écoute)"
  - tick.wav   : blip court            -> "c'est noté (je capture)"
  - done.wav   : accord majeur          -> "fait / envoyé"
  - alert.wav  : 2 notes descendantes graves -> "erreur / destructif"

Déterministe et sans dépendance (stdlib `wave`/`struct`/`math`). Re-runner
si on veut ré-accorder les tons : `python scripts/gen-earcons.py`.
"""

import math
import os
import struct
import wave

SR = 44100          # sample rate
AMP = 0.42          # amplitude crête (gentle, pas agressant en voiture)
FADE_MS = 5.0       # fondu d'entrée/sortie anti-clic

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "earcons")


def _envelope(n_samples: int) -> list:
    """Fondu linéaire d'entrée/sortie sur FADE_MS pour éviter les clics."""
    fade = max(1, int(SR * FADE_MS / 1000.0))
    env = [1.0] * n_samples
    for i in range(min(fade, n_samples)):
        g = i / fade
        env[i] = g
        env[n_samples - 1 - i] = min(env[n_samples - 1 - i], g)
    return env


def _tone(freqs, dur_ms: float, amp: float = AMP) -> list:
    """Somme de sinusoïdes (accord) sur dur_ms, normalisée + enveloppée."""
    n = int(SR * dur_ms / 1000.0)
    env = _envelope(n)
    out = []
    k = amp / max(1, len(freqs))
    for i in range(n):
        t = i / SR
        s = sum(math.sin(2 * math.pi * f * t) for f in freqs)
        out.append(s * k * env[i])
    return out


def _seq(segments) -> list:
    """Concatène des segments [(freqs, dur_ms), ...]."""
    buf = []
    for freqs, dur in segments:
        buf.extend(_tone(freqs if isinstance(freqs, (list, tuple)) else [freqs], dur))
    return buf


def _write(name: str, samples: list) -> None:
    path = os.path.join(OUT_DIR, name)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)      # 16-bit
        w.setframerate(SR)
        frames = bytearray()
        for s in samples:
            v = int(max(-1.0, min(1.0, s)) * 32767)
            frames += struct.pack("<h", v)
        w.writeframesraw(bytes(frames))
    print(f"  wrote {name}  ({len(samples)/SR*1000:.0f}ms, {len(samples)} samples)")


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"earcons -> {os.path.abspath(OUT_DIR)}")

    # ── Famille "classic" (défaut historique — noms sans suffixe) ──────────
    # "à toi" : A5 -> C#6, montée brève et claire.
    _write("turn.wav", _seq([(880.0, 90), (1108.73, 110)]))
    # "noté" : blip court 1200Hz.
    _write("tick.wav", _seq([(1200.0, 45)]))
    # "fait/envoyé" : accord C major (C5-E5-G5), résolution positive.
    _write("done.wav", _seq([([523.25, 659.25, 783.99], 240)]))
    # "erreur/destructif" : E4 -> B3, descente grave, sérieuse mais douce.
    _write("alert.wav", _seq([(329.63, 95), (246.94, 150)]))

    # ── Famille "soft" (réglage « Doux » — plus grave, plus lent) ─────────
    # Même vocabulaire, une quinte plus bas et durées allongées : moins
    # intrusif pour les longues sessions / oreilles sensibles.
    _write("turn_soft.wav", _seq([(659.25, 120), (783.99, 140)]))
    _write("tick_soft.wav", _seq([(900.0, 55)]))
    _write("done_soft.wav", _seq([([440.0, 554.37, 659.25], 280)]))
    _write("alert_soft.wav", _seq([(261.63, 110), (196.0, 170)]))

    # ── Famille "crisp" (réglage « Vif » — plus aigu, plus court) ─────────
    # Coupe mieux le bruit de route / volume faible : attaque nette.
    _write("turn_crisp.wav", _seq([(1046.5, 60), (1318.51, 80)]))
    _write("tick_crisp.wav", _seq([(1600.0, 35)]))
    _write("done_crisp.wav", _seq([([1046.5, 1318.51, 1567.98], 180)]))
    _write("alert_crisp.wav", _seq([(392.0, 80), (293.66, 120)]))

    print("done.")


if __name__ == "__main__":
    main()
