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

import { useState, useMemo, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import DOMPurify from 'dompurify'
import { ChevronLeftIcon, ChevronRightIcon, SearchIcon } from '../icons/ActionIcons'

interface Article {
  id: string
  titleKey: string
  /** i18n key (namespace `support`) holding the article body as markdown. */
  bodyKey: string
  keywords: string[]
}

interface Category {
  id: string
  nameKey: string
  icon: ReactNode
  articles: Article[]
}

/**
 * Article bodies live in `support.json` (one markdown string per `bodyKey`),
 * so help content is fully localized (fr/es/en) and editable without code
 * changes. We render with the same mini-grammar as the chat bubble:
 *   **bold**, `code`, and one paragraph per non-empty line.
 */
function ArticleBody({ markdown }: { markdown: string }) {
  return (
    <>
      {markdown.split('\n').map((line, i) => {
        if (!line.trim()) return null
        const html = DOMPurify.sanitize(
          line
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/`(.+?)`/g, '<code>$1</code>'),
          { ALLOWED_TAGS: ['strong', 'code', 'em'] },
        )
        return <p key={i} dangerouslySetInnerHTML={{ __html: html }} />
      })}
    </>
  )
}

const HELP_DATA: Category[] = [
  {
    id: 'getting-started',
    nameKey: 'cat_getting_started',
    icon: (
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><path d="m9 11 3 3L22 4" />
      </svg>
    ),
    articles: [
      { id: 'connect-account', titleKey: 'art_connect_account_title', bodyKey: 'a_connect_account', keywords: ['gmail', 'outlook', 'imap', 'connexion', 'compte', 'conectar', 'cuenta'] },
      { id: 'first-drafts', titleKey: 'art_first_drafts_title', bodyKey: 'a_first_drafts', keywords: ['brouillon', 'draft', 'ia', 'commencer', 'premier', 'borrador', 'empezar'] },
      { id: 'settings-overview', titleKey: 'art_settings_overview_title', bodyKey: 'a_settings_overview', keywords: ['paramètres', 'configuration', 'settings', 'préférences', 'ajustes'] },
    ],
  },
  {
    id: 'ai-drafts',
    nameKey: 'cat_ai_drafts',
    icon: (
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
        <path d="M14 2v4a1 1 0 0 0 1 1h4" />
      </svg>
    ),
    articles: [
      { id: 'draft-pipeline', titleKey: 'art_draft_pipeline_title', bodyKey: 'a_draft_pipeline', keywords: ['pipeline', 'drafter', 'génération', 'relance', 'à la demande', 'borrador'] },
      { id: 'smart-suggestions', titleKey: 'art_smart_suggestions_title', bodyKey: 'a_smart_suggestions', keywords: ['suggestions', 'smart', 'chips', 'rapide', 'sugerencia'] },
      { id: 'refine-mode', titleKey: 'art_refine_mode_title', bodyKey: 'a_refine_mode', keywords: ['refine', 'modifier', 'améliorer', 'instruction', 'affiner', 'refinar'] },
    ],
  },
  {
    id: 'quick-steps',
    nameKey: 'cat_quick_steps',
    icon: (
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />
      </svg>
    ),
    articles: [
      { id: 'quick-steps', titleKey: 'art_quick_steps_title', bodyKey: 'a_quick_steps', keywords: ['quick step', 'action rapide', 'palette', 'ctrl k', 'cmd k', 'commande', 'automatiser', 'trigger', 'paso', 'comando'] },
      { id: 'follow-ups', titleKey: 'art_follow_ups_title', bodyKey: 'a_follow_ups', keywords: ['relance', 'follow up', 'suivi', 'rappel', 'sans réponse', 'seguimiento'] },
    ],
  },
  {
    id: 'shortcuts',
    nameKey: 'cat_shortcuts',
    icon: (
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="4" width="20" height="16" rx="2" /><path d="M6 8h.01" /><path d="M10 8h.01" /><path d="M14 8h.01" /><path d="M18 8h.01" /><path d="M8 12h.01" /><path d="M12 12h.01" /><path d="M16 12h.01" /><path d="M7 16h10" />
      </svg>
    ),
    articles: [
      { id: 'shortcuts-nav', titleKey: 'art_shortcuts_nav_title', bodyKey: 'a_shortcuts_nav', keywords: ['j', 'k', 'navigation', 'haut', 'bas', 'flèches', 'atajo'] },
      { id: 'shortcuts-actions', titleKey: 'art_shortcuts_actions_title', bodyKey: 'a_shortcuts_actions', keywords: ['répondre', 'archiver', 'supprimer', 'transférer', 'responder'] },
    ],
  },
  {
    id: 'features',
    nameKey: 'cat_features',
    icon: (
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
      </svg>
    ),
    articles: [
      { id: 'dictation', titleKey: 'art_dictation_title', bodyKey: 'a_dictation', keywords: ['dicter', 'micro', 'vocal', 'voix', 'dictate', 'voice', 'dictar', 'voz'] },
      { id: 'calendar-rsvp', titleKey: 'art_calendar_title', bodyKey: 'a_calendar', keywords: ['calendrier', 'agenda', 'réunion', 'invitation', 'rsvp', 'meeting', 'calendario', 'cita'] },
      { id: 'subscriptions-newsletters', titleKey: 'art_subscriptions_title', bodyKey: 'a_subscriptions', keywords: ['abonnement', 'newsletter', 'désabonner', 'subscription', 'payant', 'suscripcion', 'boletin'] },
      { id: 'snippets-templates', titleKey: 'art_snippets_title', bodyKey: 'a_snippets', keywords: ['fragment', 'snippet', 'template', 'modèle', 'réutilisable', 'variable', 'plantilla'] },
      { id: 'deep-work-mode', titleKey: 'art_deep_work_title', bodyKey: 'a_deep_work', keywords: ['concentration', 'deep work', 'focus', 'créneau', 'vip', 'concentracion'] },
      { id: 'undo-send', titleKey: 'art_undo_send_title', bodyKey: 'a_undo_send', keywords: ['annuler', 'envoi', 'undo', 'rappeler', 'erreur', 'deshacer'] },
      { id: 'themes-appearance', titleKey: 'art_themes_title', bodyKey: 'a_themes', keywords: ['thème', 'apparence', 'sombre', 'clair', 'couleur', 'tema'] },
    ],
  },
  {
    id: 'labels-filters',
    nameKey: 'cat_labels_filters',
    icon: (
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2 2 7l10 5 10-5-10-5Z" /><path d="m2 17 10 5 10-5" /><path d="m2 12 10 5 10-5" />
      </svg>
    ),
    articles: [
      { id: 'auto-labeling', titleKey: 'art_auto_labeling_title', bodyKey: 'a_auto_labeling', keywords: ['label', 'auto', 'catégorie', 'classification', 'action', 'info', 'bruit', 'etiqueta'] },
      { id: 'label-correction', titleKey: 'art_label_correction_title', bodyKey: 'a_label_correction', keywords: ['corriger', 'label', 'reclasser', 'apprendre', 'entraîner', 'relabel', 'corregir', 'etiqueta'] },
      { id: 'search', titleKey: 'art_search_title', bodyKey: 'a_search', keywords: ['recherche', 'chercher', 'trouver', 'filtrer', 'buscar'] },
    ],
  },
]

interface SupportHelpSectionProps {
  onNavigateToArticle: (articleId: string) => void
  articleId?: string
  onBack?: () => void
}

export function SupportHelpSection({ onNavigateToArticle, articleId }: SupportHelpSectionProps) {
  const { t } = useTranslation('support')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)

  function getCategoryName(cat: Category): string {
    return t(cat.nameKey)
  }

  function getArticleTitle(article: Article): string {
    return t(article.titleKey)
  }

  // Search results (must be before any conditional returns to respect hooks rules)
  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return null
    const q = searchQuery.toLowerCase()
    return HELP_DATA.flatMap(c => c.articles).filter(a =>
      t(a.titleKey).toLowerCase().includes(q) ||
      a.keywords.some(k => k.includes(q))
    )
  }, [searchQuery, t])

  // If viewing a specific article
  if (articleId) {
    const article = HELP_DATA.flatMap(c => c.articles).find(a => a.id === articleId)
    if (!article) return null
    return (
      <div className="sp-help-article-content">
        <ArticleBody markdown={t(article.bodyKey)} />
      </div>
    )
  }

  // Category articles view
  if (selectedCategory) {
    const cat = HELP_DATA.find(c => c.id === selectedCategory)
    if (!cat) return null
    return (
      <>
        <div className="sp-help-back-row">
          <button className="sp-header-back" onClick={() => setSelectedCategory(null)}>
            <ChevronLeftIcon size={16} />
          </button>
          <span className="sp-help-back-label">{getCategoryName(cat)}</span>
        </div>
        <div className="sp-help-articles">
          {cat.articles.map((article) => (
            <button
              key={article.id}
              className="sp-help-article-btn"
              onClick={() => onNavigateToArticle(article.id)}
            >
              <span className="sp-help-article-dot" />
              {getArticleTitle(article)}
            </button>
          ))}
        </div>
      </>
    )
  }

  return (
    <>
      <div className="sp-help-search">
        <div className="sp-help-search-wrap">
          <SearchIcon size={14} className="sp-help-search-icon" />
          <input
            type="text"
            placeholder={t('help_search_placeholder')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            autoFocus
          />
        </div>
      </div>

      {searchResults ? (
        searchResults.length > 0 ? (
          <div className="sp-help-articles">
            {searchResults.map((article) => (
              <button
                key={article.id}
                className="sp-help-article-btn"
                onClick={() => onNavigateToArticle(article.id)}
              >
                <span className="sp-help-article-dot" />
                {getArticleTitle(article)}
              </button>
            ))}
          </div>
        ) : (
          <div className="sp-help-no-results">{t('help_no_results', { query: searchQuery })}</div>
        )
      ) : (
        <div className="sp-help-categories">
          {HELP_DATA.map((cat) => (
            <button
              key={cat.id}
              className="sp-help-category"
              onClick={() => setSelectedCategory(cat.id)}
            >
              <span className="sp-help-category-icon">{cat.icon}</span>
              <span className="sp-help-category-label">{getCategoryName(cat)}</span>
              <span className="sp-help-category-count">{cat.articles.length}</span>
              <ChevronRightIcon size={14} className="sp-help-category-arrow" />
            </button>
          ))}
        </div>
      )}
    </>
  )
}
