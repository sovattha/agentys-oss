// Types and utilities for the Training Panel (Entrainement Agentys)

export type LanguagePreset = 'francais' | 'anglais' | 'auto'
export type LanguageVariant = string
export type Pillar = 'profil' | 'style' | 'savoir' | 'autolabel'

export type EmailLength = 'concis' | 'moyen' | 'detaille'
export type WritingComplexity = 'accessible' | 'standard' | 'elabore'

export interface FormatSettings {
  longueur: EmailLength
  complexite: WritingComplexity
}

// Issue #187: ton_defaut + emotion_level supprimés.
// Le ton est désormais dérivé automatiquement depuis l'outbox via
// StyleInferenceService (backend) et exposé via /api/style/reanalyze.
export interface ProfilData {
  nom_complet: string
  entreprise: string
  poste: string
  langue: LanguagePreset
  langue_variante?: LanguageVariant
  format?: FormatSettings
  // Legacy "Surnoms" line from memoire.md. Per-contact nicknames now live in
  // ContactStyleProfile, not here — but the raw line is round-tripped verbatim
  // so a Training-page Save never silently strips it from an older memoire.md.
  // Not parsed into structured data, not used by drafts. See audit 2026-05-14 F-02.
  surnoms_passthrough?: string
}

export type KnowledgeCategory = 'FAQ' | 'TECHNIQUE' | 'CONTACT' | 'PROJET' | 'REGLE' | 'GENERAL'

export interface SavoirEntry {
  id: string
  question: string
  answer: string
  category: KnowledgeCategory
  context?: string  // when to use this knowledge (e.g. "quand l'email mentionne tarif, prix")
}

export interface RegleEntry {
  id: string
  text: string
}

export interface TrainingData {
  profil: ProfilData
  savoir: SavoirEntry[]
  regles: RegleEntry[]
}

export type FormalityLevel = 'formal' | 'casual' | 'mixed'

export interface ContactStyleProfile {
  email: string
  formality_override: FormalityLevel | null
  preferred_greeting: string | null
  preferred_closing: string | null
  langue_variante: LanguageVariant | null
  langue: string | null
  nickname?: string | null
  // Auto-derivation flags (server-side):
  // `formality_locked` is set to true when the user edits the chip
  // manually. While false, every successful send re-derives the override
  // from the just-sent body. `formality_updated_at` is the ISO-8601 UTC
  // timestamp of the last derivation/edit, surfaced as "Updated …" in
  // the per-contact card.
  formality_locked?: boolean
  formality_updated_at?: string | null
}

export interface DefaultStyleSettings {
  formality_level: FormalityLevel
  preferred_greetings: string[]
  preferred_closings: string[]
  typical_signature: string | null
}

// ── Learned data types (from account-scoped learning endpoints) ──

export interface DraftCorrectionItem {
  id: string
  contact: string
  diff_summary: string
  timestamp: string
}

export interface DraftRuleItem {
  id: string
  rule_text: string
  category: string
  scope: string
  contact: string
  confidence: number
  active: boolean
  created_at?: string
  [key: string]: unknown
}

export interface AutoLabelRule {
  id: string
  rule_text: string
  category: string
  // Per-rule precision (0..1), or null when the rule has not matched any email
  // yet (backend returns precision=null for total_matches=0). Kept nullable so
  // we never render a misleading "0%" for a brand-new rule with no data.
  confidence: number | null
  active: boolean
  created_at?: string
  total_matches?: number
  total_corrections?: number
}

// Per-label email volume from /api/learning/all (auto-label category):
// how many emails carry each label, counted across ALL folders (inbox +
// archived + trash) — the auto-sorter's total observable output.
export interface AutoLabelLabelStat {
  label: string
  email_count: number
}

// ── Memory Trace (#159) — what memory was injected into the draft prompt ──

export interface MemoryTraceRule {
  id: string
  rule_text: string
  confidence?: number
}

export interface MemoryTraceSavoir {
  id: string
  question: string
  category: string
}

export interface MemoryTrace {
  profil: Record<string, string>
  style_default: Record<string, unknown>
  style_contact: Record<string, unknown> | null
  savoir: MemoryTraceSavoir[]
  rules: MemoryTraceRule[]
}

export interface LearnedCategory {
  id: string
  name: string
  description: string
  count: number
  positive_count?: number
  total_drafts?: number
  accuracy?: number
  total_matches?: number
  total_corrections?: number
  by_label?: AutoLabelLabelStat[]
  items: Array<DraftCorrectionItem | DraftRuleItem | AutoLabelRule | { id: string; text?: string; rule_text?: string }>
}

export interface AutoLabelCategory {
  id: string
  name: string
  description: string
  count: number
  accuracy?: number
  total_matches?: number
  total_corrections?: number
  by_label?: AutoLabelLabelStat[]
  items: AutoLabelRule[]
}

let _nextId = 1
function genId(): string {
  return `t_${Date.now()}_${_nextId++}`
}

export function emptyTrainingData(): TrainingData {
  return {
    profil: {
      nom_complet: '',
      entreprise: '',
      poste: '',
      langue: 'auto',
      format: {
        longueur: 'moyen',
        complexite: 'standard',
      },
    },
    savoir: [],
    regles: [],
  }
}

// ---------------------------------------------------------------------------
// Parse structured markdown → TrainingData
// ---------------------------------------------------------------------------

export function parseMarkdownToTraining(md: string): TrainingData {
  const data = emptyTrainingData()

  const hasProfilSection = /^## Profil/m.test(md)
  const hasSavoirSection = /^## Savoir/m.test(md)
  const hasReglesSection = /^## R[eè]gles/m.test(md)

  // If the markdown doesn't have our structured format, treat as legacy
  if (!hasProfilSection && !hasSavoirSection && !hasReglesSection) {
    const trimmed = md.trim()
    if (trimmed) {
      data.savoir.push({
        id: genId(),
        question: 'Existing content',
        answer: trimmed,
        category: 'GENERAL',
      })
    }
    return data
  }

  // Split into sections by ## headings
  const sections = splitSections(md)

  // Parse Profil
  const profilSection = sections['profil'] || ''
  if (profilSection) {
    data.profil.nom_complet = extractField(profilSection, 'Nom complet')
    data.profil.entreprise = extractField(profilSection, 'Entreprise')
    data.profil.poste = extractField(profilSection, 'Poste')
    // Issue #187: Ton par défaut et Niveau d'émotion ne sont plus lus depuis
    // memoire.md — l'inférence se fait depuis l'outbox via StyleInferenceService.
    // Les lignes "Ton par défaut" et "Niveau d'émotion" éventuellement présentes
    // dans d'anciens fichiers sont ignorées silencieusement.
    const langue = extractField(profilSection, 'Langue').toLowerCase()
    if (langue === 'français' || langue === 'francais') data.profil.langue = 'francais'
    else if (langue === 'anglais' || langue === 'english') data.profil.langue = 'anglais'
    else data.profil.langue = 'auto'

    const variante = extractField(profilSection, 'Variante linguistique')
    if (variante && ['fr-neutral', 'fr-QC', 'fr-FR', 'fr-BE', 'en-NA', 'en-UK'].includes(variante)) {
      data.profil.langue_variante = variante as LanguageVariant
    }

    // The legacy "Surnoms" line is no longer a structured field (per-contact
    // nicknames moved to ContactStyleProfile), but we preserve it verbatim so
    // a Save never silently strips it from an older memoire.md. See audit F-02.
    const surnoms = extractField(profilSection, 'Surnoms')
    if (surnoms) data.profil.surnoms_passthrough = surnoms
  }

  // Parse Format section
  const formatSection = sections['format'] || ''
  if (formatSection) {
    const longueur = extractField(formatSection, 'Longueur pr[ée]f[ée]r[ée]e').toLowerCase()
    if (longueur === 'concis' || longueur === 'moyen' || longueur === 'detaille') {
      data.profil.format = { ...data.profil.format!, longueur: longueur as EmailLength }
    }
    const vocab = extractField(formatSection, 'Vocabulaire').toLowerCase()
    if (vocab === 'accessible' || vocab === 'standard' || vocab === 'elabore') {
      data.profil.format = { ...data.profil.format!, complexite: vocab as WritingComplexity }
    }
  }

  // Parse Savoir — ### sub-headings (canonical format)
  const savoirSection = sections['savoir'] || ''
  if (savoirSection) {
    const subSections = savoirSection.split(/^### /m).filter(Boolean)
    if (subSections.length > 1 || savoirSection.includes('### ')) {
      for (const sub of subSections) {
        const lines = sub.trim().split('\n')
        const question = lines[0]?.trim()
        let category: KnowledgeCategory = 'GENERAL'
        let context = ''
        const catLine = lines.find(l => /^<!--\s*category:\s*/i.test(l.trim()))
        if (catLine) {
          const catMatch = catLine.match(/category:\s*(\w+)/i)
          if (catMatch) category = catMatch[1].toUpperCase() as KnowledgeCategory
        }
        const ctxLine = lines.find(l => /^<!--\s*context:\s*/i.test(l.trim()))
        if (ctxLine) {
          const ctxMatch = ctxLine.match(/context:\s*(.+?)-->/i)
          if (ctxMatch) context = ctxMatch[1].trim()
        }
        const answer = lines.slice(1)
          .filter(l => !/^<!--\s*(category|context):/i.test(l.trim()))
          .join('\n').trim()
        // Skip Contact/Projet entries — not useful as knowledge
        if (question && !/^(Contact|Projet)\s*:/i.test(question)) {
          data.savoir.push({ id: genId(), question, answer, category, ...(context ? { context } : {}) })
        }
      }
    } else {
      // Legacy **Q:**/**R:** — auto-migrate to ### on next save
      const qrPairs = savoirSection.split(/(?=\*\*Q\s*:\s*)/).filter(Boolean)
      for (const pair of qrPairs) {
        const qMatch = pair.match(/\*\*Q\s*:\*\*\s*(.+)/)
        const rMatch = pair.match(/\*\*R\s*:\*\*\s*([\s\S]*?)$/)
        if (qMatch) {
          data.savoir.push({
            id: genId(),
            question: qMatch[1].trim(),
            answer: rMatch ? rMatch[1].trim() : '',
            category: 'GENERAL',
          })
        }
      }
      if (data.savoir.length === 0 && savoirSection.trim()) {
        data.savoir.push({ id: genId(), question: 'Notes', answer: savoirSection.trim(), category: 'GENERAL' })
      }
    }
  }

  // Parse Regles — bullet list
  const reglesSection = sections['regles'] || sections['règles'] || ''
  if (reglesSection) {
    const lines = reglesSection.split('\n')
    for (const line of lines) {
      const match = line.match(/^[-*]\s+(.+)/)
      if (match) {
        data.regles.push({ id: genId(), text: match[1].trim() })
      }
    }
  }

  return data
}

// ---------------------------------------------------------------------------
// Serialize TrainingData → structured markdown
// ---------------------------------------------------------------------------

export function serializeTrainingToMarkdown(data: TrainingData): string {
  const lines: string[] = []

  lines.push('## Profil')
  lines.push('')
  lines.push(`- **Nom complet**: ${data.profil.nom_complet || '[À définir]'}`)
  lines.push(`- **Entreprise**: ${data.profil.entreprise || '[À définir]'}`)
  lines.push(`- **Poste**: ${data.profil.poste || '[À définir]'}`)

  const langueLabels: Record<LanguagePreset, string> = {
    francais: 'French',
    anglais: 'English',
    auto: 'Auto',
  }
  lines.push(`- **Langue**: ${langueLabels[data.profil.langue]}`)

  // Issue #187: Ton par défaut et Niveau d'émotion ne sont plus sérialisés
  // dans memoire.md. Le ton est inféré automatiquement depuis l'outbox.

  if (data.profil.langue_variante) {
    lines.push(`- **Variante linguistique**: ${data.profil.langue_variante}`)
  }

  // Round-trip the legacy "Surnoms" line verbatim (see parseMarkdownToTraining
  // and audit 2026-05-14 F-02). Preserved as-is, not regenerated from data.
  if (data.profil.surnoms_passthrough) {
    lines.push(`- **Surnoms**: ${data.profil.surnoms_passthrough}`)
  }

  if (data.profil.format) {
    const f = data.profil.format
    lines.push('')
    lines.push('## Format')
    lines.push('')
    lines.push(`- **Longueur préférée**: ${f.longueur}`)
    lines.push(`- **Vocabulaire**: ${f.complexite}`)
  }

  lines.push('')
  lines.push('## Savoir')
  lines.push('')

  if (data.savoir.length === 0) {
    lines.push('_No knowledge entries recorded._')
  } else {
    for (const entry of data.savoir) {
      lines.push(`### ${entry.question}`)
      if (entry.category && entry.category !== 'GENERAL') {
        lines.push(`<!-- category: ${entry.category} -->`)
      }
      if (entry.context) {
        lines.push(`<!-- context: ${entry.context} -->`)
      }
      lines.push('')
      if (entry.answer) {
        lines.push(entry.answer)
        lines.push('')
      }
    }
  }

  lines.push('## Regles')
  lines.push('')

  if (data.regles.length === 0) {
    lines.push('- Adapt formal/informal address based on the original email')
    lines.push('- Professional but warm tone')
  } else {
    for (const rule of data.regles) {
      lines.push(`- ${rule.text}`)
    }
  }

  lines.push('')
  return lines.join('\n')
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function splitSections(md: string): Record<string, string> {
  const sections: Record<string, string> = {}
  const parts = md.split(/^## /m)

  for (const part of parts) {
    if (!part.trim()) continue
    const firstNewline = part.indexOf('\n')
    if (firstNewline === -1) continue
    const heading = part.substring(0, firstNewline).trim().toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '') // remove accents
    const body = part.substring(firstNewline + 1)
    sections[heading] = body
  }

  return sections
}

function extractField(text: string, fieldPattern: string): string {
  const regex = new RegExp(`\\*\\*${fieldPattern}\\*\\*\\s*:\\s*(.+)`, 'i')
  const match = text.match(regex)
  if (match) {
    const val = match[1].trim()
    const empty = new Set(['[a definir]', '[à définir]', '[to define]', 'none'])
    return empty.has(val.toLowerCase()) ? '' : val
  }
  return ''
}
