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

/**
 * chatEngine.ts — Rule-based chatbot engine (zero LLM, zero cost)
 *
 * Philosophy: SOLVE the problem first. "Contact support" = last resort only.
 * Pattern matching with normalized text + keyword scoring.
 *
 * i18n contract (since 2026-05-22):
 *  - `response.text` is an i18n KEY (namespace `support`), resolved by the
 *    component via `t()` at message-creation time. Never raw prose here.
 *  - chip `label` is an i18n KEY too. The renderer does `t(label, label)` so
 *    keys resolve and any stray literal still passes through.
 *  - `input:` action payloads stay in French. They are NOT user-facing — they
 *    re-enter `getResponse()` which `normalize()`s them, and every rule carries
 *    French keywords, so the FR payload always re-matches regardless of locale.
 *  - `keywords`/`patterns` are matching tokens (fr/es/en, de-accented), not
 *    user-facing strings.
 */

export interface QuickAction {
  /** i18n key (resolved by the renderer) OR a literal that passes through. */
  label: string
  /** 'input:xxx' = simulate user msg, 'form:xxx' = open form, 'escalate:xxx' = inline email escalation, 'help-article:xxx' = article, 'navigate:help' = FAQ, 'close' = close */
  action: string
  /** Optional SVG icon id for chip micro-icons: drafts, style, speed, problem, idea, search, help, close */
  icon?: string
  /** Optional subtitle for welcome grid cards */
  subtitle?: string
}

export interface ChatResponse {
  /** i18n key resolved by the component (empty string = no bubble). */
  text: string
  quickActions?: QuickAction[]
}

interface Rule {
  id: string
  keywords: string[]
  patterns?: RegExp[]
  response: ChatResponse
  priority?: number
}

/** Remove accents for fuzzy matching (FR/ES diacritics → ASCII) */
function normalize(s: string): string {
  return s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

const RULES: Rule[] = [
  // ═══════════════════════════════════════════════════════════════════
  // GREETINGS
  // ═══════════════════════════════════════════════════════════════════
  {
    id: 'greeting',
    keywords: ['bonjour', 'salut', 'hello', 'hey', 'coucou', 'bonsoir', 'hola', 'buenas', 'hi'],
    patterns: [/^(bonjour|salut|hello|hey|coucou|bonsoir|hola|buenas|hi)\b/],
    priority: 5,
    response: {
      text: 'r_greeting',
      quickActions: [
        { label: 'c_where_drafts', action: 'input:où sont mes brouillons ia' },
        { label: 'c_improve_style', action: 'input:comment améliorer le style de l\'ia' },
        { label: 'c_process_faster', action: 'input:comment traiter mes emails plus vite' },
        { label: 'c_something_broken', action: 'input:quelque chose ne marche pas' },
      ],
    },
  },

  {
    id: 'thanks',
    keywords: ['merci', 'thank', 'genial', 'parfait', 'super', 'top', 'ca marche', 'gracias', 'perfecto'],
    patterns: [/\bmerci\b/, /\bthank/, /ca\s+(a\s+)?marche/, /\bgracias\b/],
    priority: 4,
    response: {
      text: 'r_thanks',
      quickActions: [
        { label: 'c_another_question', action: 'input:j\'ai une autre question' },
        { label: 'close', action: 'close' },
      ],
    },
  },

  // ═══════════════════════════════════════════════════════════════════
  // TROUBLESHOOTING — Problèmes courants (solutions directes)
  // ═══════════════════════════════════════════════════════════════════
  {
    id: 'emails-not-loading',
    keywords: ['charge', 'charger', 'affiche', 'vide', 'rien', 'emails', 'inbox', 'boite', 'load', 'loading', 'empty', 'carga', 'cargar', 'vacio', 'bandeja'],
    patterns: [/email.*(charge|affiche|vide|rien|load)/, /(charge|affiche|vide|rien).*email/, /boite.*vide/, /rien\s+ne\s+s.affiche/, /pas\s+d.email/, /no\s+(email|correo).*carga/, /bandeja.*vacia/, /email.*(won.t|not).*load/],
    priority: 5,
    response: {
      text: 'r_emails_not_loading',
      quickActions: [
        { label: 'c_connect_account', action: 'input:comment connecter mon compte' },
        { label: 'c_still_stuck', action: 'input:ça ne marche toujours pas' },
      ],
    },
  },

  {
    id: 'drafts-not-generating',
    keywords: ['brouillon', 'genere', 'generer', 'pas de brouillon', 'draft', 'borrador', 'genera', 'generar'],
    patterns: [/brouillon.*(genere|apparai|marche|fonctionne)/, /pas\s+de\s+brouillon/, /aucun\s+brouillon/, /draft.*(not|pas|aucun)/, /borrador.*(no|genera)/, /no\s+(hay|veo).*borrador/],
    priority: 5,
    response: {
      text: 'r_drafts_not_generating',
      quickActions: [
        { label: 'c_where_drafts', action: 'input:où sont mes brouillons ia' },
        { label: 'c_followups', action: 'input:relances et suivis' },
        { label: 'c_still_stuck', action: 'input:ça ne marche toujours pas' },
      ],
    },
  },

  {
    id: 'app-slow',
    keywords: ['lent', 'lenteur', 'rame', 'freeze', 'fige', 'long', 'bloque', 'attente', 'slow', 'frozen', 'lento', 'congelado', 'colgado'],
    patterns: [/lent/, /trop\s+long/, /rame/, /freeze/, /fig(e|ee)/, /bloqu/, /\bslow\b/, /frozen/, /\blento\b/, /se\s+(cuelga|congela)/],
    priority: 4,
    response: {
      text: 'r_app_slow',
      quickActions: [
        { label: 'c_still_stuck', action: 'input:ça ne marche toujours pas' },
      ],
    },
  },

  {
    id: 'send-failed',
    keywords: ['envoyer', 'envoi', 'echoue', 'echec', 'pas envoye', 'erreur envoi', 'send fail', 'enviar', 'envio', 'fallo envio'],
    patterns: [/envoi.*(echou|erreur|marche|fonctionne)/, /pas\s+(pu\s+)?envoye/, /echec.*envoi/, /(send|sending)\s+(fail|error)/, /(no\s+puedo|fallo).*envi/, /error.*envi/],
    priority: 5,
    response: {
      text: 'r_send_failed',
      quickActions: [
        { label: 'c_connect_account', action: 'input:comment connecter mon compte' },
        { label: 'c_still_stuck', action: 'input:ça ne marche toujours pas' },
      ],
    },
  },

  {
    id: 'still-stuck',
    keywords: ['toujours', 'encore', 'marche toujours pas', 'fonctionne toujours pas', 'aide', 'still', 'sigue', 'todavia'],
    patterns: [/toujours\s+(pas|bloque|pareil)/, /marche\s+toujours\s+pas/, /fonctionne\s+toujours\s+pas/, /ca\s+ne\s+marche/, /still\s+(not|doesn)/, /sigue\s+(sin|igual)/],
    priority: 6,
    response: {
      text: 'r_still_stuck',
      quickActions: [
        { label: 'c_send_to_support', action: 'escalate:support' },
        { label: 'c_report_bug', action: 'form:bug' },
      ],
    },
  },

  // ═══════════════════════════════════════════════════════════════════
  // CORE USER JOURNEYS — What real users actually ask
  // ═══════════════════════════════════════════════════════════════════
  {
    id: 'where-are-drafts',
    keywords: ['ou', 'sont', 'brouillon', 'trouver', 'voir', 'draft', 'reponse ia', 'borrador', 'donde', 'where'],
    patterns: [/ou\s+(sont|trouver|voir).*brouillon/, /ou\s+sont.*draft/, /brouillon.*ou/, /reponse\s+ia/, /where.*draft/, /donde.*borrador/],
    priority: 5,
    response: {
      text: 'r_where_drafts',
      quickActions: [
        { label: 'c_send_draft', action: 'input:comment envoyer un brouillon' },
        { label: 'c_edit_draft', action: 'input:comment modifier un brouillon' },
        { label: 'c_followups', action: 'input:relances et suivis' },
      ],
    },
  },

  {
    id: 'send-draft',
    keywords: ['envoyer', 'valider', 'brouillon', 'confirmer', 'expedier', 'send draft', 'enviar borrador'],
    patterns: [/comment\s+(envoyer|valider).*brouillon/, /envoyer\s+(un\s+)?brouillon/, /valider\s+(un\s+)?brouillon/, /send\s+(a\s+)?draft/, /enviar\s+(un\s+)?borrador/],
    priority: 4,
    response: {
      text: 'r_send_draft',
      quickActions: [
        { label: 'c_edit_before_send', action: 'input:comment modifier un brouillon' },
      ],
    },
  },

  {
    id: 'edit-draft',
    keywords: ['modifier', 'editer', 'changer', 'brouillon', 'texte', 'contenu', 'edit draft', 'editar borrador'],
    patterns: [/modifi(er|cation)\s+(un\s+|le\s+|mon\s+)?brouillon/, /edit(er)?\s+(un\s+)?brouillon/, /changer\s+(le\s+)?texte/, /edit\s+(a\s+)?draft/, /editar\s+(el\s+)?borrador/],
    priority: 4,
    response: {
      text: 'r_edit_draft',
      quickActions: [
        { label: 'art_refine_mode_title', action: 'help-article:refine-mode' },
        { label: 'c_improve_style', action: 'input:comment améliorer le style de l\'ia' },
      ],
    },
  },

  {
    id: 'improve-style',
    keywords: ['style', 'ton', 'ameliorer', 'ia', 'personnaliser', 'ressemble', 'naturel', 'formel', 'informel', 'tone', 'estilo', 'mejorar', 'personalizar'],
    patterns: [/ameliorer.*style/, /style.*ia/, /personnaliser.*ton/, /ne\s+me\s+ressemble/, /trop\s+(formel|informel|froid|generique)/, /pas\s+mon\s+style/, /improve.*(style|tone)/, /mejorar.*estilo/],
    priority: 5,
    response: {
      text: 'r_improve_style',
      quickActions: [
        { label: 'art_settings_overview_title', action: 'help-article:settings-overview' },
        { label: 'art_refine_mode_title', action: 'help-article:refine-mode' },
      ],
    },
  },

  {
    id: 'process-faster',
    keywords: ['rapide', 'vite', 'traiter', 'productivite', 'efficace', 'serie', 'temps', 'masse', 'faster', 'productivity', 'rapido', 'productividad', 'eficaz'],
    patterns: [/traiter.*(rapide|vite|plus vite)/, /(rapide|vite|efficace).*email/, /gagner\s+du\s+temps/, /trop\s+d.email/, /email.*masse/, /process.*fast/, /procesar.*rapid/],
    priority: 5,
    response: {
      text: 'r_process_faster',
      quickActions: [
        { label: 'c_shortcuts', action: 'input:quels sont les raccourcis' },
        { label: 'c_quicksteps', action: 'input:utiliser les actions rapides' },
      ],
    },
  },

  {
    id: 'something-broken',
    keywords: ['quelque chose', 'marche', 'fonctionne', 'probleme', 'souci', 'bizarre', 'problem', 'broken', 'problema', 'algo', 'fallo'],
    patterns: [/quelque\s+chose\s+ne\s+marche/, /quelque\s+chose.*marche\s+pas/, /ne\s+(marche|fonctionne)\s+(pas|plus)/, /probleme/, /souci/, /bizarre/, /(something|nothing)\s+(work|broke)/, /algo\s+(no\s+)?(funciona|va)/],
    priority: 3,
    response: {
      text: 'r_something_broken',
      quickActions: [
        { label: 'c_emails_not_loading', action: 'input:mes emails ne chargent pas' },
        { label: 'c_drafts_missing', action: 'input:les brouillons ne se génèrent pas' },
        { label: 'c_cannot_send', action: 'input:je ne peux pas envoyer d\'email' },
        { label: 'c_app_slow', action: 'input:l\'application est lente' },
      ],
    },
  },

  {
    id: 'how-to-general',
    keywords: ['comment', 'utiliser', 'fonctionner', 'marche', 'agentys', 'decouvrir', 'commencer', 'how', 'use', 'start', 'como', 'usar', 'empezar', 'funciona'],
    patterns: [/comment\s+(utiliser|fonctionne|marche|ca\s+marche)/, /commencer/, /decouvrir/, /c.est\s+quoi/, /how\s+(do|does|to)/, /como\s+(funciona|usar|empez)/],
    priority: 3,
    response: {
      text: 'r_how_to_general',
      quickActions: [
        { label: 'c_where_drafts', action: 'input:où sont mes brouillons ia' },
        { label: 'c_connect_account', action: 'input:comment connecter mon compte' },
        { label: 'c_process_faster', action: 'input:comment traiter mes emails plus vite' },
      ],
    },
  },

  {
    id: 'connect-account',
    keywords: ['connecter', 'connexion', 'compte', 'gmail', 'outlook', 'imap', 'ajouter', 'configurer', 'oauth', 'connect', 'account', 'conectar', 'cuenta', 'agregar'],
    patterns: [/connect(er|ion)?/, /ajout(er)?\s+(un\s+)?compte/, /configur/, /gmail/, /outlook/, /imap/, /add\s+(an?\s+)?account/, /conectar\s+(una\s+)?cuenta/],
    priority: 3,
    response: {
      text: 'r_connect_account',
      quickActions: [
        { label: 'art_connect_account_title', action: 'help-article:connect-account' },
        { label: 'c_connection_problem', action: 'input:je n\'arrive pas à connecter mon compte' },
      ],
    },
  },

  {
    id: 'connection-problem',
    keywords: ['arrive pas', 'connecter', 'connexion echoue', 'mot de passe', 'oauth', 'token', 'expire', 'password', 'contrasena', 'no puedo conectar'],
    patterns: [/(arrive|peux|parvien)\s+pas\s+(a\s+)?(me\s+)?connect/, /connexion\s+(echou|refus)/, /token.*expir/, /mot\s+de\s+passe/, /can.?t\s+connect/, /no\s+puedo\s+conectar/, /contrasena/],
    priority: 5,
    response: {
      text: 'r_connection_problem',
      quickActions: [
        { label: 'art_connect_account_title', action: 'help-article:connect-account' },
        { label: 'c_still_stuck', action: 'input:ça ne marche toujours pas' },
      ],
    },
  },

  {
    id: 'drafts-howto',
    keywords: ['brouillon', 'draft', 'reponse', 'ia', 'automatique', 'pipeline', 'borrador', 'respuesta'],
    patterns: [/brouillon/, /draft/, /reponse\s+(auto|ia|genere)/, /pipeline/, /borrador/],
    priority: 2,
    response: {
      text: 'r_drafts_howto',
      quickActions: [
        { label: 'art_draft_pipeline_title', action: 'help-article:draft-pipeline' },
        { label: 'art_refine_mode_title', action: 'help-article:refine-mode' },
        { label: 'art_smart_suggestions_title', action: 'help-article:smart-suggestions' },
      ],
    },
  },

  {
    id: 'shortcuts',
    keywords: ['raccourci', 'clavier', 'shortcut', 'touche', 'combinaison', 'hotkey', 'keyboard', 'atajo', 'tecla'],
    patterns: [/raccourci/, /shortcut/, /touche/, /keyboard/, /\batajo/, /hotkey/],
    priority: 3,
    response: {
      text: 'r_shortcuts',
      quickActions: [
        { label: 'art_shortcuts_nav_title', action: 'help-article:shortcuts-nav' },
        { label: 'art_shortcuts_actions_title', action: 'help-article:shortcuts-actions' },
        { label: 'c_quicksteps', action: 'input:utiliser les actions rapides' },
      ],
    },
  },

  {
    id: 'refine',
    keywords: ['refine', 'modifier', 'ameliorer', 'corriger', 'reformuler', 'instruction', 'ton', 'formel', 'affiner', 'reformular', 'rewrite'],
    patterns: [/refine/, /affiner/, /modifi(er|cation)\s+(un\s+)?brouillon/, /amelior/, /corrig/, /reformul/, /rendre\s+(plus\s+)?formel/, /rewrite/],
    priority: 3,
    response: {
      text: 'r_refine',
      quickActions: [
        { label: 'art_refine_mode_title', action: 'help-article:refine-mode' },
      ],
    },
  },

  {
    id: 'labels',
    keywords: ['label', 'etiquette', 'filtre', 'categorie', 'classification', 'action', 'info', 'bruit', 'noise', 'trier', 'tri', 'etiqueta', 'ruido', 'categoria'],
    patterns: [/label/, /etiquette/, /filtr/, /classif/, /categori/, /tri(er)?/, /\bbruit\b/, /\bnoise\b/, /etiqueta/],
    priority: 2,
    response: {
      text: 'r_labels',
      quickActions: [
        { label: 'art_auto_labeling_title', action: 'help-article:auto-labeling' },
        { label: 'c_relabel', action: 'input:comment corriger un label' },
        { label: 'c_search', action: 'input:comment rechercher un email' },
      ],
    },
  },

  {
    id: 'relabel-train',
    keywords: ['corriger', 'corriger label', 'mauvais label', 'reclasser', 'mal classe', 'mal trie', 'apprendre', 'entrainer', 'relabel', 'wrong label', 'reclasificar', 'corregir', 'corregir etiqueta'],
    patterns: [/corrig(er|e).*(label|etiquette|classement)/, /mauvais\s+(label|tri|classement)/, /reclass/, /mal\s+(classe|trie|range)/, /(re)?label.*(wrong|train)/, /wrong\s+label/, /corregir.*etiqueta/, /reclasificar/],
    priority: 4,
    response: {
      text: 'r_relabel',
      quickActions: [
        { label: 'art_label_correction_title', action: 'help-article:label-correction' },
        { label: 'art_auto_labeling_title', action: 'help-article:auto-labeling' },
      ],
    },
  },

  {
    id: 'search',
    keywords: ['chercher', 'rechercher', 'trouver', 'retrouver', 'email specifique', 'search', 'find', 'buscar', 'encontrar'],
    patterns: [/cherch/, /recherch/, /trouv/, /retrouv/, /ou\s+est/, /\bsearch\b/, /\bfind\b/, /buscar/, /encontrar/],
    priority: 2,
    response: {
      text: 'r_search',
      quickActions: [
        { label: 'art_search_title', action: 'help-article:search' },
        { label: 'c_shortcuts', action: 'input:quels sont les raccourcis' },
      ],
    },
  },

  {
    id: 'settings',
    keywords: ['parametre', 'reglage', 'configuration', 'preference', 'changer', 'settings', 'config', 'ajuste', 'preferencia'],
    patterns: [/parametr/, /reglag/, /preferenc/, /configur(er|ation)/, /\bsettings\b/, /\bajustes?\b/],
    priority: 2,
    response: {
      text: 'r_settings',
      quickActions: [
        { label: 'art_settings_overview_title', action: 'help-article:settings-overview' },
      ],
    },
  },

  {
    id: 'spam-trash',
    keywords: ['spam', 'indesirable', 'corbeille', 'poubelle', 'supprimer', 'restaurer', 'recuperer', 'trash', 'junk', 'papelera', 'restaurar'],
    patterns: [/spam/, /indesirable/, /corbeille/, /poubelle/, /restaur/, /recuper/, /\btrash\b/, /\bjunk\b/, /papelera/],
    priority: 3,
    response: {
      text: 'r_spam_trash',
      quickActions: [
        { label: 'c_another_question', action: 'input:j\'ai une autre question' },
      ],
    },
  },

  {
    id: 'auto-reply',
    keywords: ['absence', 'auto reply', 'vacances', 'conge', 'reponse automatique', 'out of office', 'vacation', 'ausencia', 'vacaciones', 'respuesta automatica'],
    patterns: [/absence/, /auto[\s-]?reply/, /vacance/, /conge/, /reponse\s+auto/, /out\s+of\s+office/, /vacation/, /ausencia/, /respuesta\s+automatica/],
    priority: 3,
    response: {
      text: 'r_auto_reply',
      quickActions: [
        { label: 'art_settings_overview_title', action: 'help-article:settings-overview' },
      ],
    },
  },

  {
    id: 'compose',
    keywords: ['nouveau', 'composer', 'ecrire', 'envoyer', 'message', 'email', 'rediger', 'compose', 'write', 'redactar', 'escribir', 'nuevo'],
    patterns: [/nouveau\s+(message|mail|email)/, /compos(er|ition|e)/, /ecrir(e|re)\s+un/, /envoyer\s+un/, /redig/, /write\s+(a\s+)?(new\s+)?(mail|email|message)/, /redactar/, /escribir\s+un/],
    priority: 2,
    response: {
      text: 'r_compose',
      quickActions: [
        { label: 'art_refine_mode_title', action: 'help-article:refine-mode' },
        { label: 'c_dictation', action: 'input:comment dicter un email' },
      ],
    },
  },

  {
    id: 'suggestions',
    keywords: ['suggestion', 'chip', 'reponse rapide', 'clic', 'rapide', 'quick reply', 'sugerencia', 'respuesta rapida'],
    patterns: [/suggestion/, /reponse\s+rapide/, /chip/, /en\s+un\s+clic/, /quick\s+repl/, /sugerencia/, /respuesta\s+rapida/],
    priority: 2,
    response: {
      text: 'r_suggestions',
      quickActions: [
        { label: 'art_smart_suggestions_title', action: 'help-article:smart-suggestions' },
      ],
    },
  },

  {
    id: 'security',
    keywords: ['securite', 'prive', 'donnee', 'confidentialite', 'rgpd', 'chiffrement', 'privacy', 'security', 'gdpr', 'seguridad', 'privacidad', 'datos'],
    patterns: [/securit/, /confidentiali/, /rgpd/, /gdpr/, /chiffr/, /prive/, /donnee.*personnel/, /privacy/, /seguridad/, /privacidad/],
    priority: 2,
    response: {
      text: 'r_security',
      quickActions: [
        { label: 'c_another_question', action: 'input:j\'ai une autre question' },
      ],
    },
  },

  // ═══════════════════════════════════════════════════════════════════
  // FEATURES — Fonctionnalités avancées
  // ═══════════════════════════════════════════════════════════════════
  {
    id: 'quicksteps',
    keywords: ['quick step', 'action rapide', 'palette', 'commande', 'ctrl k', 'cmd k', 'quickstep', 'quick action', 'paso rapido', 'accion rapida', 'comando'],
    patterns: [/quick\s*step/, /action[s]?\s+rapide/, /palette\s+(de\s+)?commande/, /\bctrl\s*\+?\s*k\b/, /\bcmd\s*\+?\s*k\b/, /command\s+palette/, /accion(es)?\s+rapida/, /paso[s]?\s+rapido/],
    priority: 4,
    response: {
      text: 'r_quicksteps',
      quickActions: [
        { label: 'art_quick_steps_title', action: 'help-article:quick-steps' },
        { label: 'c_auto_trigger', action: 'input:automatiser declencheur automatique' },
        { label: 'c_followups', action: 'input:relances et suivis' },
      ],
    },
  },

  {
    id: 'quicksteps-auto',
    keywords: ['automatiser', 'automatique', 'declencheur', 'trigger', 'auto', 'regle automatique', 'automatizar', 'disparador', 'automation'],
    patterns: [/automatis/, /declench/, /trigger/, /auto\s*(matique)?\s+(action|step|regle)/, /regle\s+automatique/, /automation/, /automatizar/, /disparador/],
    priority: 3,
    response: {
      text: 'r_quicksteps_auto',
      quickActions: [
        { label: 'art_quick_steps_title', action: 'help-article:quick-steps' },
        { label: 'c_followups', action: 'input:relances et suivis' },
      ],
    },
  },

  {
    id: 'followups',
    keywords: ['relance', 'suivi', 'follow up', 'followup', 'rappel reponse', 'pas de reponse', 'seguimiento', 'recordatorio', 'sin respuesta'],
    patterns: [/relance/, /follow[\s-]?up/, /suivi\s+(de\s+)?(relance|reponse)/, /(pas|aucune|sans)\s+de?\s*reponse/, /rappel.*reponse/, /seguimiento/, /sin\s+respuesta/],
    priority: 4,
    response: {
      text: 'r_followups',
      quickActions: [
        { label: 'art_follow_ups_title', action: 'help-article:follow-ups' },
        { label: 'c_quicksteps', action: 'input:utiliser les actions rapides' },
      ],
    },
  },

  {
    id: 'dictation',
    keywords: ['dicter', 'dictee', 'micro', 'vocal', 'voix', 'parler', 'dictate', 'voice', 'microphone', 'dictar', 'voz', 'microfono'],
    patterns: [/dict(er|ee|ation)/, /micro(phone)?/, /\bvocal\b/, /\bvoix\b/, /reconnaissance\s+vocale/, /dictate/, /voice\s+(to\s+text|input)/, /dictar/, /\bvoz\b/],
    priority: 4,
    response: {
      text: 'r_dictation',
      quickActions: [
        { label: 'art_dictation_title', action: 'help-article:dictation' },
        { label: 'c_send_email', action: 'input:comment écrire un nouvel email' },
      ],
    },
  },

  {
    id: 'calendar',
    keywords: ['calendrier', 'agenda', 'evenement', 'reunion', 'rendez vous', 'invitation', 'rsvp', 'meeting', 'calendar', 'event', 'invite', 'calendario', 'reunion', 'cita', 'evento'],
    patterns: [/calendrier/, /\bagenda\b/, /evenement/, /reunion/, /rendez[\s-]?vous/, /invitation/, /\brsvp\b/, /meeting/, /calendar/, /\bevent\b/, /calendario/, /\bcita\b/],
    priority: 4,
    response: {
      text: 'r_calendar',
      quickActions: [
        { label: 'art_calendar_title', action: 'help-article:calendar-rsvp' },
        { label: 'c_quicksteps', action: 'input:utiliser les actions rapides' },
      ],
    },
  },

  {
    id: 'subscriptions',
    keywords: ['abonnement', 'subscription', 'service payant', 'payant', 'facturation recurrente', 'desabonner', 'suscripcion', 'pago', 'recurrente'],
    patterns: [/abonnement\s+(payant|detecte|gerer)/, /subscription/, /service\s+payant/, /gerer\s+(mes\s+)?abonnement/, /suscripcion/],
    priority: 3,
    response: {
      text: 'r_subscriptions',
      quickActions: [
        { label: 'c_manage_newsletters', action: 'input:comment gérer les newsletters' },
        { label: 'c_another_question', action: 'input:j\'ai une autre question' },
      ],
    },
  },

  {
    id: 'newsletters',
    keywords: ['newsletter', 'infolettre', 'desabonner', 'bulk', 'masse', 'supprimer newsletter', 'boletin', 'darse de baja'],
    patterns: [/newsletter/, /infolettre/, /desabonn/, /supprimer.*(newsletter|infolettre)/, /trop\s+de\s+newsletter/, /boletin/, /darse\s+de\s+baja/],
    priority: 3,
    response: {
      text: 'r_newsletters',
      quickActions: [
        { label: 'c_paid_subs', action: 'input:comment voir mes abonnements payants' },
        { label: 'c_another_question', action: 'input:j\'ai une autre question' },
      ],
    },
  },

  {
    id: 'snippets',
    keywords: ['snippet', 'template', 'modele', 'texte reutilisable', 'reponse type', 'enregistrer', 'variable', 'fragment', 'plantilla', 'reutilizable'],
    patterns: [/snippet/, /fragment/, /template/, /modele\s+de\s+(texte|reponse|message)/, /texte\s+reutilisable/, /reponse\s+type/, /enregistrer\s+(un\s+)?(texte|modele)/, /plantilla/],
    priority: 3,
    response: {
      text: 'r_snippets',
      quickActions: [
        { label: 'art_snippets_title', action: 'help-article:snippets-templates' },
        { label: 'art_refine_mode_title', action: 'help-article:refine-mode' },
      ],
    },
  },

  {
    id: 'undo-send',
    keywords: ['annuler', 'envoi', 'undo', 'rappeler', 'envoye par erreur', 'retirer', 'annulation', 'cancel', 'deshacer', 'cancelar envio'],
    patterns: [/annuler\s+(l.)?envoi/, /undo\s+send/, /rappeler\s+(un\s+)?(mail|email|message)/, /envoye\s+par\s+erreur/, /retirer\s+(un\s+)?(mail|email)/, /deshacer\s+(el\s+)?envio/, /cancelar\s+(el\s+)?envio/],
    priority: 4,
    response: {
      text: 'r_undo_send',
      quickActions: [
        { label: 'art_undo_send_title', action: 'help-article:undo-send' },
        { label: 'c_another_question', action: 'input:j\'ai une autre question' },
      ],
    },
  },

  {
    id: 'deep-work',
    keywords: ['deep work', 'ne pas deranger', 'focus mode', 'concentration', 'creneaux', 'plage horaire', 'vip', 'focus', 'no molestar', 'concentracion'],
    patterns: [/deep\s*work/, /ne\s+pas\s+deranger/, /mode\s+(de\s+)?concentration/, /focus\s+mode/, /plage\s+horaire/, /creneaux?\s+(de\s+)?consultation/, /no\s+molestar/, /concentracion/],
    priority: 4,
    response: {
      text: 'r_deep_work',
      quickActions: [
        { label: 'art_deep_work_title', action: 'help-article:deep-work-mode' },
      ],
    },
  },

  {
    id: 'themes',
    keywords: ['theme', 'apparence', 'mode sombre', 'dark mode', 'couleur', 'clair', 'sombre', 'appearance', 'tema', 'apariencia', 'oscuro'],
    patterns: [/theme/, /tema/, /dark\s+mode/, /mode\s+sombre/, /changer\s+(l.)?apparence/, /couleur\s+de\s+l.app/, /appearance/, /apariencia/, /modo\s+oscuro/],
    priority: 2,
    response: {
      text: 'r_themes',
      quickActions: [
        { label: 'art_themes_title', action: 'help-article:themes-appearance' },
        { label: 'c_settings', action: 'input:comment accéder aux paramètres' },
      ],
    },
  },

  {
    id: 'monthly-recap',
    keywords: ['recap', 'statistiques', 'bilan', 'resume mensuel', 'analytics', 'stats', 'temps sauve', 'stats mensuelles', 'estadisticas', 'resumen mensual'],
    patterns: [/recap\s+(mensuel)?/, /statistiques/, /bilan\s+(mensuel|du\s+mois)/, /resume\s+mensuel/, /temps\s+(sauve|gagne|economise)/, /combien\s+de\s+temps/, /estadisticas/, /resumen\s+mensual/],
    priority: 2,
    response: {
      text: 'r_monthly_recap',
      quickActions: [
        { label: 'c_improve_style', action: 'input:comment améliorer le style de l\'ia' },
        { label: 'c_another_question', action: 'input:j\'ai une autre question' },
      ],
    },
  },

  {
    id: 'attachments',
    keywords: ['piece jointe', 'fichier', 'attachment', 'ci joint', 'joindre', 'pj', 'taille', 'attach', 'adjunto', 'archivo'],
    patterns: [/piece\s+jointe/, /fichier\s+joint/, /attachment/, /attach/, /ci[\s-]joint/, /joindre\s+(un\s+)?fichier/, /oublie.*piece\s+jointe/, /taille\s+(max|limite)/, /adjunt/],
    priority: 3,
    response: {
      text: 'r_attachments',
      quickActions: [
        { label: 'c_send_email', action: 'input:comment écrire un nouvel email' },
        { label: 'c_another_question', action: 'input:j\'ai une autre question' },
      ],
    },
  },

  {
    id: 'snooze',
    keywords: ['snooze', 'rappel', 'reporter', 'plus tard', 'revenir', 'differer', 'recordatorio', 'posponer', 'mas tarde'],
    patterns: [/snooze/, /rappel(er)?/, /reporter\s+(un\s+)?(email|mail)/, /plus\s+tard/, /revenir\s+sur/, /differer/, /posponer/, /mas\s+tarde/],
    priority: 3,
    response: {
      text: 'r_snooze',
      quickActions: [
        { label: 'c_followups', action: 'input:relances et suivis' },
        { label: 'c_another_question', action: 'input:j\'ai une autre question' },
      ],
    },
  },

  {
    id: 'multi-account',
    keywords: ['multi compte', 'plusieurs comptes', 'changer compte', 'ajouter compte', 'switch', 'basculer', 'varias cuentas', 'cambiar cuenta'],
    patterns: [/multi[\s-]?compte/, /plusieurs\s+compte/, /changer\s+de\s+compte/, /ajouter\s+(un\s+)?(autre\s+)?compte/, /basculer\s+(entre|de)\s+compte/, /switch\s+account/, /varias\s+cuentas/, /cambiar\s+(de\s+)?cuenta/],
    priority: 3,
    response: {
      text: 'r_multi_account',
      quickActions: [
        { label: 'c_connect_account', action: 'input:comment connecter mon compte' },
        { label: 'c_connection_problem', action: 'input:je n\'arrive pas à connecter mon compte' },
      ],
    },
  },

  // ═══════════════════════════════════════════════════════════════════
  // ESCALATION — Dernier recours seulement
  // ═══════════════════════════════════════════════════════════════════
  {
    id: 'pricing',
    keywords: ['prix', 'cout', 'tarif', 'abonnement', 'gratuit', 'payant', 'facturation', 'payer', 'price', 'cost', 'precio', 'tarifa', 'facturacion'],
    patterns: [/prix/, /cout/, /tarif/, /facturation/, /factur/, /\bpayer\b/, /\bprice\b/, /\bcost\b/, /precio/, /tarifa/],
    priority: 2,
    response: {
      text: 'r_pricing',
      quickActions: [
        { label: 'c_ask_question', action: 'escalate:support' },
      ],
    },
  },

  {
    id: 'feature-request',
    keywords: ['idee', 'fonctionnalite', 'proposer', 'souhaiter', 'aimerai', 'suggestion fonctionnalite', 'feature', 'idea', 'sugerir', 'funcionalidad'],
    patterns: [/j.?aimerai/, /serait\s+(bien|cool|genial)/, /vous\s+pourriez/, /proposer\s+une/, /nouvelle\s+fonctionnalit/, /feature\s+request/, /\bidea\b/, /me\s+gustaria/],
    priority: 1,
    response: {
      text: 'r_feature_request',
      quickActions: [
        { label: 'c_suggest_idea', action: 'form:feature' },
        { label: 'c_share_feedback', action: 'form:feedback' },
      ],
    },
  },

  {
    id: 'bug-report',
    keywords: ['bug', 'crash', 'plante', 'erreur grave', 'error', 'falla', 'se cierra'],
    patterns: [/bug/, /crash/, /plante/, /erreur\s+grave/, /se\s+cierra/, /\bfalla\b/],
    priority: 3,
    response: {
      text: 'r_bug_report',
      quickActions: [
        { label: 'c_problem_persists', action: 'form:bug' },
        { label: 'c_resolved', action: 'input:merci c\'est résolu' },
      ],
    },
  },

  {
    id: 'contact-human',
    keywords: ['humain', 'personne', 'agent', 'support', 'contacter', 'parler', 'human', 'contact', 'humano', 'persona', 'contactar', 'hablar'],
    patterns: [/parler\s+(a\s+)?(un\s+)?(humain|personne|agent)/, /contacter\s+(le\s+)?support/, /besoin\s+d.aide/, /(talk|speak)\s+to\s+(a\s+)?(human|person|agent)/, /contactar\s+(con\s+)?(soporte|alguien)/, /hablar\s+con/],
    priority: 4,
    response: {
      text: 'r_contact_human',
      quickActions: [
        { label: 'c_account_problem', action: 'input:je n\'arrive pas à connecter mon compte' },
        { label: 'c_technical_problem', action: 'input:j\'ai un problème technique' },
        { label: 'c_contact_team', action: 'escalate:support' },
      ],
    },
  },

  // generic-problem is now handled by 'something-broken' in core journeys
]

/** Sort rules by priority desc */
const SORTED_RULES = [...RULES].sort((a, b) => (b.priority || 0) - (a.priority || 0))

/** Fallback: guide toward self-service, NOT support */
const FALLBACK: ChatResponse = {
  text: 'r_fallback',
  quickActions: [
    { label: 'welcome_action_help', action: 'navigate:help' },
    { label: 'c_something_broken', action: 'input:j\'ai un problème' },
    { label: 'c_how_it_works', action: 'input:comment utiliser agentys' },
  ],
}

export function getResponse(input: string): ChatResponse {
  const normalized = normalize(input)
  if (!normalized) return FALLBACK

  let bestRule: Rule | null = null
  let bestScore = 0

  for (const rule of SORTED_RULES) {
    let score = 0

    // Pattern match (high value)
    if (rule.patterns) {
      for (const pattern of rule.patterns) {
        if (pattern.test(normalized)) {
          score += 10
          break
        }
      }
    }

    // Keyword match (count matches)
    for (const kw of rule.keywords) {
      if (normalized.includes(kw)) {
        score += 3
      }
    }

    // Priority boost
    score += (rule.priority || 0) * 0.5

    if (score > bestScore) {
      bestScore = score
      bestRule = rule
    }
  }

  if (bestRule && bestScore >= 3) {
    // Append related article links when available
    const articles = searchArticles(input)
    if (articles.length > 0) {
      const articleActions: QuickAction[] = articles.map(a => ({
        label: a.titleKey, // resolved by component via t()
        action: `help-article:${a.id}`,
        icon: 'help',
      }))
      const existingActions = bestRule.response.quickActions || []
      return {
        ...bestRule.response,
        quickActions: [...existingActions, ...articleActions],
      }
    }
    return bestRule.response
  }

  // No rule matched — try article search as fallback
  const articles = searchArticles(input)
  if (articles.length > 0) {
    const articleActions: QuickAction[] = articles.map(a => ({
      label: a.titleKey,
      action: `help-article:${a.id}`,
      icon: 'help',
    }))
    return {
      text: FALLBACK.text,
      quickActions: [...articleActions, ...(FALLBACK.quickActions || [])],
    }
  }

  return FALLBACK
}

/** Article keyword index for search integration */
export interface ArticleEntry {
  id: string
  titleKey: string
  keywords: string[]
}

export const ARTICLE_INDEX: ArticleEntry[] = [
  { id: 'connect-account', titleKey: 'art_connect_account_title', keywords: ['connect', 'account', 'gmail', 'outlook', 'imap', 'oauth', 'compte', 'connexion', 'conectar', 'cuenta'] },
  { id: 'draft-pipeline', titleKey: 'art_draft_pipeline_title', keywords: ['pipeline', 'draft', 'brouillon', 'how', 'work', 'fonctionne', 'process', 'borrador'] },
  { id: 'smart-suggestions', titleKey: 'art_smart_suggestions_title', keywords: ['suggestion', 'chip', 'quick', 'reply', 'rapide', 'clic', 'sugerencia'] },
  { id: 'refine-mode', titleKey: 'art_refine_mode_title', keywords: ['refine', 'improve', 'edit', 'modifier', 'ameliorer', 'corriger', 'instruction', 'affiner', 'refinar'] },
  { id: 'shortcuts-nav', titleKey: 'art_shortcuts_nav_title', keywords: ['shortcut', 'keyboard', 'raccourci', 'clavier', 'touche', 'navigation', 'atajo'] },
  { id: 'shortcuts-actions', titleKey: 'art_shortcuts_actions_title', keywords: ['shortcut', 'action', 'raccourci', 'clavier', 'rapide', 'atajo'] },
  { id: 'quick-steps', titleKey: 'art_quick_steps_title', keywords: ['quick', 'step', 'action', 'rapide', 'palette', 'commande', 'ctrl', 'cmd', 'automatiser', 'trigger', 'paso', 'comando'] },
  { id: 'follow-ups', titleKey: 'art_follow_ups_title', keywords: ['relance', 'follow', 'suivi', 'rappel', 'reponse', 'followup', 'seguimiento'] },
  { id: 'dictation', titleKey: 'art_dictation_title', keywords: ['dicter', 'dictee', 'micro', 'vocal', 'voix', 'dictate', 'voice', 'dictar', 'voz'] },
  { id: 'calendar-rsvp', titleKey: 'art_calendar_title', keywords: ['calendrier', 'agenda', 'reunion', 'invitation', 'rsvp', 'meeting', 'calendar', 'event', 'calendario', 'cita'] },
  { id: 'snippets-templates', titleKey: 'art_snippets_title', keywords: ['snippet', 'template', 'modele', 'texte', 'reusable', 'reutilisable', 'variable', 'fragment', 'plantilla'] },
  { id: 'auto-labeling', titleKey: 'art_auto_labeling_title', keywords: ['label', 'etiquette', 'auto', 'classification', 'filtre', 'categorie', 'action', 'info', 'bruit', 'etiqueta'] },
  { id: 'label-correction', titleKey: 'art_label_correction_title', keywords: ['corriger', 'label', 'reclasser', 'apprendre', 'entrainer', 'relabel', 'wrong', 'corregir', 'etiqueta'] },
  { id: 'undo-send', titleKey: 'art_undo_send_title', keywords: ['undo', 'annuler', 'envoi', 'rappeler', 'cancel', 'send', 'deshacer'] },
  { id: 'themes-appearance', titleKey: 'art_themes_title', keywords: ['theme', 'dark', 'sombre', 'apparence', 'couleur', 'color', 'tema', 'apariencia'] },
  { id: 'subscriptions-newsletters', titleKey: 'art_subscriptions_title', keywords: ['subscription', 'abonnement', 'newsletter', 'infolettre', 'desabonner', 'suscripcion', 'boletin'] },
  { id: 'deep-work-mode', titleKey: 'art_deep_work_title', keywords: ['deep work', 'concentration', 'focus', 'vip', 'concentracion'] },
  { id: 'search', titleKey: 'art_search_title', keywords: ['search', 'chercher', 'rechercher', 'trouver', 'find', 'buscar'] },
  { id: 'settings-overview', titleKey: 'art_settings_overview_title', keywords: ['settings', 'parametre', 'configurer', 'preference', 'reglage', 'ajustes', 'configuracion'] },
  { id: 'first-drafts', titleKey: 'art_first_drafts_title', keywords: ['first', 'premier', 'commencer', 'debut', 'start', 'getting started', 'primero', 'empezar'] },
]

/** Search articles by input text — returns top matches */
export function searchArticles(input: string): ArticleEntry[] {
  const norm = normalize(input)
  if (!norm) return []
  const words = norm.split(/\s+/)

  const scored = ARTICLE_INDEX.map(article => {
    let score = 0
    for (const word of words) {
      for (const kw of article.keywords) {
        if (kw.includes(word) || word.includes(kw)) {
          score += 3
        }
      }
    }
    return { article, score }
  })

  return scored
    .filter(s => s.score >= 3)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map(s => s.article)
}

/** Popular articles shown on welcome screen — capped at 3 for a calmer hierarchy */
export const POPULAR_ARTICLE_IDS = [
  'connect-account',
  'quick-steps',
  'draft-pipeline',
]

/**
 * Initial greeting — quick action labels resolved against the active locale.
 *
 * The component owns the greeting text via `t('welcome_greeting_short')`, so
 * we leave `text` empty here. Each quick action carries an i18n-resolved label
 * plus an `input:` payload that drives the rule engine. Payloads stay in
 * French because rule keywords are normalized for FR/EN/ES fuzzy matching —
 * they are not user-facing strings.
 *
 * We pass each label through `t(key, defaultValue)` so the welcome screen
 * stays correct even when the locale JSON lacks the key — i18next falls back
 * to the English default instead of rendering the raw key string. Locale
 * teams can add translations later without code changes.
 */
type TFn = (key: string, defaultValue?: string) => string

export function getWelcomeMessage(t: TFn): ChatResponse {
  return {
    text: '',
    quickActions: [
      { label: t('welcome_card_drafts_label', 'Find my AI drafts'), action: 'input:où sont mes brouillons ia', icon: 'drafts' },
      { label: t('welcome_card_style_label', 'Improve AI style'), action: 'input:comment ameliorer le style ia', icon: 'style' },
      { label: t('welcome_card_productivity_label', 'Process emails faster'), action: 'input:comment traiter mes emails plus vite', icon: 'speed' },
      { label: t('welcome_card_problem_label', 'Fix a problem'), action: 'input:quelque chose ne marche pas', icon: 'problem' },
      { label: t('welcome_action_suggest', 'Suggest an idea'), action: 'form:feature', icon: 'idea' },
      { label: t('welcome_action_bug', 'Report a bug'), action: 'form:bug', icon: 'bug' },
    ],
  }
}
