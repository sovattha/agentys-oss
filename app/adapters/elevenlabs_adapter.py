"""
Adapter HTTP pour l'API ElevenLabs (TTS + voice cloning).

Responsabilités :
- Lister les voix disponibles (premade + clonées)
- Synthétiser du texte en MP3
- Créer une voix clonée depuis des samples audio (Instant Voice Cloning)
- Supprimer une voix clonée

La clé API est lue depuis ELEVENLABS_API_KEY. L'adapter lève
ElevenLabsError sur toute réponse HTTP non-2xx, en préservant le code
de statut d'origine pour que la couche API puisse le remapper.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Iterable

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://api.elevenlabs.io/v1"
_DEFAULT_TIMEOUT = 60  # seconds — synthesis can be slow on long text


class ElevenLabsError(Exception):
    """Erreur renvoyée par l'API ElevenLabs."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Voice:
    voice_id: str
    name: str
    category: str  # "premade" | "cloned" | "generated" | "professional"
    preview_url: str | None
    labels: dict | None
    language: str | None


class ElevenLabsAdapter:
    """Client HTTP minimaliste pour ElevenLabs."""

    def __init__(self, api_key: str | None = None, timeout: int = _DEFAULT_TIMEOUT):
        self._api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        if not self._api_key:
            raise ElevenLabsError(
                "ELEVENLABS_API_KEY non configurée sur le serveur", status_code=500
            )
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"xi-api-key": self._api_key})

    def list_voices(self) -> list[Voice]:
        url = f"{_API_BASE}/voices"
        resp = self._request("GET", url)
        payload = resp.json()
        voices: list[Voice] = []
        for v in payload.get("voices", []):
            labels = v.get("labels") or {}
            voices.append(
                Voice(
                    voice_id=v["voice_id"],
                    name=v.get("name") or v["voice_id"],
                    category=v.get("category") or "premade",
                    preview_url=v.get("preview_url"),
                    labels=labels if labels else None,
                    language=labels.get("language"),
                )
            )
        return voices

    def synthesize(
        self,
        text: str,
        voice_id: str,
        model_id: str = "eleven_turbo_v2_5",
        output_format: str = "mp3_44100_128",
        language_code: str | None = None,
    ) -> bytes:
        if not text.strip():
            raise ElevenLabsError("texte vide", status_code=400)
        url = f"{_API_BASE}/text-to-speech/{voice_id}"
        params = {"output_format": output_format}
        body = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }
        # Pin explicite de la langue (ISO 639-1 : fr/en/de/es/...). Sans ce
        # paramètre, l'auto-détection d'ElevenLabs peut basculer vers la
        # mauvaise langue sur des phrases courtes ou mixtes (chiffres +
        # mots), entraînant une prononciation hybride incompréhensible.
        if language_code:
            body["language_code"] = language_code
        resp = self._request(
            "POST",
            url,
            params=params,
            json=body,
            extra_headers={"Accept": "audio/mpeg", "Content-Type": "application/json"},
        )
        if not resp.content or len(resp.content) < 200:
            raise ElevenLabsError(
                f"réponse MP3 trop courte ({len(resp.content)} bytes)", status_code=502
            )
        return resp.content

    def clone_voice(
        self,
        name: str,
        files: Iterable[tuple[str, bytes, str]],
        description: str | None = None,
    ) -> str:
        """
        Crée une voix via Instant Voice Cloning.

        files: itérable de tuples (filename, bytes, mime_type).
        Retourne le voice_id.
        """
        if not name.strip():
            raise ElevenLabsError("nom de voix requis", status_code=400)
        url = f"{_API_BASE}/voices/add"
        form: list[tuple[str, tuple]] = []
        data: dict = {"name": name.strip()}
        if description:
            data["description"] = description
        for filename, blob, mime in files:
            form.append(("files", (filename, blob, mime)))
        if not form:
            raise ElevenLabsError("au moins un échantillon audio requis", status_code=400)
        resp = self._request(
            "POST",
            url,
            data=data,
            files=form,
            timeout=120,  # cloning can be slower than synth
        )
        payload = resp.json()
        voice_id = payload.get("voice_id")
        if not voice_id:
            raise ElevenLabsError("réponse ElevenLabs sans voice_id", status_code=502)
        return voice_id

    def delete_voice(self, voice_id: str) -> None:
        url = f"{_API_BASE}/voices/{voice_id}"
        self._request("DELETE", url)

    # ─────────────────────────────────────────────────────────────────────
    # Internal HTTP with 1 retry on 5xx / 429
    # ─────────────────────────────────────────────────────────────────────
    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        data: dict | None = None,
        files: list | None = None,
        extra_headers: dict | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        headers = dict(extra_headers or {})
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = self._session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    data=data,
                    files=files,
                    headers=headers or None,
                    timeout=timeout or self._timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise ElevenLabsError(f"ElevenLabs réseau indisponible: {exc}", status_code=502)

            if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 1.0
                time.sleep(min(delay, 3.0))
                continue

            if not resp.ok:
                raise ElevenLabsError(
                    self._format_error(resp), status_code=self._map_status(resp.status_code)
                )
            return resp

        # Unreachable but keeps type-checkers happy
        raise ElevenLabsError(
            f"ElevenLabs indisponible: {last_exc}", status_code=502
        )  # pragma: no cover

    @staticmethod
    def _format_error(resp: requests.Response) -> str:
        try:
            payload = resp.json()
            detail = payload.get("detail") or payload
            if isinstance(detail, dict):
                msg = detail.get("message") or detail.get("status") or str(detail)
            else:
                msg = str(detail)
        except ValueError:
            msg = (resp.text or "").strip()[:200] or f"HTTP {resp.status_code}"
        return f"ElevenLabs {resp.status_code}: {msg}"

    @staticmethod
    def _map_status(status: int) -> int:
        """Mappe un code ElevenLabs vers un code cohérent pour notre API."""
        if status in (400, 401, 403, 404, 422):
            # 400/422 = payload invalide côté app (text trop long, voix inconnue)
            # 401/403 = clé API serveur invalide → 502 (notre problème, pas client)
            # 404 = voice_id inconnu → 404 passthrough
            if status == 404:
                return 404
            if status in (401, 403):
                return 502
            return 400
        if status == 429:
            return 429
        return 502
