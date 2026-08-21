# Feature — Timeline Contact

> Prototype : `prototype-timeline.html` à la racine du projet

## Objectif

Permettre de retrouver tous les échanges avec un contact spécifique sur un sujet donné, ordonnés chronologiquement, pour constituer un dossier défensif (litige, impayé, contestation, etc.).

## Cas d'usage principal

> "Je dois retrouver tous les emails avec un client qui m'a causé du tort, sur un sujet précis, pour défendre ma position."

## Interface

### Header de recherche
- Champ **Contact** — sélecteur avec avatar + nom + email (autocomplete depuis `GET /api/emails/search/suggestions`)
- Champ **Sujet / Mots-clés** — texte libre (mappe sur `subject:` + `body:` filters)
- **Plage de dates** — `after:` / `before:` (date picker)
- Compteur `N emails trouvés`
- Bouton **Exporter PDF**
- Toggle **Vue Timeline / Vue Liste**

### Vue Timeline (défaut)
- Épine centrale verticale
- Emails alternés gauche (envoyés) / droite (reçus)
- Marqueurs de mois
- Card par email :
  - Badge directionnel : `→ Envoyé` (bleu) / `← Reçu` (violet)
  - Date + heure (format `DM Mono`)
  - Sujet + extrait (2 lignes)
  - Tags : pièce jointe, lu, répondu, sans réponse, point clé
  - Bouton "Voir l'email" → modal contenu complet

### Vue Liste (toggle)
- Tableau trié par date croissante
- Colonnes : Direction · Date · Sujet · PJ · Action

### Panneau latéral — Résumé du dossier
- Stats : emails reçus / envoyés / avec PJ / total / première interaction
- Histogramme de densité par mois
- **Points clés détectés** (3 bullets, codes couleur) :
  - Amber — accord/engagement mentionné
  - Rouge — délai contesté / clause invoquée
  - Bleu — relance sans réponse

## Implémentation technique

### Backend

**Modification à `GET /api/emails/search`** — ajouter paramètre `sort`:
```
sort=date_asc | date_desc | relevance (défaut actuel)
```

**Nouveau endpoint** `GET /api/emails/contact-timeline` :
```
?from=<email>&q=<keywords>&after=<date>&before=<date>&account_id=<id>
```
Retourne :
```json
{
  "emails": [...],         // triés par date asc
  "stats": {
    "received": 14,
    "sent": 9,
    "with_attachments": 7,
    "first_date": "2025-01-15"
  },
  "density": {             // nb emails par mois
    "2025-01": 3,
    "2025-03": 6, ...
  }
}
```

### Frontend

Nouveau composant `ContactTimelineView.tsx` :
- Réutilise `SmartSearchBar` pour les filtres
- Nouveau composant `TimelineSpine.tsx` (épine + cards alternées)
- Nouveau composant `DossierSidebar.tsx` (stats + histogramme + points clés)
- `EmailDetailModal` existant pour le contenu complet

Accès : bouton "Timeline" dans `SmartSearchBar` quand filtre `from:` présent, ou entrée dédiée dans la sidebar nav.

## Design

- Dark theme, glassmorphism
- Polices : Syne (titres), DM Mono (dates/codes), DM Sans (corps)
- Couleurs : `#6366f1` indigo, `#3b82f6` bleu (envoyé), `#8b5cf6` violet (reçu), `#f59e0b` amber (alertes)
- Hover cards : glow coloré selon direction
- Animation : `modalIn` cubic-bezier sur ouverture modal

## Ce qui existe déjà (réutilisable)

| Besoin | Existant |
|--------|----------|
| Filtre `from:` | `QueryParser.parse_advanced()` |
| Filtre `subject:` + `body:` | FTS5 SQLite |
| Filtre `after:` / `before:` | SQL date range |
| Modal contenu email | `EmailDetailModal.tsx` |
| Autocomplete contacts | `GET /api/emails/search/suggestions` |
| Export | À créer |

## Ce qu'il faut créer

- [ ] Param `sort=date_asc` dans `SearchService.search_emails()`
- [ ] Endpoint `/api/emails/contact-timeline` avec stats + densité
- [ ] Composant `ContactTimelineView.tsx`
- [ ] Composant `TimelineSpine.tsx`
- [ ] Composant `DossierSidebar.tsx`
- [ ] Export PDF (jsPDF ou endpoint backend)
