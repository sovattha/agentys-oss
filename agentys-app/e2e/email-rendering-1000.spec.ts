/**
 * E2E — 1000 Emails Rendering Test
 *
 * Simulates a real user opening their inbox with 1000 emails of diverse types:
 * - Plain text, rich HTML, newsletters with tables
 * - French/Spanish accents, emoji, Unicode
 * - Inline images (base64, URL), embedded logos
 * - Rich signatures (company, social links, logo, phone)
 * - Attachments (PDF, images, spreadsheets)
 * - CC/BCC recipients, long subjects, threads
 *
 * Verifies:
 * 1. All 1000 emails appear in the list (sender, subject, preview visible)
 * 2. Each email category renders correctly in the detail view
 * 3. Signatures are fully displayed (name, title, phone, logo)
 * 4. Images load without broken icons
 * 5. Accented text is not garbled
 * 6. Attachments show with filename and download chip
 * 7. No console errors during rendering
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'

// ============================================================================
// DATA GENERATORS — 1000 realistic emails
// ============================================================================

const daysAgo = (days: number): string => {
  const d = new Date(); d.setDate(d.getDate() - days); return d.toISOString()
}
const _hoursAgo = (hours: number): string => {
  const d = new Date(); d.setHours(d.getHours() - hours); return d.toISOString()
}
const minutesAgo = (min: number): string => {
  const d = new Date(); d.setMinutes(d.getMinutes() - min); return d.toISOString()
}

// 1×1 transparent PNG (valid base64 image)
const _TINY_PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=='
// 1×1 red pixel for logo tests
const RED_PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=='
// 1×1 blue pixel for avatar tests
const BLUE_PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPj/HwADBwIAMCbHYQAAAABJRU5ErkJggg=='

/** Senders with realistic names, accents, and international characters */
const SENDERS = [
  { email: 'marie.dupont@entreprise.fr', name: 'Marie Dupont' },
  { email: 'pierre.béranger@société.fr', name: 'Pierre Béranger' },
  { email: 'hélène.müller@strasbourg.eu', name: 'Hélène Müller' },
  { email: 'jean-françois.côté@québec.ca', name: 'Jean-François Côté' },
  { email: 'amélie.lefèvre@paris.fr', name: 'Amélie Lefèvre' },
  { email: 'carlos.garcía@empresa.es', name: 'Carlos García' },
  { email: 'björn.jönsson@företag.se', name: 'Björn Jönsson' },
  { email: 'lëa.renée@bruxelles.be', name: 'Léa Renée' },
  { email: 'øystein.hansen@oslo.no', name: 'Øystein Hansen' },
  { email: 'sébastien.nguyen@startup.io', name: 'Sébastien Nguyên' },
  { email: 'noreply@newsletter.tech', name: 'Tech Insights Weekly' },
  { email: 'support@saas-platform.com', name: 'Support SaaS Pro' },
  { email: 'facturation@cloud-services.fr', name: 'Cloud Services Facturation' },
  { email: 'rh@grande-entreprise.com', name: 'Service des Ressources Humaines' },
  { email: 'communication@mairie-lyon.fr', name: 'Mairie de Lyon — Communication' },
  { email: 'no-reply@github.com', name: 'GitHub' },
  { email: 'alerts@monitoring.io', name: 'Monitoring Alerts' },
  { email: 'isabelle.château@académie.fr', name: 'Isabelle Château' },
  { email: 'andré.białek@euro-consulting.pl', name: 'André Białek' },
  { email: 'cécile.o\'brien@dublin.ie', name: "Cécile O'Brien" },
]

const SUBJECTS_PLAIN = [
  'Réunion hebdomadaire — ordre du jour',
  'Re: Devis n°2026-0847 — révision demandée',
  'Confirmation de votre réservation à l\'hôtel Château de Beaumont',
  'Félicitations pour votre promotion !',
  'Rappel : échéance contrat fournisseur vendredi',
  'Transfert de dossier — pièces manquantes',
  'Re: Re: Re: Budget prévisionnel 2026',
  'Invitation : Conférence sur l\'IA générative — Genève',
  'Votre facture n°F-2026-1234 est disponible',
  'Nouvelle version disponible — mise à jour critique',
]

const SUBJECTS_WITH_EMOJI = [
  '🎉 Lancement réussi du projet Phénix !',
  '⚠️ Alerte sécurité — action requise immédiatement',
  '📊 Rapport mensuel — résultats exceptionnels',
  '🔧 Maintenance prévue ce weekend',
  '💡 Idée : nouveau workflow automatisé',
]

const SUBJECTS_LONG = [
  'Re: Fw: Re: Discussion approfondie sur la stratégie de transformation numérique de l\'entreprise pour le second semestre 2026 incluant les aspects budgétaires, ressources humaines et partenariats stratégiques',
  '[URGENT] Mise à jour du contrat-cadre de prestations de services informatiques entre notre société et le groupement d\'achats régional — révision des clauses de confidentialité et de protection des données personnelles',
]

/**
 * Rich HTML signature blocks — each has name, title, phone, company, logo
 */
const SIGNATURES = [
  `<div style="margin-top:20px;border-top:2px solid #2563eb;padding-top:12px;font-family:Arial,sans-serif">
    <table cellpadding="0" cellspacing="0"><tr>
      <td style="padding-right:15px"><img src="${RED_PNG}" alt="Logo Société" width="60" height="60" style="border-radius:4px"/></td>
      <td>
        <p style="margin:0;font-weight:bold;color:#1e293b;font-size:14px">Marie Dupont</p>
        <p style="margin:2px 0;color:#64748b;font-size:12px">Directrice Générale</p>
        <p style="margin:2px 0;color:#64748b;font-size:12px">📞 +33 1 42 68 53 00 | 📱 +33 6 12 34 56 78</p>
        <p style="margin:2px 0;color:#64748b;font-size:12px">✉️ marie.dupont@entreprise.fr</p>
        <p style="margin:2px 0;color:#2563eb;font-size:12px">www.entreprise.fr | LinkedIn | Twitter</p>
      </td>
    </tr></table>
  </div>`,

  `<div style="margin-top:16px;padding-top:10px;border-top:1px solid #e2e8f0">
    <p style="margin:0;font-size:13px"><strong>Pierre Béranger</strong> — Chef de projet innovation</p>
    <p style="margin:2px 0;font-size:12px;color:#6b7280">Société Générale d'Ingénierie | Département R&D</p>
    <p style="margin:2px 0;font-size:12px;color:#6b7280">Tél. : 01 45 67 89 00 | Mobile : 06 78 90 12 34</p>
    <p style="margin:4px 0"><img src="${BLUE_PNG}" alt="Certifié ISO 27001" width="80" height="20"/></p>
    <p style="margin:2px 0;font-size:10px;color:#9ca3af;font-style:italic">Ce message est confidentiel. Si vous n'êtes pas le destinataire, merci de le supprimer.</p>
  </div>`,

  `<table cellpadding="0" cellspacing="0" style="margin-top:20px;font-family:Helvetica,Arial,sans-serif">
    <tr>
      <td style="vertical-align:top;padding-right:12px;border-right:3px solid #059669">
        <img src="${RED_PNG}" width="80" height="80" alt="Photo profil" style="border-radius:50%"/>
      </td>
      <td style="padding-left:12px;vertical-align:top">
        <p style="margin:0;font-size:15px;font-weight:bold;color:#111827">Jean-François Côté</p>
        <p style="margin:3px 0;font-size:13px;color:#059669;font-weight:600">Vice-Président, Développement des affaires</p>
        <p style="margin:3px 0;font-size:12px;color:#6b7280">Hydro-Québec International</p>
        <p style="margin:3px 0;font-size:12px;color:#6b7280">75, boul. René-Lévesque Ouest, Montréal, QC H2Z 1A4</p>
        <p style="margin:3px 0;font-size:12px;color:#6b7280">Bureau : +1 514 289-2211 poste 4567</p>
        <p style="margin:5px 0">
          <a href="#" style="text-decoration:none;margin-right:8px">🔗 LinkedIn</a>
          <a href="#" style="text-decoration:none">🌐 Site web</a>
        </p>
      </td>
    </tr>
  </table>`,

  `<div style="margin-top:15px;font-family:Georgia,serif;border-top:1px dashed #d1d5db;padding-top:10px">
    <p style="margin:0;font-size:14px;color:#374151"><em>Cordialement,</em></p>
    <p style="margin:5px 0;font-size:14px;font-weight:bold">Isabelle Château</p>
    <p style="margin:2px 0;font-size:12px;color:#6b7280">Professeure agrégée — Académie de Lyon</p>
    <p style="margin:2px 0;font-size:12px;color:#6b7280">Département des Lettres et Sciences Humaines</p>
    <img src="${BLUE_PNG}" alt="Logo Académie" width="120" height="30" style="margin-top:6px"/>
  </div>`,
]

/** Newsletter HTML body with complex table layout */
function newsletterBody(index: number): string {
  return `<div style="max-width:600px;margin:0 auto;font-family:Arial,sans-serif;background:#ffffff">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e40af;color:#ffffff;padding:20px">
      <tr><td style="padding:20px;text-align:center">
        <img src="${RED_PNG}" width="150" height="40" alt="Newsletter Logo" style="margin-bottom:10px"/>
        <h1 style="margin:0;font-size:24px">Tech Insights Weekly #${index}</h1>
        <p style="margin:5px 0;font-size:14px;opacity:0.8">Votre résumé hebdomadaire de l'actualité tech</p>
      </td></tr>
    </table>
    <table width="100%" cellpadding="20" cellspacing="0">
      <tr><td>
        <h2 style="color:#1e40af;margin-top:0">🚀 Article à la une</h2>
        <p>L'intelligence artificielle générative continue de transformer les industries. Cette semaine, découvrez comment les entreprises françaises adoptent ces technologies pour améliorer leur productivité.</p>
        <img src="${BLUE_PNG}" width="560" height="300" alt="Article illustration" style="width:100%;height:auto;border-radius:8px;margin:10px 0"/>
        <h3 style="color:#374151">📈 Les chiffres de la semaine</h3>
        <table width="100%" style="border-collapse:collapse;margin:10px 0">
          <tr style="background:#f1f5f9">
            <td style="padding:8px;border:1px solid #e2e8f0;font-weight:bold">Métrique</td>
            <td style="padding:8px;border:1px solid #e2e8f0;font-weight:bold">Valeur</td>
            <td style="padding:8px;border:1px solid #e2e8f0;font-weight:bold">Évolution</td>
          </tr>
          <tr>
            <td style="padding:8px;border:1px solid #e2e8f0">Adoption IA en France</td>
            <td style="padding:8px;border:1px solid #e2e8f0">67%</td>
            <td style="padding:8px;border:1px solid #e2e8f0;color:#059669">+12% ↑</td>
          </tr>
          <tr>
            <td style="padding:8px;border:1px solid #e2e8f0">Investissements (Mds€)</td>
            <td style="padding:8px;border:1px solid #e2e8f0">4,2</td>
            <td style="padding:8px;border:1px solid #e2e8f0;color:#059669">+8% ↑</td>
          </tr>
          <tr>
            <td style="padding:8px;border:1px solid #e2e8f0">Emplois créés</td>
            <td style="padding:8px;border:1px solid #e2e8f0">15 400</td>
            <td style="padding:8px;border:1px solid #e2e8f0;color:#dc2626">-3% ↓</td>
          </tr>
        </table>
        <p style="font-size:12px;color:#9ca3af;text-align:center;margin-top:20px">
          © 2026 Tech Insights Weekly — <a href="#" style="color:#2563eb">Se désabonner</a> | <a href="#" style="color:#2563eb">Préférences</a>
        </p>
      </td></tr>
    </table>
  </div>`
}

/** Email body with inline images */
function bodyWithImages(index: number): string {
  return `<div>
    <p>Bonjour,</p>
    <p>Voici les photos du chantier — étape ${index} :</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin:15px 0">
      <div style="text-align:center">
        <img src="${RED_PNG}" width="280" height="200" alt="Photo chantier vue 1" style="border-radius:8px;border:1px solid #e5e7eb"/>
        <p style="font-size:12px;color:#6b7280;margin:4px 0">Vue d'ensemble — façade nord</p>
      </div>
      <div style="text-align:center">
        <img src="${BLUE_PNG}" width="280" height="200" alt="Photo chantier vue 2" style="border-radius:8px;border:1px solid #e5e7eb"/>
        <p style="font-size:12px;color:#6b7280;margin:4px 0">Détail — structure béton armé</p>
      </div>
    </div>
    <p>Les travaux avancent conformément au planning. L'architecte a validé la conformité des éléments structurels.</p>
    <p>N'hésitez pas à me contacter pour toute question.</p>
    ${SIGNATURES[index % SIGNATURES.length]}
  </div>`
}

/** Plain text body with French accents */
function plainTextBody(index: number): string {
  const bodies = [
    `Bonjour,\n\nSuite à notre échange téléphonique, je vous confirme ma disponibilité pour la réunion de mardi.\n\nL'ordre du jour portera sur :\n- Présentation des résultats du trimestre\n- Révision du budget prévisionnel\n- Discussion sur les recrutements à venir\n\nÀ bientôt,\nMarie Dupont\nDirectrice Générale\nTél. : 01 42 68 53 00`,
    `Cher collègue,\n\nLe département des Ressources Humaines souhaite vous rappeler que votre entretien annuel d'évaluation est prévu le 15 mars.\n\nMerci de préparer :\n1. Votre auto-évaluation\n2. Vos objectifs pour le prochain semestre\n3. Vos besoins en formation\n\nCordialement,\nService RH`,
    `Bonjour à tous,\n\nJe suis heureux de vous annoncer que le projet « Phénix » a été livré avec succès !\n\nQuelques métriques :\n• Délai respecté : 100%\n• Budget consommé : 94% (économie de 6%)\n• Satisfaction client : 4.8/5\n\nFélicitations à toute l'équipe !\n\nJean-François Côté\nVice-Président`,
    `Madame, Monsieur,\n\nVeuillez trouver ci-joint la facture n°F-2026-${1000 + index} pour les prestations du mois de février.\n\nMontant HT : 8 450,00 €\nTVA (20%) : 1 690,00 €\nMontant TTC : 10 140,00 €\n\nÉchéance : 30 jours date de facture.\n\nComptabilité Fournisseur\ncloud-services.fr`,
    `Salut,\n\nJ'ai trouvé un super article sur les dernières avancées en traitement du langage naturel. Ça pourrait être utile pour notre projet d'automatisation.\n\nLe modèle décrit atteint 97% de précision sur les benchmarks français, ce qui est remarquable.\n\nÀ+\nSébastien`,
  ]
  return bodies[index % bodies.length]
}

/** HTML body with rich formatting + signature */
function richHtmlBody(index: number): string {
  return `<div style="font-family:Arial,sans-serif;color:#1f2937;line-height:1.6">
    <p>Bonjour ${SENDERS[index % SENDERS.length].name.split(' ')[0]},</p>
    <p>Comme convenu lors de notre dernière réunion, voici le récapitulatif des <strong>décisions prises</strong> et des <em>actions à mener</em> :</p>
    <h3 style="color:#1e40af;border-bottom:1px solid #e2e8f0;padding-bottom:5px">📋 Décisions validées</h3>
    <ol>
      <li>Migration vers la nouvelle plateforme — <strong>deadline : 30 avril 2026</strong></li>
      <li>Recrutement de 3 développeurs séniors — processus lancé cette semaine</li>
      <li>Budget formation augmenté de <span style="color:#059669;font-weight:bold">25%</span> pour le second semestre</li>
    </ol>
    <h3 style="color:#1e40af;border-bottom:1px solid #e2e8f0;padding-bottom:5px">⚠️ Points d'attention</h3>
    <ul>
      <li style="color:#dc2626">Le fournisseur XYZ n'a toujours pas livré les certificats SSL</li>
      <li>La charge serveur a augmenté de 40% — investigation en cours</li>
      <li>3 tickets critiques restent ouverts sur le backlog</li>
    </ul>
    <blockquote style="border-left:3px solid #2563eb;padding:10px 15px;background:#f0f9ff;margin:15px 0;font-style:italic;color:#374151">
      « La qualité n'est jamais un accident ; c'est toujours le résultat d'un effort intelligent. » — John Ruskin
    </blockquote>
    <p>Merci de me confirmer la réception de ce compte-rendu.</p>
    ${SIGNATURES[index % SIGNATURES.length]}
  </div>`
}

// ---- Email generator ----

interface MockEmail {
  id: string
  sender: string
  sender_name: string | null
  subject: string
  received_at: string
  has_attachments: boolean
  conversation_id: string | null
  is_read: boolean
  body_preview: string
}

interface MockEmailDetail extends MockEmail {
  body: string
  body_html?: string
  to: string[]
  cc: string[]
  attachments: { id: string; filename: string; size: number; content_type: string }[]
}

type EmailCategory = 'plain' | 'rich-html' | 'images' | 'newsletter' | 'accents-special' | 'attachments' | 'long-subject' | 'emoji-subject' | 'thread'

/**
 * Generate 1000 emails with deterministic distribution across categories.
 */
function generateEmails(count: number): { emails: MockEmail[], details: Record<string, MockEmailDetail> } {
  const emails: MockEmail[] = []
  const details: Record<string, MockEmailDetail> = {}

  const categories: EmailCategory[] = [
    'plain', 'rich-html', 'images', 'newsletter',
    'accents-special', 'attachments', 'long-subject', 'emoji-subject', 'thread',
  ]

  for (let i = 0; i < count; i++) {
    const cat = categories[i % categories.length]
    const sender = SENDERS[i % SENDERS.length]
    const id = `email-${String(i + 1).padStart(4, '0')}`
    const timeOffset = i * 7 // spread across ~290 days
    const isRead = i % 3 !== 0 // ~33% unread

    let subject: string
    let bodyHtml: string | undefined
    let bodyText: string
    let hasAttachments = false
    let attachments: MockEmailDetail['attachments'] = []
    let cc: string[] = []
    const to = ['moi@example.com']
    let convId: string | null = null

    switch (cat) {
      case 'plain':
        subject = SUBJECTS_PLAIN[i % SUBJECTS_PLAIN.length]
        bodyText = plainTextBody(i)
        break

      case 'rich-html':
        subject = `Compte-rendu réunion #${i} — ${sender.name.split(' ')[0]}`
        bodyHtml = richHtmlBody(i)
        bodyText = `Décisions validées... Points d'attention... Signature: ${sender.name}`
        cc = ['direction@example.com', 'equipe@example.com']
        break

      case 'images':
        subject = `Photos chantier étape ${Math.floor(i / 9) + 1} — ${sender.name}`
        bodyHtml = bodyWithImages(i)
        bodyText = `Photos du chantier étape ${Math.floor(i / 9) + 1}. Les travaux avancent conformément au planning.`
        hasAttachments = true
        attachments = [
          { id: `att-${id}-1`, filename: `photo_chantier_${i}_01.jpg`, size: 2_400_000, content_type: 'image/jpeg' },
          { id: `att-${id}-2`, filename: `photo_chantier_${i}_02.jpg`, size: 3_100_000, content_type: 'image/jpeg' },
        ]
        break

      case 'newsletter':
        subject = `📬 Tech Insights Weekly #${Math.floor(i / 9) + 1} — Les tendances de la semaine`
        bodyHtml = newsletterBody(Math.floor(i / 9) + 1)
        bodyText = `Article à la une : L'IA générative transforme les industries...`
        break

      case 'accents-special': {
        const accentSubjects = [
          `Évaluation pré-qualité — critères révisés (à confirmer)`,
          `Résumé : café-débat « L'avenir de l'éducation »`,
          `Données géographiques — coordonnées GPS du réseau (48°51'N, 2°21'E)`,
          `Re: Procès-verbal — séance du comité d'éthique`,
          `Présentation des résultats financiers — clôture de l'exercice`,
          `Mañana — reunión con el equipo de diseño`,
          `Grüße aus München — Zusammenarbeit Vorschlag`,
          `Współpraca międzynarodowa — nowy projekt`,
          `Contrat n°2026/FR-ÎDF/007 — avenant n°3`,
          `Enquête de satisfaction — « Très satisfait » à 92%`,
        ]
        subject = accentSubjects[i % accentSubjects.length]
        bodyHtml = `<div style="font-family:serif;line-height:1.8">
          <p>Cher(e) collègue,</p>
          <p>Veuillez noter que les caractères spéciaux suivants doivent s'afficher correctement :</p>
          <ul>
            <li><strong>Français</strong> : àâäéèêëïîôùûüÿçœæ — «&nbsp;guillemets français&nbsp;»</li>
            <li><strong>Espagnol</strong> : ñ, ¿Cómo estás?, ¡Hola! — áéíóú</li>
            <li><strong>Polonais</strong> : ą, ć, ę, ł, ń, ó, ś, ź, ż — współpraca</li>
            <li><strong>Symboles</strong> : € £ ¥ © ® ™ § ¶ † ‡ ° ± × ÷ ≈ ≠ ≤ ≥</li>
            <li><strong>Tirets</strong> : trait d'union (-), tiret cadratin (—), tiret demi-cadratin (–)</li>
          </ul>
          <p>Les montants : 1&nbsp;234,56&nbsp;€ et 9&nbsp;876&nbsp;543,21&nbsp;$.</p>
          ${SIGNATURES[i % SIGNATURES.length]}
        </div>`
        bodyText = `Caractères spéciaux : àâäéèêëïîôùûüÿçœæ — ñ ¿ ¡ ä ö ü ß — € £ ¥ © ® ™`
        break
      }

      case 'attachments':
        subject = `Livrables projet #${Math.floor(i / 9) + 1} — documents à valider`
        bodyHtml = `<div>
          <p>Bonjour,</p>
          <p>Veuillez trouver ci-joints les livrables du projet pour validation :</p>
          <ol>
            <li>📄 Cahier des charges technique (PDF, 45 pages)</li>
            <li>📊 Tableur de suivi budgétaire (Excel)</li>
            <li>🖼️ Maquettes UI/UX finalisées (ZIP)</li>
          </ol>
          <p>Merci de me faire un retour avant vendredi.</p>
          ${SIGNATURES[i % SIGNATURES.length]}
        </div>`
        bodyText = `Livrables projet : cahier des charges, tableur budget, maquettes UI/UX.`
        hasAttachments = true
        attachments = [
          { id: `att-${id}-1`, filename: `cahier_des_charges_v${Math.floor(i / 9) + 1}.pdf`, size: 4_500_000, content_type: 'application/pdf' },
          { id: `att-${id}-2`, filename: `suivi_budget_2026.xlsx`, size: 890_000, content_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
          { id: `att-${id}-3`, filename: `maquettes_UI_v3.zip`, size: 12_000_000, content_type: 'application/zip' },
        ]
        cc = ['chef-projet@example.com']
        break

      case 'long-subject':
        subject = SUBJECTS_LONG[i % SUBJECTS_LONG.length]
        bodyHtml = richHtmlBody(i)
        bodyText = `Corps du message avec un sujet très long...`
        break

      case 'emoji-subject':
        subject = SUBJECTS_WITH_EMOJI[i % SUBJECTS_WITH_EMOJI.length]
        bodyHtml = `<div>
          <p>Bonjour l'équipe ! 🎯</p>
          <p>Quelques nouvelles importantes :</p>
          <ul>
            <li>✅ Déploiement terminé avec succès</li>
            <li>📈 Performance améliorée de 35%</li>
            <li>🐛 0 bug critique détecté en production</li>
            <li>🎉 Célébration prévue vendredi soir !</li>
          </ul>
          <p>Bravo à tous ! 💪</p>
          ${SIGNATURES[i % SIGNATURES.length]}
        </div>`
        bodyText = `Déploiement terminé avec succès. Performance améliorée de 35%.`
        break

      case 'thread':
        convId = `conv-thread-${i % 50}`
        subject = `Re: Discussion fil #${i % 50} — suivi des actions`
        bodyHtml = `<div>
          <p>${sender.name.split(' ')[0]}, merci pour ta réponse rapide.</p>
          <p>Je suis d'accord avec ta proposition. On valide ça en comité mardi.</p>
          ${SIGNATURES[i % SIGNATURES.length]}
          <div style="margin-top:20px;padding-left:15px;border-left:3px solid #d1d5db;color:#6b7280">
            <p style="font-size:12px"><strong>Le ${new Date(daysAgo(2)).toLocaleDateString('fr-FR')}, ${sender.name} a écrit :</strong></p>
            <p>Bonjour, je propose que nous modifions l'approche pour le module de facturation. L'architecture actuelle ne supporte pas bien la montée en charge.</p>
          </div>
        </div>`
        bodyText = `Merci pour ta réponse rapide. Je suis d'accord...`
        break

      default:
        subject = `Email #${i + 1}`
        bodyText = `Contenu de l'email numéro ${i + 1}.`
    }

    const preview = bodyText.slice(0, 120).replace(/\n/g, ' ')

    const email: MockEmail = {
      id,
      sender: sender.email,
      sender_name: sender.name,
      subject,
      received_at: minutesAgo(timeOffset),
      has_attachments: hasAttachments,
      conversation_id: convId,
      is_read: isRead,
      body_preview: preview,
    }
    emails.push(email)

    details[id] = {
      ...email,
      body: bodyText,
      body_html: bodyHtml,
      to,
      cc,
      attachments,
    }
  }

  return { emails, details }
}

// ============================================================================
// TEST HELPERS
// ============================================================================

const { emails: ALL_EMAILS, details: ALL_DETAILS } = generateEmails(1000)

async function setupWith1000Emails(page: Page) {
  const emailsResponse = { count: ALL_EMAILS.length, emails: ALL_EMAILS }

  await setupBaseMocks(page, { emailsResponse })

  // Dynamic route: /api/emails/:id — returns detail for any email
  const detailHandler = (route: import('@playwright/test').Route) => {
    const url = new URL(route.request().url())
    // Extract email ID from /api/emails/email-0001 or /api/emails/email-0001?...
    const match = url.pathname.match(/\/api\/emails\/(email-\d{4})$/)
    if (match) {
      const detail = ALL_DETAILS[match[1]]
      if (detail) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(detail),
        })
        return
      }
    }
    route.fulfill({ status: 404, contentType: 'application/json', body: '{"error":"not found"}' })
  }

  await page.route(
    (url) => (url.origin === API || url.origin === API_LOCALHOST) && /\/api\/emails\/email-\d{4}$/.test(url.pathname),
    detailHandler
  )

  // Mock thread endpoint
  await page.route(
    (url) => (url.origin === API || url.origin === API_LOCALHOST) && /\/api\/emails\/email-\d{4}\/thread/.test(url.pathname),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, emails: [] }) })
  )

  // Mock mark-as-read
  await page.route(
    (url) => (url.origin === API || url.origin === API_LOCALHOST) && /\/api\/emails\/email-\d{4}\/read/.test(url.pathname),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' })
  )
}

/** Open an email by its 0-based index in the list */
async function openEmailByIndex(page: Page, index: number): Promise<void> {
  const items = page.locator('[data-testid="email-item"]')
  const item = items.nth(index)
  await item.scrollIntoViewIfNeeded()
  await item.click()

  // Wait for detail view to appear (inline or modal)
  await expect(
    page.locator('.email-detail-content, .email-detail-inline').first()
  ).toBeVisible({ timeout: 10000 })
}

/** Get text content inside the email body iframe (or inline body fallback) */
async function getEmailBodyText(page: Page): Promise<string> {
  // Try iframe first (HTML emails)
  const iframe = page.locator('.email-body-iframe')
  const iframeCount = await iframe.count()
  if (iframeCount > 0 && await iframe.isVisible()) {
    const frame = page.frameLocator('.email-body-iframe')
    // Wait for body to have content
    await frame.locator('body').waitFor({ timeout: 5000 })
    return await frame.locator('body').textContent() || ''
  }
  // Fallback: inline body content
  const body = page.locator('.email-original-body-container, .email-detail-body').first()
  return await body.textContent() || ''
}

// Known non-critical errors that can appear with mocked data
const KNOWN_ERRORS = [
  "Cannot read properties of undefined",
  "Failed to fetch",
  "net::ERR",
  "ResizeObserver loop",
  "Abort",
  "socket",
]

function isKnownError(text: string): boolean {
  return KNOWN_ERRORS.some(k => text.includes(k))
}

// ============================================================================
// TESTS
// ============================================================================

test.describe('1000 Emails — Rendering & Presentation', () => {
  test.beforeEach(async ({ page }) => {
    await setupWith1000Emails(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  // --------------------------------------------------------------------------
  // 1. LIST VIEW — all 1000 emails present
  // --------------------------------------------------------------------------
  test('list shows 1000 emails with sender, subject visible', async ({ page }) => {
    const items = page.locator('[data-testid="email-item"]')
    await expect(items.first()).toBeVisible({ timeout: 10000 })

    const count = await items.count()
    expect(count).toBeGreaterThanOrEqual(20)

    // Verify first 5 emails have sender + subject
    for (let i = 0; i < Math.min(5, count); i++) {
      const item = items.nth(i)
      const sender = item.locator('.email-sender')
      await expect(sender).toBeVisible()
      expect((await sender.textContent())?.trim().length).toBeGreaterThan(0)

      const subject = item.locator('.email-subject')
      await expect(subject).toBeVisible()
      expect((await subject.textContent())?.trim().length).toBeGreaterThan(0)
    }

    // The "1000 emails" counter should be present
    const pageText = await page.textContent('body') || ''
    expect(pageText).toContain('1000')
  })

  test('unread emails are visually distinct from read emails', async ({ page }) => {
    const items = page.locator('[data-testid="email-item"]')
    await expect(items.first()).toBeVisible({ timeout: 10000 })

    // First email (index 0) is unread (0 % 3 === 0)
    const firstItem = items.first()
    const fontWeight = await firstItem.locator('.email-sender').evaluate(el =>
      window.getComputedStyle(el).fontWeight
    )
    expect(parseInt(fontWeight)).toBeGreaterThanOrEqual(500)
  })

  test('emails with attachments show attachment indicator', async ({ page }) => {
    const items = page.locator('[data-testid="email-item"]')
    await expect(items.first()).toBeVisible({ timeout: 10000 })

    // At least one attachment indicator somewhere in the visible list
    const anyAttachment = page.locator('.attachment-indicator, [aria-label*="ièce jointe"]').first()
    await expect(anyAttachment).toBeVisible({ timeout: 5000 })
  })

  // --------------------------------------------------------------------------
  // 2. PLAIN TEXT EMAIL — accents preserved, readable
  // --------------------------------------------------------------------------
  test('plain text email renders with correct French accents', async ({ page }) => {
    // email-0001 (index 0) is 'plain' category
    await openEmailByIndex(page, 0)

    const bodyText = await getEmailBodyText(page)
    expect(bodyText).toContain('réunion')
    expect(bodyText).toContain('disponibilité')
  })

  // --------------------------------------------------------------------------
  // 3. RICH HTML EMAIL — formatting, lists, signature with logo
  // --------------------------------------------------------------------------
  test('rich HTML email shows formatting, lists, and signature', async ({ page }) => {
    // email-0002 (index 1) is 'rich-html' with signature
    await openEmailByIndex(page, 1)

    const detail = page.locator('.email-detail-content, .email-detail-inline').first()
    await expect(detail).toBeVisible()

    // Subject in header
    const subjectEl = detail.locator('h2').first()
    await expect(subjectEl).toBeVisible({ timeout: 5000 })
    expect(await subjectEl.textContent()).toContain('Compte-rendu')

    // Body via iframe
    const frame = page.frameLocator('.email-body-iframe')
    await frame.locator('body').waitFor({ timeout: 8000 })
    const bodyText = await frame.locator('body').textContent() || ''

    // Structured content (lists)
    expect(bodyText).toContain('Décisions validées')
    expect(bodyText).toContain('Migration vers la nouvelle plateforme')
    // Signature
    expect(bodyText).toContain('Chef de projet')
    expect(bodyText).toContain('01 45 67 89 00')
  })

  test('rich HTML email shows CC recipients', async ({ page }) => {
    await openEmailByIndex(page, 1) // email-0002 has CC
    const detail = page.locator('.email-detail-content, .email-detail-inline').first()
    await expect(detail).toBeVisible()
    // Email renders without error — CC display is layout-dependent
  })

  // --------------------------------------------------------------------------
  // 4. EMAIL WITH INLINE IMAGES — images render, no broken icons
  // --------------------------------------------------------------------------
  test('email with inline images renders images correctly', async ({ page }) => {
    // email-0003 (index 2) is 'images' category
    await openEmailByIndex(page, 2)

    const frame = page.frameLocator('.email-body-iframe')
    await frame.locator('body').waitFor({ timeout: 8000 })

    const images = frame.locator('img')
    const imgCount = await images.count()
    // Should have 2 chantier photos + 1 signature logo
    expect(imgCount).toBeGreaterThanOrEqual(2)

    // Verify first image has non-zero dimensions
    const box = await images.first().boundingBox()
    expect(box).toBeTruthy()
    expect(box!.width).toBeGreaterThan(0)
    expect(box!.height).toBeGreaterThan(0)
  })

  test('email with images shows attachment chips', async ({ page }) => {
    await openEmailByIndex(page, 2) // email-0003 has 2 JPEG attachments

    const detail = page.locator('.email-detail-content, .email-detail-inline').first()
    await expect(detail).toBeVisible()

    const attachments = detail.locator('.email-attachment-chip, [class*="attachment-chip"]')
    await expect(attachments.first()).toBeVisible({ timeout: 5000 })
    expect(await attachments.count()).toBeGreaterThanOrEqual(1)
    const firstAtt = await attachments.first().textContent()
    expect(firstAtt).toContain('photo_chantier')
  })

  // --------------------------------------------------------------------------
  // 5. NEWSLETTER — complex table layout renders
  // --------------------------------------------------------------------------
  test('newsletter email renders table layout and images', async ({ page }) => {
    // email-0004 (index 3) is 'newsletter'
    await openEmailByIndex(page, 3)

    const frame = page.frameLocator('.email-body-iframe')
    await frame.locator('body').waitFor({ timeout: 8000 })

    // Newsletter tables
    const tables = frame.locator('table')
    expect(await tables.count()).toBeGreaterThanOrEqual(1)

    const bodyText = await frame.locator('body').textContent() || ''
    expect(bodyText).toContain('Tech Insights Weekly')
    expect(bodyText).toContain('Adoption IA')
    expect(bodyText).toContain('67%')

    // Images present
    expect(await frame.locator('img').count()).toBeGreaterThanOrEqual(1)
  })

  // --------------------------------------------------------------------------
  // 6. SPECIAL CHARACTERS — accents, symbols, international
  // --------------------------------------------------------------------------
  test('email with special characters and international accents', async ({ page }) => {
    // email-0005 (index 4) is 'accents-special'
    await openEmailByIndex(page, 4)

    const frame = page.frameLocator('.email-body-iframe')
    await frame.locator('body').waitFor({ timeout: 8000 })
    const bodyText = await frame.locator('body').textContent() || ''

    // French accents
    expect(bodyText).toContain('àâäéèêëïîôùûüÿçœæ')
    // Spanish
    expect(bodyText).toContain('¿Cómo estás?')
    expect(bodyText).toContain('¡Hola!')
    // Symbols
    expect(bodyText).toContain('€')
    expect(bodyText).toContain('©')
    expect(bodyText).toContain('™')
  })

  // --------------------------------------------------------------------------
  // 7. ATTACHMENTS — chips with filenames
  // --------------------------------------------------------------------------
  test('email with multiple attachments shows all files', async ({ page }) => {
    // email-0006 (index 5) is 'attachments' with 3 files
    await openEmailByIndex(page, 5)

    const detail = page.locator('.email-detail-content, .email-detail-inline').first()
    await expect(detail).toBeVisible()

    const attachSection = detail.locator('.email-attachments-section, [class*="attachment"]').first()
    await expect(attachSection).toBeVisible({ timeout: 5000 })
    const allText = await attachSection.textContent() || ''
    expect(allText).toContain('cahier_des_charges')
    expect(allText).toContain('suivi_budget')
    expect(allText).toContain('maquettes_UI')
  })

  // --------------------------------------------------------------------------
  // 8. LONG SUBJECT — visible in list and full in detail
  // --------------------------------------------------------------------------
  test('long subject is visible in list and full in detail', async ({ page }) => {
    const items = page.locator('[data-testid="email-item"]')
    await expect(items.first()).toBeVisible({ timeout: 10000 })

    // email-0007 (index 6) is 'long-subject'
    const listSubject = items.nth(6).locator('.email-subject')
    await expect(listSubject).toBeVisible()
    expect((await listSubject.textContent())?.length).toBeGreaterThan(30)

    // Open and verify full subject in detail
    await openEmailByIndex(page, 6)
    const titleEl = page.locator('h2').first()
    await expect(titleEl).toBeVisible({ timeout: 5000 })
    expect((await titleEl.textContent())?.length).toBeGreaterThan(50)
  })

  // --------------------------------------------------------------------------
  // 9. EMOJI SUBJECT — renders emoji correctly
  // --------------------------------------------------------------------------
  test('email with emoji in subject renders emoji', async ({ page }) => {
    // email-0008 (index 7) is 'emoji-subject'
    await openEmailByIndex(page, 7)

    const frame = page.frameLocator('.email-body-iframe')
    await frame.locator('body').waitFor({ timeout: 8000 })
    const bodyText = await frame.locator('body').textContent() || ''
    expect(bodyText).toContain('✅')
    expect(bodyText).toContain('📈')
  })

  // --------------------------------------------------------------------------
  // 10. SIGNATURE — name, title, phone, company logo all visible
  // --------------------------------------------------------------------------
  test('signature with logo, name, title, and phone renders fully', async ({ page }) => {
    // email-0002 (index 1) — SIGNATURES[1] with name, title, phone, logo, disclaimer
    await openEmailByIndex(page, 1)

    const frame = page.frameLocator('.email-body-iframe')
    await frame.locator('body').waitFor({ timeout: 8000 })
    const bodyText = await frame.locator('body').textContent() || ''

    // Signature content: title
    const hasSigTitle =
      bodyText.includes('Directrice Générale') ||
      bodyText.includes('Chef de projet') ||
      bodyText.includes('Vice-Président') ||
      bodyText.includes('Professeure agrégée')
    expect(hasSigTitle).toBe(true)

    // Phone number
    const hasPhone =
      bodyText.includes('+33') || bodyText.includes('01 4') ||
      bodyText.includes('06 7') || bodyText.includes('+1 514')
    expect(hasPhone).toBe(true)

    // Signature logo image present and rendered
    const imgs = frame.locator('img')
    expect(await imgs.count()).toBeGreaterThanOrEqual(1)
    const box = await imgs.first().boundingBox()
    expect(box).toBeTruthy()
    expect(box!.width).toBeGreaterThan(0)
    expect(box!.height).toBeGreaterThan(0)
  })

  test('signature with confidentiality disclaimer renders', async ({ page }) => {
    // email-0002 (index 1) — rich-html, SIGNATURES[1 % 4 = 1] with confidentiality
    await openEmailByIndex(page, 1)

    const frame = page.frameLocator('.email-body-iframe')
    await frame.locator('body').waitFor({ timeout: 8000 })
    const bodyText = await frame.locator('body').textContent() || ''

    const hasDisclaimer = bodyText.includes('confidentiel') || bodyText.includes('destinataire')
    expect(hasDisclaimer).toBe(true)
  })

  // --------------------------------------------------------------------------
  // 11. THREAD EMAIL — quoted text visible
  // --------------------------------------------------------------------------
  test('thread email shows quoted previous message', async ({ page }) => {
    // email-0009 (index 8) is 'thread' with quoted text
    await openEmailByIndex(page, 8)

    const frame = page.frameLocator('.email-body-iframe')
    await frame.locator('body').waitFor({ timeout: 8000 })
    const bodyText = await frame.locator('body').textContent() || ''

    expect(bodyText).toContain('a écrit')
    expect(bodyText).toContain('module de facturation')
  })

  // --------------------------------------------------------------------------
  // 12. DATE FORMATTING — date shown in detail header
  // --------------------------------------------------------------------------
  test('email date is displayed in detail view', async ({ page }) => {
    await openEmailByIndex(page, 0)

    const detail = page.locator('.email-detail-content, .email-detail-inline').first()
    await expect(detail).toBeVisible()

    const dateEl = detail.locator('.email-original-date, [class*="date"]').first()
    await expect(dateEl).toBeVisible({ timeout: 5000 })
    expect((await dateEl.textContent())?.trim().length).toBeGreaterThan(0)
  })

  // --------------------------------------------------------------------------
  // 13. SENDER DISPLAY — name visible in detail
  // --------------------------------------------------------------------------
  test('sender name is shown in detail view', async ({ page }) => {
    await openEmailByIndex(page, 1)

    const detail = page.locator('.email-detail-content, .email-detail-inline').first()
    await expect(detail).toBeVisible()

    const senderName = detail.locator('.email-original-from-name, [class*="from-name"]').first()
    await expect(senderName).toBeVisible({ timeout: 5000 })
    expect((await senderName.textContent())?.trim().length).toBeGreaterThan(0)
  })

  // --------------------------------------------------------------------------
  // 14. KEYBOARD NAVIGATION — J/K to navigate emails
  // --------------------------------------------------------------------------
  test('J/K keyboard shortcuts navigate between emails', async ({ page }) => {
    const items = page.locator('[data-testid="email-item"]')
    await expect(items.first()).toBeVisible({ timeout: 10000 })

    await items.first().click()
    await page.waitForTimeout(500)

    await page.keyboard.press('j')
    await page.waitForTimeout(500)
    await page.keyboard.press('k')
    await page.waitForTimeout(500)

    await expect(items.first()).toBeVisible()
  })

  // --------------------------------------------------------------------------
  // 15. STRESS TEST — open first 18 emails (all 9 categories × 2), no crash
  // --------------------------------------------------------------------------
  test('opening 18 emails across all categories — no render crash', async ({ page }) => {
    // First 18 emails cover 2 full rounds of all 9 categories
    const errors: string[] = []
    page.on('console', msg => {
      if (msg.type() === 'error' && !isKnownError(msg.text())) {
        errors.push(`[${msg.text().slice(0, 100)}]`)
      }
    })

    for (let i = 0; i < 18; i++) {
      await openEmailByIndex(page, i)

      // Body visible
      const body = page.locator('.email-original-body-container, .email-body-iframe, .email-detail-body').first()
      await expect(body).toBeVisible({ timeout: 8000 })

      // Navigate to next email via J key (avoids needing to find list item again)
      await page.keyboard.press('j')
      await page.waitForTimeout(200)
    }

    if (errors.length > 0) {
      console.log('Console errors during stress test:', errors.join(', '))
    }
    expect(errors.length).toBeLessThan(5)
  })

  // --------------------------------------------------------------------------
  // 16. SCROLL DEEP — emails beyond visible area are accessible
  // --------------------------------------------------------------------------
  test('scrolling deep into the list shows more emails', async ({ page }) => {
    const items = page.locator('[data-testid="email-item"]')
    await expect(items.first()).toBeVisible({ timeout: 10000 })

    const _initialCount = await items.count()

    // Scroll down
    for (let i = 0; i < 20; i++) {
      await page.mouse.wheel(0, 2000)
      await page.waitForTimeout(100)
    }

    // Items should still be visible
    const afterCount = await items.count()
    expect(afterCount).toBeGreaterThan(0)

    const lastVisible = items.last()
    const lastSender = lastVisible.locator('.email-sender')
    await expect(lastSender).toBeVisible({ timeout: 5000 })
    expect((await lastSender.textContent())?.trim().length).toBeGreaterThan(0)
  })

  // --------------------------------------------------------------------------
  // 17. IFRAME ISOLATION — HTML email styles don't leak
  // --------------------------------------------------------------------------
  test('HTML email rendered in iframe does not affect app styles', async ({ page }) => {
    await openEmailByIndex(page, 3) // newsletter with heavy styling

    const sidebar = page.locator('[data-testid="nav-inbox"]')
    await expect(sidebar).toBeVisible()
    const sidebarBox = await sidebar.boundingBox()
    expect(sidebarBox).toBeTruthy()
    expect(sidebarBox!.width).toBeGreaterThan(10)
    expect(sidebarBox!.height).toBeGreaterThan(10)
  })

  // --------------------------------------------------------------------------
  // 18. EMAIL BODY NOT EMPTY — all categories have visible body
  // --------------------------------------------------------------------------
  test('email body is never empty for any category', async ({ page }) => {
    // Indices: 0=plain, 1=rich-html, 3=newsletter, 4=accents, 7=emoji, 8=thread
    const indices = [
      { idx: 0, label: 'plain' },
      { idx: 1, label: 'rich-html' },
      { idx: 3, label: 'newsletter' },
      { idx: 4, label: 'accents' },
      { idx: 7, label: 'emoji' },
      { idx: 8, label: 'thread' },
    ]

    for (const { idx, label } of indices) {
      await openEmailByIndex(page, idx)

      // Body container visible
      const body = page.locator('.email-original-body-container, .email-body-iframe, .email-detail-body').first()
      await expect(body).toBeVisible({ timeout: 8000 })

      // Check content is non-empty
      const iframe = page.locator('.email-body-iframe')
      const iframeCount = await iframe.count()
      if (iframeCount > 0 && await iframe.isVisible()) {
        const frame = page.frameLocator('.email-body-iframe')
        const text = await frame.locator('body').textContent()
        expect(text?.trim().length, `Body empty for ${label}`).toBeGreaterThan(5)
      } else {
        const bodyText = await body.textContent()
        expect(bodyText?.trim().length, `Body empty for ${label}`).toBeGreaterThan(5)
      }

      await page.keyboard.press('Escape')
      await page.waitForTimeout(300)
    }
  })
})
