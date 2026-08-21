/**
 * Configuration centralisée pour Agentys
 *
 * Utilise les variables d'environnement Vite (VITE_*)
 */

// URL de l'API backend
// En mode dev (Vite), on utilise une chaîne vide : les requêtes /api/* et /socket.io/*
// passent par le proxy Vite (vite.config.ts) → 127.0.0.1:5050, évitant le blocage CORS.
// En production (Tauri), pas de proxy — on cible directement 127.0.0.1:5050.
// Note : 127.0.0.1 évite la résolution IPv6 de "localhost" sur Windows (~2s de latence).
export const API_URL = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? '' : 'http://127.0.0.1:5050')

// True quand l'app tourne en cloud (Vercel) — désactive les options local-only (Claude Code CLI, Ollama)
export const IS_CLOUD = API_URL !== '' && !API_URL.includes('127.0.0.1') && !API_URL.includes('localhost')

// (2026-06-11) Log de démarrage retiré : le budget « <260 console statements »
// (tests/test_speed_optimizations.py) était atteint pile et bloquait la CI.
// L'API_URL effective se lit dans l'onglet Network au premier appel.
