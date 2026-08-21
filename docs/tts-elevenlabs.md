# TTS ElevenLabs (mobile)

L'app mobile utilise ElevenLabs pour tout le TTS (remplace `expo-speech`). Proxy backend à `/api/tts/*`, cache MP3 sur disque (SHA256 key), voice cloning via Instant Voice Cloning.

## Composants

- **Backend** : `app/api/tts.py` + `app/adapters/elevenlabs_adapter.py` + `app/infrastructure/tts_cache.py`
- **Mobile** : `src/services/tts.ts`, `src/hooks/useTts.ts`, composants `VoicePicker` + `VoiceCloneModal`
- **Endpoints** : `GET /voices`, `POST /speak` → `{audio_url, cached, chars}`, `GET /audio/<hash>.mp3` (auth), `POST /clone` (multipart), `DELETE /voices/<id>`
- **Modèle défaut** : `eleven_turbo_v2_5` (multilingue, ~50 % du coût de `eleven_multilingual_v2`)
- **Cache** : `AGENTYS_DATA_DIR/tts_cache/<hash>.mp3` + SQLite `tts_cache.db`, LRU éviction à 500 MB
- **Limite texte** : 2 500 chars (troncature douce sur ponctuation + "(…)")
- **Tests** : `pytest tests/api/test_tts.py` (18 tests, ElevenLabs stubbé)

## Env vars Railway

- `ELEVENLABS_API_KEY` (obligatoire — sinon tous les endpoints `/api/tts/*` renvoient 500)

## Rotation de clé

Dashboard ElevenLabs → Profile → API Key → regenerate, puis `railway variables --set ELEVENLABS_API_KEY=<new_key>`. Aucune migration nécessaire (le cache MP3 reste valide, les voice_id côté user ne dépendent pas de la clé).

## Config côté mobile

Les 4 clés SecureStore (`voice_id`, `voice_rate`, `voice_auto_advance`, `voice_auto_advance_delay`) sont conservées. Voix par défaut auto-sélectionnée au premier chargement (1ère clonée si dispo, sinon 1ère premade).

## Voice cloning

Instant Voice Cloning, min 10 s d'audio (recommandé 30 s+). Samples uploadés via multipart vers `/api/tts/clone` → ElevenLabs `/v1/voices/add`. Les voix sont globales au compte ElevenLabs (pas de scope multi-user dans notre DB).
