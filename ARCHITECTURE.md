# Architecture - Agentys

> **Dernière mise à jour** : 2026-03-23
> **Tests** : 361 fichiers de test Python + 91 specs Playwright E2E
> **Approche** : TDD (Test-Driven Development)

## Vue d'ensemble

Agentys est une **app desktop Tauri (React/TypeScript)** connectée à un **backend Python Flask**, respectant les principes de la **Clean Architecture**. Le frontend gère l'interface utilisateur, le backend gère le traitement IA et la communication email.

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frameworks                               │
│   (Flask, SQLite, Gmail API, Anthropic SDK, Prometheus...)      │
├─────────────────────────────────────────────────────────────────┤
│                     Interface Adapters                           │
│         (ClaudeAdapter, GmailAdapter, FCMAdapter...)            │
├─────────────────────────────────────────────────────────────────┤
│                       Use Cases                                  │
│    (DraftEmailUseCase, CritiqueEmailUseCase, ProcessEmail...)   │
├─────────────────────────────────────────────────────────────────┤
│                        Entities                                  │
│              (Email, Draft, Critique, TokenUsage...)            │
└─────────────────────────────────────────────────────────────────┘
```

**Dependency Rule** : Les dépendances pointent toujours vers l'intérieur. Les couches externes (adapters, frameworks) dépendent des couches internes (entities, use cases), jamais l'inverse.

---

## Structure des répertoires

```
agentys/
├── app/
│   ├── domain/                    # Couche Entities (centre)
│   │   ├── entities/              # Objets métier purs
│   │   │   ├── email.py           # Email, Thread
│   │   │   ├── draft.py           # Draft, Critique, ProcessingResult, DraftStatus
│   │   │   ├── draft_input.py     # DraftInput, DraftInputTone, CompletedDraft
│   │   │   ├── token_usage.py     # TokenUsage
│   │   │   ├── push_notification.py  # DeviceToken, PushNotification, PushNotificationRecord
│   │   │   ├── wizard_config.py   # WizardConfig, AgentActivation, ConfigPack
│   │   │   ├── marketplace.py     # MarketplaceAgent, Publisher, AgentPack, AgentReview
│   │   │   ├── fine_tuning.py     # UserCorrection, CorrectionPattern, ImprovementModel
│   │   │   ├── mobile_companion.py # MobileSession, MobileSyncState, MobileAnalyticsEvent
│   │   │   ├── classification.py  # EmailClassification, ClassificationResult
│   │   │   ├── learning.py        # LearnedPattern, PromptAdjustment, LearningInsights, LearningStats
│   │   │   ├── realtime_edit.py   # EditSession, TextChange, EditTrigger, Suggestion, TextDiff
│   │   │   ├── analytics.py       # QualityScore, HumanEdit, PerformanceMetrics, AIVsHumanComparison
│   │   │   ├── draft_history.py   # DraftRecord (historique brouillons)
│   │   │   ├── followup.py        # SentEmail, FollowupSchedule, FollowupStats, FollowupStatus
│   │   │   ├── commitment.py      # Commitment, CommitmentStatus (suivi engagements)
│   │   │   ├── email_template.py  # EmailTemplate, TemplateMatch, TemplateVariables
│   │   │   ├── sensitive_data.py  # SensitiveDataDetection, SensitiveDataItem, SensitiveDataType
│   │   │   ├── anonymization.py   # AnonymizedToken, AnonymizedResult, SecureAnonymizedData
│   │   │   └── permission.py      # Permission, Role, Credential (RBAC)
│   │   ├── ports/                 # Interfaces abstraites (contrats)
│   │   │   ├── llm_port.py        # Interface LLMPort, LLMResponse
│   │   │   ├── email_template_port.py # Interface EmailTemplateStorePort
│   │   │   ├── email_port.py      # Interface EmailPort
│   │   │   ├── time_provider.py   # Interface TimeProvider (Clock Pattern)
│   │   │   ├── notification_port.py  # Interface NotificationPort
│   │   │   ├── device_store_port.py  # Interface DeviceStorePort
│   │   │   ├── wizard_config_port.py # Interface WizardConfigPort
│   │   │   ├── marketplace_port.py   # Interface MarketplacePort
│   │   │   ├── fine_tuning_port.py   # Interface FineTuningPort
│   │   │   ├── mobile_companion_port.py # Interface MobileCompanionPort
│   │   │   ├── classification_port.py # Interface ClassificationPort
│   │   │   ├── learning_port.py   # Interface LearningPatternStorePort, AdjustmentStorePort
│   │   │   ├── realtime_edit_port.py # Interface EditSessionStorePort, RealTimeEditPort
│   │   │   ├── analytics_port.py    # Interface AnalyticsPort (qualité, comparaison IA/humain)
│   │   │   ├── draft_history_port.py # Interface DraftHistoryPort (persistance brouillons)
│   │   │   ├── followup_port.py     # Interface FollowupTrackerPort (relances)
│   │   │   ├── token_counter_port.py # Interface TokenCounterPort (comptage tokens/coûts)
│   │   │   ├── processed_emails_port.py # Interface ProcessedEmailsTrackerPort (emails traités)
│   │   │   ├── item_tracker_port.py    # Interface ItemTrackerPort (port générique suivi items)
│   │   │   ├── processed_drafts_port.py # Interface ProcessedDraftsTrackerPort (brouillons traités)
│   │   │   ├── commitment_port.py      # Interface CommitmentTrackerPort (suivi engagements)
│   │   │   ├── task_port.py            # Interface TaskPort (tâches extraites)
│   │   │   ├── sensitive_data_port.py  # Interface SensitiveDataDetectorPort
│   │   │   └── cryptographer_port.py   # Interface CryptographerPort (chiffrement isolé)
│   │   ├── exceptions.py          # Exceptions métier (DomainError, LLMError, ValidationError...)
│   │   └── services/              # Services de domaine
│   │       ├── learning_service.py    # LearningService (orchestration)
│   │       ├── anonymizer_service.py  # DataAnonymizer (anonymisation AES-GCM)
│   │       └── credential_manager.py  # CredentialManager (RBAC permissions)
│   │
│   ├── application/               # Couche Use Cases
│   │   ├── draft_email.py         # DraftEmailUseCase
│   │   ├── critique_email.py      # CritiqueEmailUseCase
│   │   ├── process_email.py       # ProcessEmailUseCase (pipeline complet)
│   │   ├── complete_draft.py      # CompleteDraftUseCase
│   │   ├── send_push_notification.py  # SendPushNotificationUseCase
│   │   ├── push_notification_service.py  # Service de notifications
│   │   ├── wizard_config.py       # Wizard Use Cases (Save, Load, Toggle, Import, Export)
│   │   ├── marketplace.py         # Marketplace Use Cases (Publish, Install, Review)
│   │   ├── fine_tuning.py         # Fine-tuning Use Cases (Corrections, Patterns, Models)
│   │   ├── mobile_companion.py    # Mobile App Use Cases (Session, Sync, Actions)
│   │   ├── learning.py            # Learning Use Cases (Analyze, Extract, Enhance)
│   │   ├── realtime_edit.py       # RealTime Edit Use Cases (Start, Process, Suggest, Apply)
│   │   ├── health_check.py        # HealthCheckUseCase
│   │   ├── analyze_email.py       # AnalyzeEmailUseCase (classification)
│   │   └── email_template.py      # Email Template Use Cases (CRUD, Match, Render)
│   │
│   ├── adapters/                  # Couche Interface Adapters
│   │   ├── llm/                   # Adapters LLM
│   │   │   ├── claude_adapter.py  # Implémentation Anthropic Claude
│   │   │   └── ollama_adapter.py  # Implémentation Ollama (local)
│   │   ├── email/                 # Adapters Email
│   │   │   ├── gmail_adapter.py   # Implémentation Gmail API
│   │   │   └── outlook_adapter.py # Implémentation Microsoft Graph
│   │   └── push/                  # Adapters Push Notifications
│   │       ├── fcm_adapter.py     # Firebase Cloud Messaging
│   │       ├── expo_adapter.py    # Expo Push Notifications
│   │       └── mock_adapter.py    # Mock pour tests
│   │
│   ├── infrastructure/            # Couche Frameworks & Drivers
│   │   ├── container.py           # Injection de dépendances (DI)
│   │   ├── config.py              # Configuration centralisée
│   │   ├── clock.py               # TimeProvider (SystemClock, FakeClock)
│   │   ├── database.py            # SQLite avec WAL
│   │   ├── circuit_breaker.py     # Pattern Circuit Breaker
│   │   ├── rate_limiter.py        # Gestion des quotas API
│   │   ├── retry.py               # Retry avec backoff exponentiel
│   │   ├── security.py            # Chiffrement (Fernet/AES)
│   │   ├── cache.py               # Cache LRU avec TTL
│   │   ├── batch.py               # Traitement par lots
│   │   ├── pagination.py          # Pagination (offset, cursor)
│   │   ├── metrics.py             # Métriques Prometheus
│   │   ├── audit.py               # Logs d'audit
│   │   ├── logging_config.py      # Logging structuré JSON
│   │   ├── notifications.py       # Notifications desktop et push
│   │   ├── device_store.py        # Stockage device tokens
│   │   ├── push_adapter_factory.py # Factory pour adapters push
│   │   ├── wizard_config_store.py # Stockage configuration wizard
│   │   ├── marketplace_store.py   # Stockage marketplace (agents, publishers, reviews)
│   │   ├── fine_tuning_store.py   # Stockage fine-tuning (corrections, patterns, models)
│   │   ├── mobile_companion_store.py # Stockage app mobile (sessions, sync, analytics)
│   │   ├── learning_store.py      # Stockage patterns et ajustements appris (Clean Architecture)
│   │   ├── realtime_edit_store.py # Stockage sessions d'édition temps réel
│   │   ├── email_template_store.py # Stockage templates email (JsonEmailTemplateStore)
│   │   ├── adapters/              # Adapters infrastructure (Clean Architecture)
│   │   │   ├── analytics_adapter.py     # Impl. AnalyticsPort (métriques qualité)
│   │   │   ├── commitment_adapter.py    # Impl. CommitmentTrackerPort (SQLite)
│   │   │   ├── cryptographer_adapter.py # Impl. CryptographerPort (Fernet AES-128-CBC)
│   │   │   ├── draft_history_adapter.py # Impl. DraftHistoryPort (historique brouillons)
│   │   │   ├── followup_adapter.py      # Impl. FollowupTrackerPort (relances)
│   │   │   ├── token_counter_adapter.py # Impl. TokenCounterPort (tokens/coûts)
│   │   │   ├── processed_emails_adapter.py # Impl. ProcessedEmailsTrackerPort (emails traités)
│   │   │   ├── item_tracker_adapter.py  # Impl. ItemTrackerPort (port générique items)
│   │   │   ├── processed_drafts_adapter.py # Impl. ProcessedDraftsTrackerPort (brouillons traités)
│   │   │   └── json_file_store.py       # Base générique JSON file store
│   │   ├── cost_manager.py        # Gestion budget et coûts API
│   │   ├── errors.py              # Gestion centralisée des erreurs
│   │   ├── hot_reload.py          # Hot-reload configuration (watchdog)
│   │   └── monitoring.py          # Monitoring et health checks
│   │
│   ├── api/                       # API REST (Flask) — ~39 fichiers
│   │   ├── app.py                 # Factory Flask + SocketIO + blueprints
│   │   ├── routes.py              # Routes principales (~50 endpoints)
│   │   ├── routes_emails.py       # Routes email (24 endpoints)
│   │   ├── websocket.py           # Événements Socket.IO (/daemon namespace)
│   │   ├── webhooks.py            # Webhooks pour événements
│   │   ├── push_notifications.py  # Endpoints push
│   │   ├── wizard.py              # Endpoints wizard configuration
│   │   ├── marketplace.py         # Endpoints marketplace agents
│   │   ├── fine_tuning.py         # Endpoints fine-tuning
│   │   ├── mobile.py              # Endpoints app mobile companion
│   │   ├── realtime_edit.py       # Endpoints édition temps réel
│   │   ├── email_templates.py     # Endpoints templates email
│   │   ├── accounts.py            # Gestion multi-comptes
│   │   ├── oauth.py               # OAuth providers (Gmail, Outlook)
│   │   ├── settings.py            # Paramètres utilisateur
│   │   ├── labels.py              # Classification et labels
│   │   ├── discord.py             # Intégration Discord
│   │   ├── telegram.py            # Intégration Telegram
│   │   ├── search.py              # Recherche email
│   │   ├── snippets.py            # Bibliothèque de snippets
│   │   ├── folders.py             # Gestion des dossiers
│   │   ├── calendar.py            # Intégration calendrier
│   │   ├── auto_followup.py       # Relances automatiques
│   │   ├── contact_groups.py      # Groupes de contacts
│   │   ├── knowledge.py           # Base de connaissances
│   │   ├── sync.py                # Déclenchement sync manuel
│   │   ├── connectivity.py        # Status de connexion
│   │   └── helpers.py             # Fonctions utilitaires API
│   │
│   ├── agents.py                  # Agents IA (Drafter, Critic, etc.)
│   ├── daemon.py                  # Service background
│   ├── specialized_agents.py      # Agents spécialisés dynamiques
│   ├── draft_completion.py        # Complétion de brouillons
│   ├── learning.py                # Auto-amélioration
│   ├── followups.py               # Suivi des relances
│   ├── message_router.py          # Routage multi-canal (Dispatcher/Supervisor)
│   ├── discord_integration.py     # Support Discord
│   ├── memory_manager.py          # Gestion mémoire IA
│   ├── browser_api.py             # API plugin navigateur
│   ├── multi_accounts.py          # Support multi-comptes
│   └── voice.py                   # Commandes vocales
│
├── agents/                        # Définitions agents (.md)
│   ├── drafter.md                 # Agent rédaction
│   ├── critic.md                  # Agent évaluation
│   ├── dispatcher.md              # Routeur de messages
│   ├── supervisor.md              # Superviseur agents
│   ├── onboarding_specialist.md   # Spécialiste onboarding
│   ├── sales_qualifier.md         # Qualification commerciale
│   ├── refund_handler.md          # Gestionnaire remboursements
│   ├── meeting_scheduler.md       # Planification RDV
│   ├── feedback_analyst.md        # Analyste feedback
│   └── registry.json              # Registre des agents
│
├── tests/                         # Tests unitaires et intégration
├── knowledge/                     # Base de connaissances
├── data/                          # Données persistantes (SQLite, JSON)
└── logs/                          # Logs applicatifs
```

---

## Couches de l'architecture

### 1. Entities (Domain Layer)

Les entités sont des objets métier purs, sans dépendance externe.

```python
# app/domain/entities/email.py
@dataclass
class Email:
    id: str
    sender: str
    subject: str
    body: str
    thread_id: Optional[str] = None
```

**Caractéristiques** :
- Pas d'import de frameworks externes
- Logique métier encapsulée
- Testables unitairement sans mock

### 2. Ports (Interfaces)

Les ports définissent les contrats que les adapters doivent implémenter.

```python
# app/domain/ports/llm_port.py
class LLMPort(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse:
        pass
```

**Principe** : Le domaine ne connaît que les interfaces, jamais les implémentations concrètes.

### 3. Use Cases (Application Layer)

Les use cases orchestrent la logique métier.

```python
# app/application/process_email.py
@dataclass
class ProcessEmailUseCase:
    llm: LLMPort  # Dépend du port, pas de l'implémentation

    def execute(self, email: Email) -> ProcessingResult:
        draft = self._generate_draft(email)
        critique = self._evaluate(draft)
        return self._finalize(draft, critique)
```

**Caractéristiques** :
- Dépend uniquement des entities et ports
- Orchestre le workflow métier
- Indépendant des frameworks

### 4. Adapters (Interface Adapters)

Les adapters implémentent les ports pour des technologies spécifiques.

```python
# app/adapters/llm/claude_adapter.py
class ClaudeAdapter(LLMPort):
    def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse:
        response = self._client.messages.create(...)
        return LLMResponse(content=response.content[0].text, ...)
```

**Caractéristiques** :
- Implémentent les interfaces du domaine
- Encapsulent les SDK et APIs externes
- Interchangeables (ex: Claude ↔ Ollama)

### 5. Infrastructure (Frameworks & Drivers)

Composants techniques cross-cutting.

| Composant | Rôle |
|-----------|------|
| `container.py` | Injection de dépendances (factory) |
| `database.py` | SQLite avec WAL, thread-safe |
| `circuit_breaker.py` | Protection contre les cascades d'échecs |
| `rate_limiter.py` | Gestion des quotas API |
| `retry.py` | Retry avec backoff exponentiel |
| `security.py` | Chiffrement Fernet (AES-128-CBC) |
| `cache.py` | Cache LRU avec TTL |
| `cost_manager.py` | Gestion budget et suivi des coûts API |
| `hot_reload.py` | Hot-reload configuration sans restart |
| `monitoring.py` | Health checks et détection d'échecs |
| `errors.py` | Gestion centralisée des erreurs |

---

## Injection de dépendances

Le `Container` centralise la création des composants :

```python
# app/infrastructure/container.py
@dataclass
class Container:
    config: Config

    @property
    def llm(self) -> LLMPort:
        if self.config.llm_provider == "ollama":
            return OllamaAdapter(...)
        return ClaudeAdapter(...)

    def get_process_use_case(self) -> ProcessEmailUseCase:
        return ProcessEmailUseCase(llm=self.llm, ...)
```

**Avantages** :
- Configuration centralisée
- Facilite les tests (injection de mocks)
- Lazy loading des dépendances

---

## Choix techniques

### Langage & Runtime
| Technologie | Justification |
|-------------|---------------|
| **Python 3.10+** | Écosystème IA mature, typage statique optionnel |
| **dataclasses** | Entités légères et immutables |
| **ABC** | Interfaces explicites pour les ports |

### LLM Providers
| Provider | Usage |
|----------|-------|
| **Claude (Anthropic)** | Production (haute qualité) |
| **Ollama** | Développement local (gratuit) |

### Email Providers
| Provider | API |
|----------|-----|
| **Gmail** | Google API Python Client |
| **Outlook** | Microsoft Graph SDK |
| **IMAP/SMTP** | Protocoles standards |

### Persistance
| Technologie | Usage |
|-------------|-------|
| **SQLite + WAL** | Base principale (thread-safe) |
| **JSON files** | Configuration, patterns appris |

### API & Communication
| Technologie | Usage |
|-------------|-------|
| **Flask** | API REST |
| **Flasgger** | Documentation OpenAPI/Swagger (UI: `/api/docs`) |
| **Flask-SocketIO** | WebSocket temps réel |
| **Prometheus** | Métriques et monitoring |

### Sécurité
| Technologie | Usage |
|-------------|-------|
| **Fernet (AES-128-CBC)** | Chiffrement credentials |
| **OAuth 2.0** | Auth Gmail/Outlook |

### Push Notifications
| Technologie | Plateforme |
|-------------|------------|
| **Firebase Cloud Messaging** | Android/iOS natif |
| **Expo Push** | React Native |

---

## Flux de données

### Pipeline de traitement email

```
Email reçu
    │
    ▼
┌─────────────────┐
│ ClassifierAgent │ → Catégorise (URGENT, NORMAL, SPAM...)
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│ PrioritizationAgent │ → Score priorité (0-100)
└────────┬────────────┘
         │
         ▼
┌───────────────┐
│ DrafterAgent  │ → Génère brouillon V1
└───────┬───────┘
        │
        ▼
┌──────────────┐
│ CriticAgent  │ → Évalue qualité
└───────┬──────┘
        │
   ┌────┴────┐
   │ VALID?  │
   └────┬────┘
    Yes │ No
        │  └──→ DrafterAgent → V2
        │
        ▼
  Brouillon final
```

### Injection de dépendances

```
Container.get_process_use_case()
    │
    ├──→ LLMPort (via container.llm)
    │        └──→ ClaudeAdapter ou OllamaAdapter
    │
    ├──→ knowledge_base (via container.knowledge_base)
    │
    └──→ token_usage (partagé)
```

---

## Testabilité

L'architecture permet de tester chaque couche indépendamment :

### Tests unitaires (Entities)
```python
def test_email_entity():
    email = Email(id="1", sender="a@b.com", subject="Test", body="Hello")
    assert email.sender == "a@b.com"
```

### Tests use cases (avec mocks)
```python
def test_process_email_use_case(mock_llm):
    use_case = ProcessEmailUseCase(llm=mock_llm, knowledge_base="...")
    result = use_case.execute(email)
    assert result.status == DraftStatus.VALIDATED_V1
```

### Tests adapters (avec fakes)
```python
def test_claude_adapter_complete():
    adapter = ClaudeAdapter(api_key="test-key")
    response = adapter.complete(system="...", user="...")
    assert response.content
```

---

## Conformité Clean Architecture

### Les 4 principes respectés

1. **Séparation des couches** : Entities → Use Cases → Interface Adapters → Frameworks
2. **Dependency Rule** : Les dépendances pointent toujours vers l'intérieur (le domaine ne connaît pas les couches externes)
3. **Testabilité** : Le code métier est testable sans UI, BDD ni frameworks
4. **TDD** : Tests écrits avant le code, guidant le design

### Implémentation

| Principe | Implémentation |
|----------|----------------|
| **Séparation des couches** | `domain/`, `application/`, `adapters/`, `infrastructure/` |
| **Dependency Rule** | Imports uniquement vers l'intérieur |
| **Entities indépendantes** | `Email`, `Draft`, `LearnedPattern` sans import externe |
| **Use Cases orchestrateurs** | `ProcessEmailUseCase`, `AnalyzeFeedbackUseCase` |
| **Ports/Adapters** | `LLMPort` + `ClaudeAdapter`, `AnalyticsPort` + `JsonAnalyticsAdapter`, `ItemTrackerPort` + `ItemTrackerAdapter` |
| **Domain Services** | `LearningService` (orchestration multi-use-cases) |
| **DI Container** | `Container` dans `infrastructure/` (1000+ lignes, 70+ factories) |
| **Testabilité** | 361 fichiers de test Python + 91 specs Playwright E2E |

---

## Extensions futures

L'architecture facilite l'ajout de :
- **Nouveaux LLM providers** : Implémenter `LLMPort`
- **Nouveaux email providers** : Implémenter `EmailPort`
- **Nouveaux agents spécialisés** : Ajouter fichier `.md` dans `agents/` (chargement dynamique)
- **Nouvelles notifications** : Implémenter `NotificationPort`
- **Nouveaux canaux de communication** : Via le `MessageRouter` (Discord, Slack, etc.)
- **Nouveaux adapters push** : Implémenter dans `adapters/push/` (FCM, Expo, APNS...)
- **Nouveaux canaux CRM** : Implémenter un nouveau CRM adapter

---

## Frontend Architecture (agentys-app/)

L'application desktop est construite avec **Tauri 2** (backend Rust) et **React 19** (frontend TypeScript).

### Stack technique
- **Tauri 2** : Backend Rust natif (tray icon, shortcuts globaux, IPC, notifications)
- **React 19** : Interface utilisateur avec TypeScript strict
- **Vite** : Build tooling avec code splitting (vendor-react, vendor-socket, vendor-editor, vendor-ui)
- **Socket.IO Client** : Communication temps réel avec le backend Python
- **FullCalendar** : Vues calendrier (Google Calendar, Outlook Calendar)
- **TipTap** : Éditeur de texte riche pour la rédaction
- **i18next** : Internationalisation (FR, EN)
- **Sentry** : Monitoring des erreurs frontend

### Structure
```
agentys-app/src/
├── components/           # ~117 composants React
│   ├── EmailList.tsx     # Liste virtualisée (react-window v2)
│   ├── Sidebar.tsx       # Navigation par onglets
│   ├── Settings.tsx      # Paramètres utilisateur
│   ├── compose/          # Modal de composition email
│   ├── deep-focus/       # Mode Deep Focus (concentration)
│   ├── Calendar/         # Intégration calendrier
│   ├── labels/           # Gestion des labels
│   ├── snippets/         # Bibliothèque de snippets
│   ├── onboarding/       # Onboarding premium (6 étapes)
│   ├── admin/            # Dashboard administrateur
│   ├── support/          # Panel de support
│   └── ui/               # Composants UI réutilisables
├── hooks/                # ~69 hooks custom
│   ├── useBackend.ts     # Communication API
│   ├── useDraftController.ts  # Gestion des brouillons
│   ├── useWebSocketSync.ts    # Synchronisation Socket.IO
│   ├── useModals.ts      # Gestion des modales
│   └── useSnooze.ts      # Fonctionnalité snooze
├── services/             # Services métier
│   ├── api.ts            # Client HTTP (apiClient)
│   ├── websocket.ts      # Événements Socket.IO
│   ├── oauth.ts          # Gestion OAuth providers
│   └── notifications.ts  # Notifications natives
├── types/                # Interfaces TypeScript
└── api/                  # Couche API typée (emails, accounts, labels)
```

### Patterns architecturaux
- **Lazy loading** : Toutes les modales chargées avec `React.lazy()` et `Suspense`
- **State-driven routing** : Navigation par état (pas de router URL)
- **Tauri IPC** : Commandes Rust exposées au frontend (tray, shortcuts, autostart)
- **Singleton cleanup** : Handlers de disposal HMR pour prévenir les fuites mémoire

---

## Services Background (app/services/)

Le backend exécute plusieurs services en parallèle, démarrés par `run_api.py` :

| Service | Rôle | Intervalle |
|---------|------|-----------|
| **SyncService** | Polling email multi-comptes | Configurable (60s défaut) |
| **BatchWorker** | Traitement hors-heures à 50% de réduction | Optionnel |
| **RecapScheduler** | Génération de récaps mensuels | Mensuel |
| **LearningRefreshScheduler** | Rafraîchissement base de connaissances | Toutes les 6h |
| **ReminderChecker** | Vérification des relances à envoyer | 60s (daemon thread) |
| **DraftOrchestrator** | Pipeline de génération de brouillons | Sur événement |
| **CacheManager** | Cache LRU avec TTL | Continu |

---

## Intégrations Externes (app/integrations/)

| Intégration | Module | Description |
|-------------|--------|-------------|
| **Stripe** | `stripe_adapter.py` | Paiements et abonnements |
| **Shopify** | `shopify_adapter.py` | E-commerce |
| **PayPal** | `paypal_adapter.py` | Paiements alternatifs |
| **WordPress** | `wordpress_adapter.py` | CMS integration |
| **Custom API** | `custom_api_adapter.py` | Intégrations personnalisées |

---

## Projets Compagnons

| Projet | Répertoire | Stack | Description |
|--------|------------|-------|-------------|
| **App Mobile** | `agentys-mobile/` | React Native / Expo | Companion mobile pour approuver/rejeter les brouillons |
| **Serveur MCP** | `agentys_mcp/` | Python (MCP SDK) | Model Context Protocol pour intégration IA |
| **Extension Navigateur** | `browser_plugin/` | JS (Chrome/Firefox) | Génération de réponses depuis Gmail/Outlook web |
| **Admin Standalone** | `admin-standalone/` | React | Interface d'administration indépendante |
| **Marketing IA** | `ai-marketing-team/` | Python | Module de génération de contenu marketing |

---

## Modules récents

### Marketplace d'agents IA
Permet de publier, découvrir et installer des agents spécialisés :
- Workflow de publication (Draft → Review → Published)
- Système de reviews et notes
- Packs d'agents avec réductions

### Fine-tuning avec feedback
Amélioration continue basée sur les corrections utilisateur :
- Analyse automatique des types de corrections
- Extraction de patterns récurrents
- Application automatique aux futurs drafts

### App Mobile Companion
Synchronisation et gestion des brouillons depuis mobile :
- Sessions sécurisées avec heartbeat
- Actions batch (approve, reject, edit)
- Analytics et préférences utilisateur

### Learning System (Clean Architecture)
Système d'apprentissage automatique basé sur les feedbacks utilisateur :

**Architecture Clean :**
- **Entités** : `LearnedPattern`, `PromptAdjustment`, `LearningInsights`, `LearningStats`, `ReviewRequirement` (`app/domain/entities/learning.py`)
- **Ports** : `LearningPatternStorePort`, `AdjustmentStorePort`, `LearningFeedbackProviderPort`, `LearningServicePort` (`app/domain/ports/learning_port.py`)
- **Use Cases** : `AnalyzeFeedbackUseCase`, `ExtractPatternsUseCase`, `ShouldRequireReviewUseCase`, `GenerateAdjustmentUseCase`, `GetLearningStatsUseCase`, `EnhancePromptUseCase` (`app/application/learning.py`)
- **Adapters** : `JsonLearningPatternStore`, `JsonAdjustmentStore`, `HistoryFeedbackAdapter` (`app/infrastructure/learning_store.py`)
- **Service** : `LearningService` (`app/domain/services/learning_service.py`)

**Fonctionnalités :**
- Analyse des feedbacks utilisateur (positifs, négatifs, neutres)
- Extraction de patterns récurrents (bons et mauvais)
- Génération d'ajustements de prompt basés sur les patterns
- Détection automatique de la nécessité de review humaine
- Amélioration continue des prompts avec les ajustements actifs
- Statistiques complètes (taux de satisfaction V1/V2, patterns, ajustements)

**Intégration Container :**
```python
container = get_container()
learning_service = container.get_learning_service()
stats = learning_service.get_stats()
```

### Realtime Edit (Clean Architecture)
Édition temps réel des brouillons avec suggestions IA :

**Architecture Clean :**
- **Entités** : `EditSession`, `TextChange`, `EditTrigger`, `Suggestion`, `SuggestionResult`, `TextDiff` (`app/domain/entities/realtime_edit.py`)
- **Ports** : `EditSessionStorePort`, `RealTimeEditPort`, `SuggestionHistoryPort` (`app/domain/ports/realtime_edit_port.py`)
- **Use Cases** : `StartEditSessionUseCase`, `ProcessTextChangeUseCase`, `GetSuggestionUseCase`, `ApplySuggestionUseCase`, `CloseEditSessionUseCase`, `CleanupExpiredSessionsUseCase` (`app/application/realtime_edit.py`)
- **Adapters** : `JsonEditSessionStore`, `InMemoryEditSessionStore` (`app/infrastructure/realtime_edit_store.py`)
- **API** : `/api/realtime-edit/*` (`app/api/realtime_edit.py`)

**Fonctionnalités :**
- Sessions d'édition avec suivi du texte en temps réel
- Détection de changements (insertion, suppression, remplacement)
- Triggers intelligents : blur, pause de frappe, fin de phrase, manuel
- Suggestions IA avec diffs précis (difflib)
- Accepter/rejeter les suggestions individuellement
- Gestion des timeouts et sessions expirées

### Ports et Adapters Infrastructure (Refactoring Clean Architecture)

Modules legacy migrés vers l'architecture ports/adapters :

**Analytics (Métriques de qualité) :**
- **Entités** : `QualityScore`, `HumanEdit`, `PerformanceMetrics`, `QualityMetrics`, `AIVsHumanComparison` (`app/domain/entities/analytics.py`)
- **Port** : `AnalyticsPort` (`app/domain/ports/analytics_port.py`)
- **Adapter** : `JsonAnalyticsAdapter` (`app/infrastructure/adapters/analytics_adapter.py`)

**Draft History (Historique brouillons) :**
- **Entités** : `DraftRecord` (`app/domain/entities/draft_history.py`)
- **Port** : `DraftHistoryPort` (`app/domain/ports/draft_history_port.py`)
- **Adapter** : `JsonDraftHistoryAdapter` (`app/infrastructure/adapters/draft_history_adapter.py`)

**Follow-up (Relances) :**
- **Entités** : `SentEmail`, `FollowupSchedule`, `FollowupStats`, `FollowupStatus`, `FollowupPriority` (`app/domain/entities/followup.py`)
- **Port** : `FollowupTrackerPort` (`app/domain/ports/followup_port.py`)
- **Adapter** : `JsonFollowupAdapter` (`app/infrastructure/adapters/followup_adapter.py`)

**Token Counter (Comptage tokens/coûts) :**
- **Port** : `TokenCounterPort` (`app/domain/ports/token_counter_port.py`)
- **Adapter** : `JsonTokenCounterAdapter` (`app/infrastructure/adapters/token_counter_adapter.py`)

**Processed Emails Tracker (Suivi emails traités) :**
- **Port** : `ProcessedEmailsTrackerPort` (`app/domain/ports/processed_emails_port.py`)
- **Adapter** : `ProcessedEmailsAdapter` (`app/infrastructure/adapters/processed_emails_adapter.py`)
- **Refactoring** : Simplification via réutilisation de `ItemTrackerAdapter` (composition over duplication)

**Item Tracker (Port générique de suivi d'items) :**
- **Port** : `ItemTrackerPort` (`app/domain/ports/item_tracker_port.py`)
- **Adapter** : `ItemTrackerAdapter` (`app/infrastructure/adapters/item_tracker_adapter.py`)
- **Description** : Port générique pour le suivi d'items traités (emails, brouillons, etc.)
- **Méthodes** : `is_processed()`, `mark_processed()`, `count()`, `get_all_ids()`, `clear()`
- **Principe DRY** : Évite la duplication de code entre ProcessedEmailsTrackerPort et ProcessedDraftsTrackerPort

**Processed Drafts Tracker (Suivi brouillons utilisateur traités) :**
- **Port** : `ProcessedDraftsTrackerPort` (`app/domain/ports/processed_drafts_port.py`)
- **Adapter** : `ProcessedDraftsAdapter` (`app/infrastructure/adapters/processed_drafts_adapter.py`)
- **Description** : Spécialisé pour les brouillons utilisateur complétés par le daemon

### Traçabilité des brouillons (Logging DEBUG)

Système de logging détaillé pour comprendre pourquoi un brouillon est ignoré ou traité :

**Configuration :**
```bash
LOG_LEVEL=DEBUG python run_daemon.py  # Active les logs détaillés
```

**Logs générés :**
- `📝 Brouillon déjà traité: {draft_id}...` - Brouillon dans le cache
- `📝 Aucun nouveau brouillon à traiter` - Tous les brouillons sont traités
- `📝 Analyse brouillon: subject='...', body='...'` - Contenu analysé
- `📝 Pas une demande de complétion, ignoré` - Le brouillon n'a pas de préfixe trigger

**Préfixes de déclenchement (DraftInput) :**
- `brouillon:` / `brouillon :` - Français
- `draft:` / `draft :` - Anglais
- `ébauche:` / `ébauche :` - Alternative française
- `à compléter:` / `a compléter:` - Explicite
- `idées pour email:` - Notes à développer
- `rédige à partir de ça:` - Instruction directe

**Validation robuste :**
- Gestion des valeurs null/empty dans `DraftInput.is_draft_input()`
- Sujet manquant → `"Re: (sans sujet)"` dans `_generate_reply_subject()`
- Entité `DraftInput.from_text()` retourne une structure vide si le texte est null

### Exceptions de Domaine (Clean Architecture)

Module centralisé pour les exceptions métier (`app/domain/exceptions.py`) :

**Exceptions de base :**
- `DomainError` - Exception de base pour toutes les erreurs du domaine
- `ValidationError` - Erreur de validation des données
- `EmptyValueError` - Valeur vide non autorisée
- `InvalidBoundsError` - Valeur hors des bornes autorisées
- `InvalidFormatError` - Format de données invalide
- `EntityNotFoundError` - Entité non trouvée
- `BusinessRuleViolationError` - Violation d'une règle métier
- `ConcurrencyError` - Modification simultanée détectée

**Exceptions LLM (hiérarchie spécialisée) :**
- `LLMError` - Exception de base pour les erreurs LLM
- `LLMAuthenticationError` - API key invalide ou expirée
- `LLMRateLimitError` - Limite de requêtes atteinte (429)
- `LLMUnavailableError` - Service temporairement indisponible
- `LLMConnectionError` - Impossible de se connecter
- `LLMTimeoutError` - Timeout lors de la requête
- `LLMContextLengthError` - Prompt dépasse la limite de contexte
- `LLMResponseError` - Réponse invalide ou malformée
- `LLMModelNotFoundError` - Modèle demandé n'existe pas

**Principe Clean Architecture :**
- Exceptions définies dans le Domain
- Utilisées par les Entities et Use Cases
- Les Adapters traduisent vers/depuis ces exceptions

**Avantages du refactoring :**
- Isolation complète du domaine métier
- Interchangeabilité des implémentations (JSON → SQLite → API externe)
- Testabilité accrue avec injection de mocks
- Conformité stricte à la Dependency Rule

### Generate Preview Endpoint (Preview de réponse IA)

Endpoint pour générer une preview de réponse IA sans créer de brouillon dans le client email :

**Architecture Clean :**
- **Route** : `POST /api/generate` (`app/api/routes.py`)
- **Handler** : `generate_preview()` - Nouvelle fonction dans routes.py
- **Réutilisation** : `_process_email_with_use_case()` - Helper existant
- **Use Cases** : `AnalyzeEmailUseCase`, `ProcessEmailUseCase` (réutilisés)

**Contrat API :**
```
POST /api/generate
Content-Type: application/json

{
  "email_id": "string (required)",
  "tone": "formal|friendly|neutral (optional)"
}

Response 200:
{
  "success": true,
  "email_id": "...",
  "classification": "commercial|support|...",
  "priority": 1-5,
  "status": "V1|V2",
  "draft": {
    "subject": "Re: ...",
    "body": "...",
    "tokens_used": 1234
  },
  "agents_trace": [
    {"agent": "Classifier", "status": "completed", "result": "..."},
    {"agent": "Drafter", "status": "completed", "result": "..."},
    {"agent": "Critic", "status": "completed", "result": "..."}
  ]
}

Response 400: { "error": "email_id is required" }
Response 401: { "error": "Authentication failed" }
Response 404: { "error": "Email not found" }
Response 500: { "error": "An internal error occurred" }
```

**Différence avec `POST /api/emails/<id>/process` :**
| Aspect | `/api/generate` | `/api/emails/<id>/process` |
|--------|-----------------|----------------------------|
| Brouillon créé | ❌ Non | ✅ Oui |
| Cas d'usage | Preview mode "Contrôle" | Mode "Magique" |
| Réponse enrichie | ✅ Complète (trace agents) | Basique |

**Pattern utilisé : Facade + Use Case Reuse**
```
POST /api/generate
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│  generate_preview() - NOUVELLE FONCTION                  │
│  Couche: Interface (API)                                 │
│  ─────────────────────────────────────────────────────── │
│  1. Authentification via LegacyModuleLoader              │
│  2. Récupération email via provider                      │
│  3. Appel _process_email_with_use_case() [RÉUTILISÉ]     │
│  4. Construction réponse enrichie                        │
│  5. PAS de provider.create_draft() ← DIFFÉRENCE CLÉ     │
└──────────────────────────────────────────────────────────┘
```

**Conformité Clean Architecture :**
- ✅ **Dependency Rule** : Interface → Application → Domain
- ✅ **Réutilisation** : 90% du code existant via helper
- ✅ **Séparation des responsabilités** : Génération ≠ Sauvegarde

---

### Get Email by ID Endpoint (Récupération d'un email)

Endpoint pour récupérer les détails d'un email spécifique par son ID :

**Architecture Clean :**
- **Route** : `GET /api/emails/<email_id>` (`app/api/routes.py`)
- **Handler** : `get_email()` - Fonction dans routes.py
- **Réutilisation** : Helpers existants (`_get_authenticated_provider()`, `_validate_email_id()`, `_get_email_by_id()`, `_email_to_dict()`)

**Contrat API :**
```
GET /api/emails/<email_id>

Response 200:
{
  "id": "abc123",
  "sender": "user@example.com",
  "sender_name": "John Doe",
  "subject": "Re: Question",
  "received_at": "2024-01-15T10:30:00Z",
  "has_attachments": false,
  "conversation_id": "conv123"
}

Response 400: { "error": "Invalid email_id format" }
Response 401: { "error": "Authentication failed" }
Response 404: { "error": "Email not found" }
Response 500: { "error": "An internal error occurred while getting email" }
```

**Pattern utilisé : Direct Provider Call + Helper Reuse**
```
GET /api/emails/<email_id>
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│  get_email() - FONCTION                                   │
│  Couche: Interface (API)                                 │
│  ─────────────────────────────────────────────────────── │
│  1. Validation ID via _validate_email_id()               │
│  2. Authentification via _get_authenticated_provider()   │
│  3. Récupération via _get_email_by_id()                  │
│  4. Sérialisation via _email_to_dict()                   │
└──────────────────────────────────────────────────────────┘
```

**Conformité Clean Architecture :**
- ✅ **Dependency Rule** : Interface (API) → Domain (EmailProvider port)
- ✅ **Réutilisation DRY** : 100% des helpers existants réutilisés
- ✅ **Single Responsibility** : Endpoint fait une seule chose (lecture)
- ✅ **REST Complet** : Complète le CRUD (Read individuel ajouté)

---

### Send Draft Endpoint (Envoi de brouillon)

Endpoint pour envoyer un brouillon de réponse email précédemment généré :

**Architecture Clean :**
- **Route** : `POST /api/emails/<draft_id>/send` (`app/api/routes.py`)
- **Handler** : `send_draft()` - Nouvelle fonction dans routes.py
- **Réutilisation** : Helpers existants (`_get_authenticated_provider()`, `_validate_email_id()`, `_sanitize_for_log()`)
- **Provider** : `EmailProvider.send_draft(draft_id)` - Méthode abstraite déjà implémentée dans tous les adapters

**Contrat API :**
```
POST /api/emails/<draft_id>/send
Content-Type: application/json

Response 200:
{
  "success": true,
  "draft_id": "abc123",
  "message": "Email sent successfully"
}

Response 400: { "error": "Invalid draft ID format" }
Response 401: { "error": "Authentication failed" }
Response 404: { "error": "Failed to send draft" }
Response 500: { "error": "An internal error occurred" }
```

**Différence avec `POST /api/generate` :**
| Aspect | `/api/emails/<id>/send` | `/api/generate` |
|--------|-------------------------|-----------------|
| Action | Envoie un brouillon existant | Génère une preview |
| Brouillon requis | ✅ Oui (draft_id) | ❌ Non |
| Cas d'usage | Mode "Contrôle" après preview | Mode "Preview" |

**Pattern utilisé : Direct Provider Call**
```
POST /api/emails/<draft_id>/send
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│  send_draft() - NOUVELLE FONCTION                        │
│  Couche: Interface (API)                                 │
│  ─────────────────────────────────────────────────────── │
│  1. Validation ID via _validate_email_id()               │
│  2. Authentification via _get_authenticated_provider()   │
│  3. Appel provider.send_draft(draft_id)                  │
│  4. Logging sécurisé via _sanitize_for_log()            │
└──────────────────────────────────────────────────────────┘
```

**Conformité Clean Architecture :**
- ✅ **Dependency Rule** : Interface (API) → Domain (EmailProvider port)
- ✅ **Réutilisation DRY** : 100% des helpers existants réutilisés
- ✅ **Single Responsibility** : Endpoint fait une seule chose (envoyer)
- ✅ **Pragmatisme** : Pas de Use Case dédié (over-engineering évité)

**Décision architecturale :**
L'endpoint appelle directement `provider.send_draft()` sans passer par un Use Case car :
1. La logique métier est minimale (validation + appel provider)
2. L'interface `EmailProvider.send_draft()` encapsule déjà toute la complexité
3. Pattern cohérent avec les endpoints existants (`list_drafts`, `get_draft`)

---

### Task Extraction (Extraction automatique des tâches)

Système d'extraction automatique des tâches depuis les emails et création manuelle :

**Architecture Clean :**
- **Agent** : `TaskExtractorAgent` (`app/agents.py`) - Agent IA pour extraire les tâches
- **Entités** : Tâches avec id, email_id (NULL pour manuelles), description, status, priority, deadline
- **Port** : `TaskPort` (`app/domain/ports/task_port.py`) - Interface abstraite (get_all, get_by_id, mark_completed, create)
- **Repository** : `TaskRepository` (`app/infrastructure/database.py`) - Implémentation SQLite
- **API** : `/api/tasks/*` (`app/api/routes.py`) - 4 endpoints REST (GET list, GET by id, POST create, PATCH complete)

**Port TaskPort :**
```python
class TaskPort(ABC):
    @abstractmethod
    def get_all(self, status: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Récupère les tâches avec filtres optionnels."""
        pass

    @abstractmethod
    def get_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Récupère une tâche par son ID."""
        pass

    @abstractmethod
    def mark_completed(self, task_id: int) -> bool:
        """Marque une tâche comme complétée."""
        pass

    @abstractmethod
    def create(self, title: str, description: str = None, priority: str = "medium", deadline: str = None) -> Dict[str, Any]:
        """Crée une tâche manuelle (sans email_id)."""
        pass
```

**Endpoints API :**
| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/tasks` | Liste les tâches (filtres: status, limit) |
| `GET` | `/api/tasks/<id>` | Détails d'une tâche par ID |
| `POST` | `/api/tasks` | Crée une tâche manuelle (JSON body: title, description, priority, deadline) |
| `PATCH` | `/api/tasks/<id>` | Marquer une tâche comme complétée |

**Contrat API POST /api/tasks :**
```
POST /api/tasks
Content-Type: application/json

{
  "title": "string (required)",
  "description": "string (optional)",
  "priority": "high|medium|low (optional, default: medium)",
  "deadline": "YYYY-MM-DD (optional)"
}

Response 201:
{
  "id": 1,
  "title": "...",
  "description": "...",
  "priority": "medium",
  "deadline": null,
  "status": "pending",
  "created_at": "2024-01-15T10:00:00"
}

Response 400: { "error": "Title is required" }
```

**Décision architecturale :** La méthode `create` est distincte de `add` (utilisée pour l'extraction email) pour respecter l'Interface Segregation Principle. Les tâches manuelles ont `email_id = NULL`.

**Intégration Container :**
```python
container = get_container()
task_repo = container.get_task_repository()
tasks = task_repo.get_all(status="pending", limit=100)
```

**Patterns utilisés :**
- **Repository Pattern** : Abstraction de la couche de données
- **Dependency Inversion** : API dépend du port, pas de l'implémentation
- **Single Responsibility** : Chaque endpoint a une responsabilité unique
- **Consistent Response Format** : Format JSON uniforme avec les autres endpoints

---

### Email Templates (Templates d'emails réutilisables)

Système de templates d'emails pour les réponses récurrentes :

**Architecture Clean (Refactoring progressif) :**
- **Entités** : `EmailTemplate`, `TemplateMatch`, `TemplateVariables` (`app/domain/entities/email_template.py`)
- **Port** : `EmailTemplateStorePort` (`app/domain/ports/email_template_port.py`)
- **Use Cases** : `CreateTemplateUseCase`, `GetTemplateUseCase`, `ListTemplatesUseCase`, `UpdateTemplateUseCase`, `DeleteTemplateUseCase`, `MatchTemplateUseCase`, `RenderTemplateUseCase` (`app/application/email_template.py`)
- **Adapter** : `JsonEmailTemplateStore` (`app/infrastructure/email_template_store.py`)
- **API** : `/api/templates/*` (`app/api/email_templates.py`)
- **Compatibilité** : Réexports dans `app/email_templates.py` pour backward compatibility

**Entité EmailTemplate :**
```python
@dataclass
class EmailTemplate:
    id: str
    name: str
    category: str                    # URGENT, NORMAL, MEETING, etc.
    template_body: str
    description: str = ""
    language: str = "fr"
    tone: str = "professional"
    priority: int = 0
    enabled: bool = True
    usage_count: int = 0
    conditions: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
```

**Port EmailTemplateStorePort :**
- `add(template)` : Ajoute un template
- `get(template_id)` : Récupère un template par ID
- `get_all()` : Liste tous les templates
- `get_by_category(category)` : Templates par catégorie
- `remove(template_id)` : Supprime un template
- `find_best_match(category, subject, body, language)` : Matching IA
- `render(template, variables)` : Rendu avec variables
- `get_stats()` : Statistiques d'utilisation

**Endpoints API :**
| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/templates` | Liste tous les templates |
| `POST` | `/api/templates` | Crée un template |
| `GET` | `/api/templates/<id>` | Détails d'un template |
| `PUT` | `/api/templates/<id>` | Met à jour un template |
| `DELETE` | `/api/templates/<id>` | Supprime un template |
| `POST` | `/api/templates/match` | Trouve le meilleur template |
| `POST` | `/api/templates/<id>/render` | Rend un template |
| `GET` | `/api/templates/stats` | Statistiques |

**Variables dynamiques (TemplateVariables) :**
- `{{sender_name}}` - Nom de l'expéditeur
- `{{sender_email}}` - Email de l'expéditeur
- `{{subject}}` - Sujet de l'email
- `{{date}}` - Date courante
- Extensible via la classe `TemplateVariables`

**Décision architecturale :**
Refactoring progressif de `app/email_templates.py` (monolithique) vers Clean Architecture :
1. Extraction des entités vers le domain
2. Création du port abstrait
3. Transformation du manager existant en adapter
4. Création des use cases
5. Ajout de l'API REST
6. Réexports pour backward compatibility (tests existants fonctionnent)

**Patterns utilisés :**
- **Repository Pattern** : `EmailTemplateStorePort` abstrait la persistance
- **Use Case Pattern** : Chaque opération = 1 classe
- **Dependency Inversion** : Application dépend des ports, pas des implémentations
- **Factory Pattern** : Container pour l'injection
- **Facade Pattern** : `app/email_templates.py` expose l'API simplifiée

---

### Commitment Tracking (Suivi des engagements)

Système de suivi des engagements pris dans les emails envoyés :

**Architecture Clean :**
- **Entités** : `Commitment`, `CommitmentStatus` (`app/domain/entities/commitment.py`)
- **Port** : `CommitmentTrackerPort` (`app/domain/ports/commitment_port.py`)

**Entité Commitment :**
```python
@dataclass
class Commitment:
    id: str                           # UUID unique
    email_id: str                     # Référence à l'email source
    description: str                  # Description de l'engagement
    detected_at: str                  # ISO timestamp de détection
    status: CommitmentStatus          # Statut actuel
    deadline: Optional[str] = None    # ISO date optionnelle
    completed_at: Optional[str] = None # Date de complétion
```

**Enum CommitmentStatus :**
- `PENDING` : Engagement détecté, en attente
- `COMPLETED` : Marqué comme réalisé
- `CANCELLED` : Annulé par l'utilisateur
- `OVERDUE` : Deadline dépassée

**Méthodes immutables (pattern dataclasses.replace) :**
- `mark_completed(completed_at: str) -> Commitment`
- `mark_cancelled() -> Commitment`
- `mark_overdue() -> Commitment`

**Port CommitmentTrackerPort :**
- `add_commitment(commitment)` : Ajoute un engagement
- `get_pending()` : Récupère les engagements en attente
- `get_by_email(email_id)` : Engagements par email
- `get_overdue()` : Engagements en retard
- `mark_completed(commitment_id)` : Marque comme complété
- `mark_cancelled(commitment_id)` : Marque comme annulé
- `get_by_id(commitment_id)` : Récupère par ID
- `get_all()` : Tous les engagements

**Adapter SQLite :**
- **Adapter** : `SqliteCommitmentAdapter` (`app/infrastructure/adapters/commitment_adapter.py`)
- **Export** : Ajouté dans `app/infrastructure/adapters/__init__.py`
- **Tests TDD** : `tests/infrastructure/adapters/test_commitment_adapter.py` (15+ tests)

**Schéma SQL :**
```sql
CREATE TABLE IF NOT EXISTS commitments (
    id TEXT PRIMARY KEY,
    email_id TEXT NOT NULL,
    description TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    deadline TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_commitments_email_id ON commitments(email_id);
CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(status);
```

**Use Case :**
- **Use Case** : `CommitmentTrackingUseCase` (`app/application/commitment_tracking.py`)
- **Tests TDD** : `tests/application/test_commitment_tracking.py` (35+ tests)

**Méthodes du Use Case :**
- `track_commitment(commitment)` : Enregistre un nouvel engagement
- `get_pending()` : Récupère les engagements en attente
- `get_overdue()` : Récupère les engagements en retard
- `complete(commitment_id)` : Marque comme complété
- `cancel(commitment_id)` : Marque comme annulé
- `get_by_email(email_id)` : Engagements par email
- `get_by_id(commitment_id)` : Récupère par ID
- `get_all()` : Tous les engagements

**Pattern architectural :**
- **Dependency Injection** : Le port `CommitmentTrackerPort` est injecté via le constructeur `@dataclass`
- **Facade Pattern** : Le use case expose une interface simplifiée à l'API
- **Delegation** : Toutes les opérations délèguent au port d'infrastructure

**CommitmentExtractorAgent (Façade d'extraction) :**

Agent LLM pour détecter les engagements dans les emails envoyés :

```
┌─────────────────────────────────────────────────────────────────┐
│                         app/agents.py                           │
├─────────────────────────────────────────────────────────────────┤
│  COMMITMENT_EXTRACTOR_PROMPT = """..."""                        │
│                                                                 │
│  @dataclass                                                     │
│  class ExtractedCommitment:                                     │
│      description: str                                           │
│      deadline: Optional[str] = None                             │
│                                                                 │
│  @dataclass                                                     │
│  class CommitmentExtractorAgent:                                │
│      model: str = MODEL_FAST                                    │
│      max_tokens: int = MAX_TOKENS_COMMITMENT_EXTRACTION         │
│      _llm: Optional[LLMPort] = field(default=None, repr=False)  │
│                                                                 │
│      def extract(self, email_content: str)                      │
│          -> List[ExtractedCommitment]                           │
└─────────────────────────────────────────────────────────────────┘
```

**Exemples d'engagements détectés :**
- "Je vous envoie le document demain"
- "Je m'en occupe cette semaine"
- "Je vous rappelle lundi"
- "Je reviens vers vous avec une proposition"

**Différence avec l'entité Domain `Commitment` :**
- **`ExtractedCommitment`** (façade, léger) : Données brutes extraites par le LLM
- **`Commitment`** (domain, riche) : Entité persistée avec lifecycle complet

La conversion `ExtractedCommitment` → `Commitment` se fait dans le use case `CommitmentTrackingUseCase`.

**Tests TDD (tests/test_agents.py) :**
- `TestCommitmentExtractorAgent` : Tests extraction (7+ tests)
- `TestCommitmentExtractorAgentParseCommitment` : Tests parsing JSON

**Prochaines étapes :**
1. ~~Détecteur : Implémentation `CommitmentExtractorAgent`~~ ✅ (2026-01-01)
2. Scheduler : Job pour marquer les engagements `OVERDUE`
3. Injection Container : Wiring dans `container.py`
4. Intégration Daemon : Scanner les emails envoyés automatiquement

---

## Tests et TDD

### Approche TDD (Test-Driven Development)

Le projet suit une approche **Test-Driven Development** stricte :

1. **Red-Green-Refactor** : Écrire d'abord un test qui échoue, puis le code minimal pour le faire passer, puis refactorer
2. **Tests edge cases** : Couverture exhaustive des cas limites, erreurs et scénarios extrêmes
3. **Tests par couche** : Tests unitaires pour chaque couche de l'architecture (entities, use cases, adapters, infrastructure)
4. **Isolation des dépendances** : Le domaine métier est testable sans UI, DB ni services externes

### Catégories de tests

| Catégorie | Fichiers | Description |
|-----------|----------|-------------|
| **Tests unitaires** | `test_*.py` | Tests isolés par composant |
| **Tests d'intégration** | `test_*_integration.py` | Tests de workflow complet |
| **Tests edge cases TDD** | `test_*_edge_cases_tdd.py` | Scénarios limites et erreurs |
| **Tests de charge** | `test_load.py`, `test_performance.py` | Performance et scalabilité |

### Fichiers de tests edge cases

Ces fichiers suivent une méthodologie TDD rigoureuse pour couvrir les cas extrêmes :

- `test_learning_store_edge_cases_tdd.py` - Edge cases des stores d'apprentissage
- `test_container_edge_cases_tdd.py` - Edge cases de l'injection de dépendances
- `test_infrastructure_edge_cases_tdd.py` - Edge cases infrastructure (rate limiter, circuit breaker, etc.)
- `test_realtime_edit_edge_cases_tdd.py` - Edge cases édition temps réel
- `test_api_edge_cases_tdd.py` - Edge cases des endpoints API
- `test_mobile_edge_cases_tdd.py` - Edge cases app mobile companion
- `test_push_edge_cases_tdd.py` - Edge cases notifications push
- `test_concurrency_sync_tdd.py` - Edge cases synchronisation et concurrence
- `test_entities_validation_tdd.py` - Edge cases validation entités
- `test_legacy_ports_tdd.py` - Edge cases ports legacy (analytics, followup, etc.)
- `test_llm_edge_cases_tdd.py` - Edge cases appels LLM
- `test_numeric_edge_cases_tdd.py` - Edge cases valeurs numériques et limites
- `test_item_tracker_port.py` - Tests port générique ItemTrackerPort
- `test_item_tracker_adapter.py` - Tests adapter ItemTrackerAdapter
- `test_processed_emails_tracker_tdd.py` - Edge cases ProcessedEmailsTracker (240 tests)
- `test_processed_drafts_adapter.py` - Tests adapter ProcessedDraftsAdapter
- `test_user_draft_polling.py` - Tests polling brouillons utilisateur
- `test_daemon_edge_cases_null_empty.py` - Edge cases daemon (null/empty/boundary)
- `test_daemon_lifecycle_edge_cases.py` - Edge cases lifecycle daemon (start/stop/restart)
- `test_daemon_edge_cases_additional.py` - Edge cases supplémentaires daemon
- `test_edge_cases_comprehensive.py` - Tests edge cases comprehensifs multi-modules
- `test_gmail_adapter_edge_cases.py` - Edge cases Gmail adapter (OAuth, refresh, API)
- `test_followups_auto.py` - Tests détection automatique follow-ups (3 scénarios)
- `test_commitment.py` - Tests entité Commitment et enum CommitmentStatus
- `test_commitment_adapter.py` - Tests adapter SQLite CommitmentTrackerPort (15+ tests TDD)
- `test_commitment_tracking.py` - Tests use case CommitmentTrackingUseCase (35+ tests TDD)
- `test_cryptographer_port.py` - Tests interface CryptographerPort (45+ tests TDD)
- `test_cryptographer_adapter.py` - Tests adapter FernetCryptographerAdapter (71 tests TDD)
- `test_api_drafts_complete.py` - Tests endpoint POST /api/drafts/complete (19+ tests)

### Fixtures globaux (conftest.py)

| Fixture | Scope | Mode | Description |
|---------|-------|------|-------------|
| `mock_notifications` | function | autouse | Désactive toutes les notifications (desktop/push) pendant les tests |

**Pattern mock_notifications :**
```python
@pytest.fixture(autouse=True)
def mock_notifications(monkeypatch):
    """Mock global - désactive toutes les notifications."""
    mock_manager = MagicMock(spec=NotificationManager)
    mock_manager.send.return_value = True
    monkeypatch.setattr(
        "app.infrastructure.notifications.get_notification_manager",
        lambda: mock_manager
    )
    # Reset singleton pour forcer re-création
    monkeypatch.setattr(
        "app.infrastructure.notifications._notification_manager",
        None
    )
```

**Avantages :**
- Aucune notification parasite pendant les tests
- S'applique automatiquement à tous les tests (autouse=True)
- Isolation complète : singleton reset entre chaque test
- Respecte l'interface via `spec=NotificationManager`

### Couverture

- **5120+ tests** répartis sur **118+ fichiers**
- Couverture de code : **~85%**
- Temps d'exécution : **< 2 secondes** pour la collecte

---

## Sécurité Email

### Détection de Phishing avec Move to Spam

Système de détection automatique des emails frauduleux avec déplacement vers les spams :

**Architecture Clean :**
- **Port** : Méthode `move_to_spam(message_id: str) -> bool` dans `EmailProvider` (`app/interfaces/email_provider.py`)
- **Adapters** :
  - `GmailAdapter` : Ajoute label `SPAM`, retire label `INBOX` via Gmail API
  - `OutlookAdapter` : Déplace vers dossier `junkemail` via Graph API
- **Orchestration** : `daemon._detect_phishing()` appelle `move_to_spam()` quand phishing détecté (`app/daemon.py`)

**Flux de traitement :**
```
Email reçu
    │
    ▼
┌─────────────────────┐
│ PhishingDetector    │ → Analyse liens, domaines, patterns
└────────┬────────────┘
         │
    ┌────┴────┐
    │ PHISHING?│
    └────┬────┘
     No  │  Yes
         │   │
         │   ▼
         │  ┌─────────────────────┐
         │  │ apply_label()       │ → Label "PHISHING" ajouté
         │  └────────┬────────────┘
         │           │
         │           ▼
         │  ┌─────────────────────┐
         │  │ move_to_spam()      │ → Déplacé vers spams
         │  └────────┬────────────┘
         │           │
         ▼           ▼
    Email safe    Email isolé
```

**Comportement graceful :**
- Si `move_to_spam()` échoue, un warning est loggé mais le traitement continue
- Si le provider ne supporte pas l'opération, retourne `False` (implémentation par défaut)

**Tests :**
- `tests/test_daemon_phishing_integration.py` : Tests d'intégration phishing + move_to_spam
- Vérifie que `move_to_spam()` est appelé pour les emails de phishing
- Vérifie le comportement graceful en cas d'échec
- Vérifie que les emails sûrs ne sont pas déplacés

---

### Follow-ups Automatiques

Système de détection des emails sans réponse, qui alimente les rappels et le label "Follow up" :

**Architecture Clean :**
- **Entités** : `SentEmail`, `FollowupSchedule`, `FollowupStats`, `FollowupStatus`, `FollowupPriority` (`app/domain/entities/followup.py`)
- **Port** : `FollowupTrackerPort` (`app/domain/ports/followup_port.py`)
- **Adapter** : `LegacyFollowupAdapter` (`app/infrastructure/adapters/followup_adapter.py`)
- **Orchestration** : `EmailDaemon.check_for_replies()` (`app/daemon.py`), endpoints reminder dans `app/api/auto_followup.py`

**Flux de traitement :**
```
┌─────────────────────────────────────────────────────────────────┐
│                        PRESENTATION                             │
│  app/daemon.py (EmailDaemon)                                    │
│  - Orchestrateur du flux                                        │
│  - Utilise FollowupTrackerPort (injection via Container)       │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  _run_main_loop() (daemon.py)                                   │
│       │                                                         │
│       └──→ check_for_replies() (daemon.py)                      │
│                 └──→ Détecte réponses reçues                    │
└─────────────────────────────────────────────────────────────────┘
```

**Configuration :**
```bash
FOLLOWUP_DELAY_DAYS=3  # Délai avant relance (défaut: 3 jours)
```

**Patterns utilisés :**
| Pattern | Localisation | Description |
|---------|-------------|-------------|
| **Port/Adapter** | `followup_port.py` / `followup_adapter.py` | Abstraction du stockage des follow-ups |
| **Dependency Injection** | `container.py` / `daemon.py:280-281` | Le Container injecte le tracker |
| **Dataclass Entity** | `domain/entities/followup.py` | Entités métier immutables |
| **Observer/Notifier** | `FollowupNotifier` dans `followups.py` | Notifications de relance |

**Détection des réponses :**
- Utilise `thread_id` (conversation email) pour associer réponses
- Fallback sur `sender` si thread_id non disponible
- Évite les doublons (ne relance pas un email déjà relancé)

**Tests :**
- `tests/test_followups.py` : 38 tests (schedules, calendrier, notifications)
- `tests/test_followups_auto.py` : Tests détection automatique (3 scénarios)
  - Email sans réponse après X jours → relance générée
  - Email avec réponse → pas de relance
  - Délai non atteint → pas de relance

---

### CryptographerPort (Séparation des responsabilités cryptographiques)

Interface pour isoler les opérations de chiffrement/déchiffrement dans un composant dédié :

**Objectif de sécurité :**
L'objectif est qu'**aucun agent unique n'ait accès à toute la chaîne de données**. En cas de fuite, sans la clé de déchiffrement, les données restent anonymes (RGPD).

**Architecture Clean :**
- **Port** : `CryptographerPort` (`app/domain/ports/cryptographer_port.py`)
- **Export** : `app/domain/ports/__init__.py`
- **Tests** : `tests/test_cryptographer_port.py` (45+ tests TDD)

**Interface CryptographerPort :**
```python
class CryptographerPort(ABC):
    @abstractmethod
    def encrypt(self, data: str) -> str:
        """Chiffre une chaîne de caractères."""

    @abstractmethod
    def decrypt(self, encrypted_data: str) -> str:
        """Déchiffre une chaîne de caractères."""

    @abstractmethod
    def encrypt_dict(self, data: dict[str, Any]) -> str:
        """Chiffre un dictionnaire en JSON chiffré."""

    @abstractmethod
    def decrypt_dict(self, encrypted_data: str) -> dict[str, Any]:
        """Déchiffre un JSON chiffré en dictionnaire."""

    @abstractmethod
    def hash_email(self, email: str) -> str:
        """Génère un hash irréversible pour anonymisation."""
```

**Patterns utilisés :**
- **Port/Adapter (Hexagonal)** : Le domaine définit l'interface, l'infrastructure implémente
- **Dependency Inversion** : Le domaine ne connaît que l'abstraction `CryptographerPort`
- **Interface Segregation** : Une seule responsabilité (cryptographie)

**Adapter FernetCryptographerAdapter :**
- **Adapter** : `FernetCryptographerAdapter` (`app/infrastructure/adapters/cryptographer_adapter.py`)
- **Export** : Ajouté dans `app/infrastructure/adapters/__init__.py`
- **Tests TDD** : `tests/infrastructure/adapters/test_cryptographer_adapter.py` (71 tests)

**Spécifications techniques :**
```python
class FernetCryptographerAdapter(CryptographerPort):
    def __init__(self, key: bytes | str | None = None):
        # Si key est None : génère une nouvelle clé Fernet
        # Si key est str : encode en bytes (URL-safe base64)
        # Si key est bytes : utilise directement
```

**Méthodes :**
| Méthode | Description |
|---------|-------------|
| `encrypt(data: str) -> str` | Chiffre une chaîne UTF-8 avec Fernet (AES-128-CBC) |
| `decrypt(encrypted_data: str) -> str` | Déchiffre, lève `ValueError` si échec |
| `encrypt_dict(data: dict) -> str` | Sérialise JSON puis chiffre |
| `decrypt_dict(encrypted_data: str) -> dict` | Déchiffre puis désérialise JSON |
| `hash_email(email: str) -> str` | Normalise (lowercase, strip) puis SHA-256 |

**Injection Container :**
```python
container = get_container()
cryptographer = container.get_cryptographer()

# Chiffrement
encrypted = cryptographer.encrypt("données sensibles")
original = cryptographer.decrypt(encrypted)

# Hash anonymisation
hashed = cryptographer.hash_email("user@example.com")
```

**Configuration clé de chiffrement :**
```bash
# Variable d'environnement (production)
export AGENTYS_ENCRYPTION_KEY="clé-base64-fernet"

# Si non définie : clé générée automatiquement (développement)
```

**Historique :**
1. ~~Créer l'interface `CryptographerPort`~~ ✅ (2026-01-01)
2. ~~Créer `CryptographerAdapter`~~ ✅ (2026-01-01)
3. ~~Faire implémenter `CryptographerPort` par l'adapter existant~~ ✅ (2026-01-01)
4. ~~Injecter via le container d'injection de dépendances~~ ✅ (2026-01-01)

---

### Détection de Données Sensibles (SensitiveDataDetectorAgent)

Agent IA pour empêcher la transmission d'informations sensibles ou confidentielles aux destinataires externes :

**Architecture Clean :**
- **Entités** : `SensitiveDataDetection`, `SensitiveDataItem`, `SensitiveDataType` (`app/domain/entities/sensitive_data.py`)
- **Port** : `SensitiveDataDetectorPort` (`app/domain/ports/sensitive_data_port.py`)
- **Agent** : `SensitiveDataDetectorAgent` (`app/agents.py`)
- **Tests** : `tests/test_sensitive_data_detector.py`

**Entité SensitiveDataDetection :**
```python
@dataclass
class SensitiveDataDetection:
    is_sensitive: bool                     # Données sensibles détectées ?
    confidence: float                      # Niveau de confiance (0.0 à 1.0)
    detected_items: List[SensitiveDataItem]  # Liste des données détectées
    analysis_summary: str                  # Résumé de l'analyse
```

**Enum SensitiveDataType :**
- `FINANCIAL` : Revenus, profits, budgets, données financières
- `PERSONAL` : Données personnelles (RGPD)
- `COMMERCIAL_SECRET` : Secrets commerciaux, stratégies
- `CREDENTIAL` : Mots de passe, tokens, clés API

**Port SensitiveDataDetectorPort :**
```python
class SensitiveDataDetectorPort(ABC):
    @abstractmethod
    def detect(self, draft_content: str, recipient: str) -> SensitiveDataDetection:
        """Analyse un brouillon pour détecter les données sensibles."""
        pass
```

**Intégration dans le pipeline daemon :**
```
┌───────────────┐
│ DrafterAgent  │ → Génère brouillon
└───────┬───────┘
        │
        ▼
┌──────────────┐
│ CriticAgent  │ → Évalue qualité
└───────┬──────┘
        │
        ▼
┌──────────────────────────────┐
│ SensitiveDataDetectorAgent   │ → Vérifie données sensibles
└───────┬──────────────────────┘
        │
   ┌────┴────┐
   │ SAFE?   │
   └────┬────┘
    Yes │ No
        │  └──→ ⚠️ Brouillon bloqué + WARNING log
        │
        ▼
  Brouillon créé
```

**Comportement :**
- Si données sensibles détectées : brouillon bloqué, warning dans les logs
- Types détectés : financial, personal, commercial_secret, credential
- Analyse IA du contenu avec niveau de confiance
- Vérifie le destinataire (interne vs externe à l'entreprise)

**Tests TDD :**
- Tests unitaires de l'entité `SensitiveDataDetection`
- Tests du port `SensitiveDataDetectorPort`
- Tests du use case `DetectSensitiveDataUseCase`
- Tests de l'agent `SensitiveDataDetectorAgent`
- Tests d'intégration avec le pipeline daemon

---

### Anonymisation des Données Sensibles (DataAnonymizer)

Service d'anonymisation sécurisée des données sensibles pour la mémoire du daemon :

**Architecture Clean :**
- **Entités** : `AnonymizedToken`, `SecureTokenMapping`, `AnonymizedResult`, `SecureAnonymizedData` (`app/domain/entities/anonymization.py`)
- **Service** : `DataAnonymizer` (`app/domain/services/anonymizer_service.py`)
- **Réutilisation** : Intégration avec `SensitiveDataDetection` existant (pas de duplication de la détection)
- **Tests** : `tests/test_anonymizer_service.py`

**Sécurité du chiffrement :**
- **Algorithme** : AES-GCM 256 bits (via `cryptography.hazmat`)
- **Nonce** : 12 bytes aléatoires par token (standard GCM)
- **Clé** : 32 bytes (AES-256)
- **Intégrité** : Hash SHA-256 du texte original pour vérification

**Entités immutables (frozen=True) :**

```python
@dataclass(frozen=True)
class AnonymizedToken:
    """Token public - NE CONTIENT PAS la valeur originale."""
    token_id: str           # UUID 8 chars
    data_type: SensitiveDataType
    # placeholder: "[ANON:TYPE:ID]"

@dataclass(frozen=True)
class SecureTokenMapping:
    """Mapping sécurisé - valeur chiffrée."""
    token_id: str
    encrypted_value: bytes  # AES-GCM encrypted
    salt: bytes             # Nonce GCM

@dataclass(frozen=True)
class AnonymizedResult:
    """Résultat public - sans valeurs sensibles."""
    anonymized_text: str
    tokens: tuple           # Tuple[AnonymizedToken]
    original_text_hash: str

@dataclass(frozen=True)
class SecureAnonymizedData:
    """Conteneur complet avec données chiffrées."""
    result: AnonymizedResult
    secure_mappings: tuple  # Tuple[SecureTokenMapping]
    key_id: str             # Hash de la clé (16 chars)
```

**API du service :**

```python
class DataAnonymizer:
    def anonymize(
        self, text: str, detection: SensitiveDataDetection, encryption_key: bytes
    ) -> SecureAnonymizedData:
        """Anonymise et chiffre les données sensibles."""

    def reveal(
        self, secure_data: SecureAnonymizedData, decryption_key: bytes
    ) -> str:
        """Révèle le texte original (nécessite la clé)."""
```

**Séparation sécuritaire :**
- `AnonymizedResult` : Peut être persisté dans `draft_history` (pas de données sensibles)
- `SecureTokenMapping` : Stocké séparément avec accès restreint
- La clé de chiffrement n'est JAMAIS stockée avec les données

**Diagramme des flux :**

```
┌───────────────────────────────────────────────────────────────┐
│                      ANONYMISATION                             │
│                                                                │
│  Texte + SensitiveDataDetection + Key                          │
│       │                                                        │
│       ▼                                                        │
│  ┌─────────────────────┐                                       │
│  │ DataAnonymizer      │                                       │
│  │   .anonymize()      │                                       │
│  └─────────┬───────────┘                                       │
│            │                                                   │
│            ├──► AnonymizedResult (public, persistable)         │
│            │      - anonymized_text: "Contact [ANON:EMAIL:x1]" │
│            │      - tokens: [AnonymizedToken...]               │
│            │                                                   │
│            └──► SecureTokenMapping[] (privé, accès restreint)  │
│                   - encrypted_value: b'\x8a...'                │
│                   - salt: b'\x12...'                           │
└───────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────┐
│                        REVEAL                                  │
│                                                                │
│  SecureAnonymizedData + Key                                    │
│       │                                                        │
│       ▼                                                        │
│  ┌─────────────────────┐                                       │
│  │ DataAnonymizer      │                                       │
│  │   .reveal()         │                                       │
│  └─────────┬───────────┘                                       │
│            │                                                   │
│            ▼                                                   │
│  "Contact john@example.com pour..."                            │
│                                                                │
│  ⚠️ InvalidCredentialsError si clé invalide                   │
└───────────────────────────────────────────────────────────────┘
```

**Tests TDD :**
- Anonymisation email → placeholder `[ANON:PERSONAL:xxxx]`
- Anonymisation IBAN → placeholder `[ANON:FINANCIAL:xxxx]`
- Reveal avec bonne clé → texte original
- Reveal avec mauvaise clé → `InvalidCredentialsError`
- Texte sans données sensibles → résultat unchanged
- Multiples occurrences → tokens uniques

**Prochaines étapes :**
1. ~~Créer le service DataAnonymizer~~ ✅ (2026-01-01)
2. ~~Intégrer dans DraftHistory~~ ✅ (2026-01-01)
3. ~~Créer le système de permissions pour reveal()~~ ✅ (2026-01-01)

---

### Intégration DataAnonymizer dans DraftHistory

**Architecture d'intégration :**

L'intégration respecte le pattern **Composition optionnelle** pour maintenir la rétrocompatibilité :

```python
@dataclass
class AnonymizationConfig:
    """Configuration optionnelle pour l'anonymisation dans DraftHistory."""
    anonymizer: DataAnonymizer
    detector: SensitiveDataDetectorPort
    encryption_key: bytes
```

**Modifications apportées à `app/history.py` :**

1. **Injection optionnelle** : `DraftHistory.__init__(anonymization_config: Optional[AnonymizationConfig] = None)`
2. **Méthode `_anonymize_record()`** : Anonymise les champs sensibles lors de `add()`
3. **Méthode `_reveal_record()`** : Révèle les données lors de `get_by_id()` et `get_all()`

**Champs anonymisés dans DraftRecord :**

| Champ | Type de données |
|-------|-----------------|
| `email_sender` | Adresse email |
| `email_preview` | Corps email (email, téléphone, IP) |
| `draft_v1` | Contenu brouillon V1 |
| `draft_final` | Contenu brouillon final |

**Schéma JSON enrichi :**

```json
{
  "id": "abc123",
  "email_sender": "[EMAIL_a1b2c3d4]",
  "email_preview": "Bonjour [EMAIL_e5f6g7h8]...",
  "draft_v1": "...",
  "draft_final": "...",
  "_anonymization_data": {
    "email_sender": { "result": {...}, "secure_mappings": [...], "key_id": "..." },
    "email_preview": { "result": {...}, "secure_mappings": [...], "key_id": "..." }
  }
}
```

**Conformité Clean Architecture :**

| Principe | Implémentation |
|----------|----------------|
| **Dependency Rule** | `DraftHistory` (Infrastructure) → `DataAnonymizer` (Domain Service) ✅ |
| **Rétrocompatibilité** | Config optionnelle, comportement identique sans anonymizer |
| **Single Responsibility** | `DraftHistory` délègue anonymisation à un objet dédié |
| **Open/Closed** | Extension via composition, pas de modification du contrat existant |

**Tests TDD (`tests/test_history.py`) :**
- `TestDraftHistoryAnonymization` : Tests anonymisation/révélation
- Rétrocompatibilité avec enregistrements non anonymisés
- Comportement sans config (identique à avant)

---

### Système de Permissions RBAC (CredentialManager)

Système RBAC (Role-Based Access Control) pour contrôler l'accès aux données dé-anonymisées :

**Architecture Clean :**
- **Entités** : `Permission`, `Role`, `Credential` (`app/domain/entities/permission.py`)
- **Service** : `CredentialManager` (`app/domain/services/credential_manager.py`)
- **Exception** : `InsufficientPermissionError` (`app/domain/exceptions.py`)
- **Tests** : `tests/test_credential_manager.py`

**Diagramme des entités :**

```
┌─────────────────────────────────────────────────────────────────┐
│                         ENTITÉS                                 │
├─────────────────────────────────────────────────────────────────┤
│  Role (Enum)                                                    │
│  ├── ADMIN    → Accès complet (can_reveal=True)                │
│  ├── AUDITOR  → Lecture logs uniquement (can_reveal=False)     │
│  └── VIEWER   → Données anonymisées uniquement (can_reveal=F)  │
├─────────────────────────────────────────────────────────────────┤
│  Permission (@dataclass frozen=True)                            │
│  ├── action: str           (ex: "reveal", "audit", "view")     │
│  ├── resource: str         (ex: "sensitive_data")              │
│  └── granted: bool                                              │
├─────────────────────────────────────────────────────────────────┤
│  Credential (@dataclass frozen=True)                            │
│  ├── credential_id: str    (UUID unique)                       │
│  ├── holder_id: str        (ID de l'utilisateur/service)       │
│  ├── role: Role                                                 │
│  ├── granted_at: datetime                                       │
│  └── expires_at: Optional[datetime]                            │
└─────────────────────────────────────────────────────────────────┘
```

**API du CredentialManager :**

```python
class CredentialManager:
    def grant(self, holder_id: str, role: Role,
              expires_at: Optional[datetime] = None) -> Credential:
        """Accorde une accréditation à un holder."""

    def revoke(self, credential_id: str) -> bool:
        """Révoque une accréditation. Retourne False si inexistante."""

    def can_reveal(self, holder_id: str) -> bool:
        """Vérifie si le holder peut appeler reveal()."""

    def get_credential(self, holder_id: str) -> Optional[Credential]:
        """Récupère l'accréditation d'un holder."""

    def require_reveal_permission(self, holder_id: str) -> None:
        """Lève InsufficientPermissionError si accès refusé."""
```

**Flux d'intégration avec DataAnonymizer :**

```
                    ┌──────────────────────┐
                    │    Caller Code       │
                    └──────────┬───────────┘
                               │
                               ▼
               ┌───────────────────────────────┐
               │  credential_manager.          │
               │  require_reveal_permission()  │
               └───────────────┬───────────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
    ┌─────────────────┐              ┌─────────────────────┐
    │   Permission    │              │ InsufficientPerm    │
    │    GRANTED      │              │      ERROR          │
    └────────┬────────┘              └─────────────────────┘
             │
             ▼
    ┌─────────────────────────┐
    │  anonymizer.reveal()    │
    │  (avec encryption_key)  │
    └─────────────────────────┘
```

**Règles de permissions par rôle :**

| Rôle | can_reveal() | Accès logs | Accès données |
|------|-------------|------------|---------------|
| `ADMIN` | ✅ Oui | ✅ Complet | ✅ Toutes |
| `AUDITOR` | ❌ Non | ✅ Lecture | ⚠️ Anonymisées |
| `VIEWER` | ❌ Non | ❌ Non | ⚠️ Anonymisées |

**Gestion de l'expiration :**
- Les credentials peuvent avoir une `expires_at` optionnelle
- `can_reveal()` retourne `False` pour les credentials expirés
- La vérification utilise `datetime.now(timezone.utc)`

**Conformité Clean Architecture :**

```
┌─────────────────────────────────────────────────────────────────┐
│  Domain Layer (pur Python, pas de dépendances externes)        │
│  ┌─────────────────┐  ┌─────────────────────────────────────┐  │
│  │ entities/       │  │ services/                           │  │
│  │ permission.py   │──│ credential_manager.py               │  │
│  │ (Role, Cred)    │  │ (utilise uniquement les entités)    │  │
│  └─────────────────┘  └─────────────────────────────────────┘  │
│           │                        │                            │
│           └────────────┬───────────┘                            │
│                        ▼                                        │
│              ┌─────────────────┐                                │
│              │ exceptions.py   │                                │
│              │ (DomainError)   │                                │
│              └─────────────────┘                                │
└─────────────────────────────────────────────────────────────────┘
```

**Tests TDD (`tests/test_credential_manager.py`) :**
- `TestRole` : Permissions par rôle (admin, auditor, viewer)
- `TestCredential` : Immutabilité, expiration
- `TestCredentialManager` : grant, revoke, can_reveal, require_reveal_permission

---

### Amélioration Continue Autonome (DraftCorrectionManager)

Système d'apprentissage automatique basé sur les corrections utilisateur des brouillons :

**Architecture Clean :**
- **Module** : `DraftCorrectionManager` (`app/draft_correction.py`)
- **Intégration** : `EmailDaemon` (`app/daemon.py`)
- **Tests** : `tests/test_daemon_correction_learning.py`

**Flux d'apprentissage :**
```
┌─────────────────────────────────────────────────────────────────┐
│  Email reçu                                                     │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────┐                                            │
│  │ _generate_draft │                                            │
│  │     │           │                                            │
│  │     ├──► apply_learned_corrections() ─► Améliore draft V1    │
│  │     │           avec patterns appris                         │
│  │     ▼           │                                            │
│  │  DrafterAgent   │                                            │
│  └─────────────────┘                                            │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────┐                                        │
│  │ _create_and_save    │ ─► Sauvegarde draft original           │
│  │      _draft()       │    dans draft_history                  │
│  └─────────────────────┘                                        │
│       │                                                         │
│       ▼                                                         │
│  [Brouillon créé dans boîte mail]                               │
│       │                                                         │
│       │ ... Utilisateur modifie le brouillon et l'envoie ...    │
│       │                                                         │
│       ▼                                                         │
│  ┌──────────────────────────┐                                   │
│  │ _check_draft_corrections │ ─► Comparaison via                │
│  │          ()              │    detect_user_modification()     │
│  └──────────────────────────┘                                   │
│       │                                                         │
│       ├──► Si modification détectée: record_correction()        │
│       │                                                         │
│       ▼                                                         │
│  [Patterns mis à jour] ─► Utilisés pour les prochains drafts    │
└─────────────────────────────────────────────────────────────────┘
```

**API DraftCorrectionManager :**
| Méthode | Usage | Paramètres |
|---------|-------|------------|
| `get_correction_manager()` | Singleton factory | - |
| `detect_user_modification(original, current, threshold=0.1)` | Détecte si modifié >10% | Deux textes |
| `record_correction(original, corrected, context)` | Enregistre + apprend | Original, corrigé, contexte |
| `apply_learned_corrections(draft, context, min_confidence=0.6)` | Applique patterns | Draft, contexte |

**Points d'intégration dans EmailDaemon :**

1. **Initialisation (`__post_init__`)** :
   - Import et initialisation du `DraftCorrectionManager` via singleton

2. **Application des corrections (`_generate_draft`)** :
   - Appliquer les patterns appris AVANT la critique du CriticAgent
   - Log `🎓 X correction(s) appliquée(s)` si patterns appliqués

3. **Détection des modifications (`poll_user_drafts`)** :
   - Comparer le brouillon actuel avec l'original stocké dans `draft_history`
   - Si modification détectée → `record_correction()`

4. **Méthode privée `_check_draft_corrections`** :
   - Récupérer les brouillons envoyés (via provider)
   - Comparer avec l'historique (`draft_history`)
   - Détecter les modifications (`detect_user_modification`)
   - Enregistrer les corrections (`record_correction`)

**Conformité Clean Architecture :**
- ✅ **Dependency Rule respectée** : `DraftCorrectionManager` est dans la couche Application
- ✅ **Injection via singleton** : Pattern identique à `LearningService`
- ✅ **Pas de couplage infrastructure** : Persistance via JSON (détail interne)
- ✅ **Interface implicite** : API claire et stable

**Tests TDD (`tests/test_daemon_correction_learning.py`) :**
- `test_correction_manager_initialized` - Initialisation dans EmailDaemon
- `test_apply_corrections_on_draft_generation` - Application dans `_generate_draft`
- `test_detect_user_modification_on_sent_draft` - Détection modifications
- `test_record_correction_called_when_modified` - Enregistrement corrections
- `test_no_correction_recorded_when_unchanged` - Pas de correction si inchangé
- `test_correction_context_includes_email_metadata` - Contexte avec métadonnées
