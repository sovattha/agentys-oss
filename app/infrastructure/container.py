# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Conteneur d'injection de dépendances (DI Container).

Ce module centralise la création des dépendances de l'application.
Il respecte les principes de Clean Architecture :
- Les dépendances pointent vers l'intérieur (Dependency Rule)
- Les use cases reçoivent des abstractions (ports), pas des implémentations concrètes
- Le container est le seul point de câblage des dépendances

Usage:
    container = get_container()
    use_case = container.get_process_use_case()
    result = use_case.execute(email)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Callable

if TYPE_CHECKING:
    from app.application.email_template import (
        CreateTemplateUseCase,
        DeleteTemplateUseCase,
        GetTemplateStatsUseCase,
        GetTemplateUseCase,
        ListTemplatesUseCase,
        MatchTemplateUseCase,
        RenderTemplateUseCase,
        UpdateTemplateUseCase,
    )
    from app.application.realtime_edit import (
        ApplySuggestionUseCase,
        CloseEditSessionUseCase,
        GetEditSessionUseCase,
        GetSuggestionUseCase,
        ProcessTextChangeUseCase,
        StartEditSessionUseCase,
    )
    from app.domain.ports.commitment_port import CommitmentTrackerPort
    from app.domain.ports.email_template import EmailTemplateStorePort
    from app.infrastructure.adapters.label_store import LabelStore
    from app.db.repositories.email_repository import EmailRepository

# Domain Ports (abstractions)
from app.domain.ports import (
    LLMPort,
    EmailPort,
    TimeProvider,
    DeviceStorePort,
    WizardConfigPort,
    MarketplaceAgentPort,
    AgentPackPort,
    AgentInstallationPort,
    AgentReviewPort,
    PublisherPort,
    UserCorrectionPort,
    UserFeedbackPort,
    CorrectionPatternPort,
    ImprovementModelPort,
    FineTuningSessionPort,
    FineTuningAnalyzerPort,
    MobileSessionPort,
    MobileSyncPort,
    MobileDraftActionPort,
    MobileAnalyticsPort,
    MobileUserPreferencesPort,
    MobileAppConfigPort,
    ClassifierPort,
    PrioritizationPort,
    EmailAnalyzerPort,
    LearningPatternStorePort,
    AdjustmentStorePort,
    LearningFeedbackProviderPort,
    EditSessionStorePort,
    CryptographerPort,
    # Legacy Migration Ports
    DraftHistoryPort,
    AnalyticsPort,
    TokenCounterPort,
    ProcessedEmailsTrackerPort,
    ProcessedDraftsTrackerPort,
    TaskPort,
    # Pending Drafts
    PendingDraftStorePort,
    # Contact Analysis
    ContactAnalyzerPort,
)

# Infrastructure - Clock (import au niveau module pour lisibilité)
from app.infrastructure.clock import SystemClock

# Domain Entities
from app.domain.entities import TokenUsage

# Adapters (implémentations concrètes)
from app.adapters.llm import (
    ClaudeAdapter,
    ClaudeCodeAdapter,
    MockLLMAdapter,
    OllamaAdapter,
    get_llm_adapter,
)

# Application Layer - Core Use Cases
from app.application import (
    # Core Email Processing
    DraftEmailUseCase,
    CritiqueEmailUseCase,
    ProcessEmailUseCase,
    RefineEmailUseCase,
    RegenerateEmailUseCase,
    ClassifyEmailUseCase,
    PrioritizeEmailUseCase,
    AnalyzeEmailUseCase,
    HealthCheckUseCase,
    CompleteDraftUseCase,
    PushNotificationService,
    # Email Labels
    LabelEmailUseCase,
    LearnLabelingRuleUseCase,
    # Contact Analysis
    AnalyzeContactHistoryUseCase,
    # Wizard Configuration
    SaveWizardConfigUseCase,
    LoadWizardConfigUseCase,
    CreateWizardConfigUseCase,
    ToggleAgentUseCase,
    ImportKnowledgeBaseUseCase,
    ExportConfigUseCase,
    # Marketplace
    RegisterPublisherUseCase,
    GetPublisherUseCase,
    PublishAgentUseCase,
    SubmitAgentForReviewUseCase,
    ApproveAgentUseCase,
    UpdateAgentUseCase,
    SearchAgentsUseCase,
    GetAgentDetailsUseCase,
    ListFeaturedAgentsUseCase,
    ListAgentsByCategoryUseCase,
    InstallAgentUseCase,
    UninstallAgentUseCase,
    ListInstalledAgentsUseCase,
    RecordAgentUsageUseCase,
    SubmitReviewUseCase,
    RespondToReviewUseCase,
    ListAgentReviewsUseCase,
    CreateAgentPackUseCase,
    InstallPackUseCase,
    # Fine-tuning
    RecordCorrectionUseCase,
    RecordFeedbackUseCase,
    ExtractPatternsUseCase,
    CreateImprovementModelUseCase,
    ActivateModelUseCase,
    DisableModelUseCase,
    ApplyImprovementsUseCase,
    GetPromptEnhancementsUseCase,
    RunFineTuningSessionUseCase,
    GetFineTuningStatsUseCase,
    ListPatternsUseCase,
    ListModelsUseCase,
    # Mobile Companion
    StartMobileSessionUseCase,
    EndMobileSessionUseCase,
    TouchSessionUseCase,
    SyncMobileDataUseCase,
    GetDraftDetailsUseCase,
    GetPendingDraftsUseCase,
    ApplyDraftActionUseCase,
    ApplyBatchActionsUseCase,
    MarkDraftReadUseCase,
    TrackMobileEventUseCase,
    GetMobileStatsUseCase,
    GetPreferencesUseCase,
    UpdatePreferencesUseCase,
    GetAppConfigUseCase,
    UpdateAppConfigUseCase,
    MobileCompanionService,
)

# Learning Use Cases
from app.application.learning import (
    AnalyzeFeedbackUseCase,
    ExtractPatternsUseCase as LearningExtractPatternsUseCase,
    ShouldRequireReviewUseCase,
    GenerateAdjustmentUseCase,
    GetLearningStatsUseCase,
    EnhancePromptUseCase,
    GetActiveAdjustmentsUseCase,
)

# Learning Service
from app.domain.services.learning_service import LearningService

from .config import Config


@dataclass
class Container:
    """
    Conteneur d'injection de dépendances (DI Container).

    Centralise la création et le câblage des composants.
    Suit le pattern Composition Root de Clean Architecture.

    Responsabilités:
    - Créer les adapters (implémentations concrètes)
    - Câbler les use cases avec leurs dépendances
    - Gérer le cycle de vie des singletons

    Note: Utilise lazy loading pour les dépendances coûteuses.
    """
    config: Config = field(default_factory=Config.from_env)

    # Core dependencies (lazy loaded)
    _llm: Optional[LLMPort] = field(default=None, repr=False)
    _llm_label: Optional[LLMPort] = field(default=None, repr=False)
    _llm_sonnet: Optional[LLMPort] = field(default=None, repr=False)
    # Clés spécialisées (traçabilité coûts)
    _llm_drafting: Optional[LLMPort] = field(default=None, repr=False)
    _llm_drafting_smart: Optional[LLMPort] = field(default=None, repr=False)
    _llm_onboarding: Optional[LLMPort] = field(default=None, repr=False)
    _llm_onboarding_label: Optional[LLMPort] = field(default=None, repr=False)
    # Worker tier for onboarding agents (Profile/Knowledge/Style/Label).
    # Migrated 2026-05-05 from Sonnet to Haiku (~22× cost reduction). Held
    # behind ONBOARDING_WORKER_TIER env so we can roll back instantly to
    # "smart" if eval_onboarding.py shows a regression > 5 pts. Judge
    # (EvaluationAgent) intentionally stays on `_llm_onboarding` (Sonnet)
    # so writer ≠ judge — see lesson 52524115.
    _llm_onboarding_worker: Optional[LLMPort] = field(default=None, repr=False)
    _llm_background: Optional[LLMPort] = field(default=None, repr=False)
    # Smart-router escalation target for label classification (Sonnet, billed
    # under the background API key for cost categorisation).
    _llm_background_smart: Optional[LLMPort] = field(default=None, repr=False)
    _knowledge_base: Optional[str] = field(default=None, repr=False)
    _second_brain: Optional["SecondBrainPort"] = field(default=None, repr=False)  # noqa: F821
    _token_usage: TokenUsage = field(default_factory=TokenUsage)
    _clock: Optional[TimeProvider] = field(default=None, repr=False)

    # Store singletons (lazy loaded)
    _wizard_config_store: Optional[WizardConfigPort] = field(default=None, repr=False)
    _device_store: Optional[DeviceStorePort] = field(default=None, repr=False)
    _cryptographer: Optional[CryptographerPort] = field(default=None, repr=False)

    # Marketplace stores (lazy loaded)
    _marketplace_agent_store: Optional[MarketplaceAgentPort] = field(default=None, repr=False)
    _agent_pack_store: Optional[AgentPackPort] = field(default=None, repr=False)
    _agent_installation_store: Optional[AgentInstallationPort] = field(default=None, repr=False)
    _agent_review_store: Optional[AgentReviewPort] = field(default=None, repr=False)
    _publisher_store: Optional[PublisherPort] = field(default=None, repr=False)

    # Fine-tuning stores (lazy loaded)
    _user_correction_store: Optional[UserCorrectionPort] = field(default=None, repr=False)
    _user_feedback_store: Optional[UserFeedbackPort] = field(default=None, repr=False)
    _correction_pattern_store: Optional[CorrectionPatternPort] = field(default=None, repr=False)
    _improvement_model_store: Optional[ImprovementModelPort] = field(default=None, repr=False)
    _fine_tuning_session_store: Optional[FineTuningSessionPort] = field(default=None, repr=False)
    _fine_tuning_analyzer: Optional[FineTuningAnalyzerPort] = field(default=None, repr=False)

    # Mobile companion stores (lazy loaded)
    _mobile_session_store: Optional[MobileSessionPort] = field(default=None, repr=False)
    _mobile_sync_store: Optional[MobileSyncPort] = field(default=None, repr=False)
    _mobile_draft_action_store: Optional[MobileDraftActionPort] = field(default=None, repr=False)
    _mobile_analytics_store: Optional[MobileAnalyticsPort] = field(default=None, repr=False)
    _mobile_preferences_store: Optional[MobileUserPreferencesPort] = field(default=None, repr=False)
    _mobile_config_store: Optional[MobileAppConfigPort] = field(default=None, repr=False)

    # Classification & Prioritization adapters (lazy loaded)
    _classifier: Optional[ClassifierPort] = field(default=None, repr=False)
    _prioritizer: Optional[PrioritizationPort] = field(default=None, repr=False)
    _email_analyzer: Optional[EmailAnalyzerPort] = field(default=None, repr=False)

    # Learning stores (lazy loaded)
    _learning_pattern_store: Optional[LearningPatternStorePort] = field(default=None, repr=False)
    _adjustment_store: Optional[AdjustmentStorePort] = field(default=None, repr=False)
    _learning_feedback_provider: Optional[LearningFeedbackProviderPort] = field(default=None, repr=False)

    # Real-time edit store (lazy loaded)
    _realtime_edit_store: Optional[EditSessionStorePort] = field(default=None, repr=False)

    # Legacy migration adapters (lazy loaded)
    _draft_history: Optional[DraftHistoryPort] = field(default=None, repr=False)
    _analytics: Optional[AnalyticsPort] = field(default=None, repr=False)
    _token_counter: Optional[TokenCounterPort] = field(default=None, repr=False)
    _processed_emails_tracker: Optional[ProcessedEmailsTrackerPort] = field(default=None, repr=False)
    _processed_drafts_tracker: Optional[ProcessedDraftsTrackerPort] = field(default=None, repr=False)
    _commitment_tracker: Optional["CommitmentTrackerPort"] = field(default=None, repr=False)

    # Task repository (lazy loaded)
    _task_repository: Optional[TaskPort] = field(default=None, repr=False)

    # Pending draft store (lazy loaded)
    _pending_draft_store: Optional[PendingDraftStorePort] = field(default=None, repr=False)

    # Label store (lazy loaded)
    _label_store: Optional["LabelStore"] = field(default=None, repr=False)

    # =========================================================================
    # Core Properties (Lazy Loading)
    # =========================================================================

    @property
    def llm(self) -> LLMPort:
        """Retourne le provider LLM configuré (lazy loading)."""
        if self._llm is None:
            self._llm = self._create_llm()
        return self._llm

    @property
    def llm_label(self) -> LLMPort:
        """Retourne un LLM léger pour le labeling (Haiku pour Claude, default pour Ollama)."""
        if self._llm_label is None:
            self._llm_label = self._create_llm_label()
        return self._llm_label

    @property
    def llm_sonnet(self) -> LLMPort:
        """Retourne un LLM Sonnet pour les emails tone-sensitive (lazy loading).

        DEPRECATED: prefer `llm_onboarding` which routes to the onboarding API key.
        """
        if self._llm_sonnet is None:
            self._llm_sonnet = self._create_llm_sonnet()
        return self._llm_sonnet

    # -------------------------------------------------------------------------
    # Semantic LLM factories (5-key cost traceability)
    # Each routes to the matching ANTHROPIC_API_KEY_* so the Anthropic console
    # shows per-category spend. Claude-code / Ollama providers fall back to the
    # single-provider behavior (these run on the user's machine, not Anthropic).
    # -------------------------------------------------------------------------

    @property
    def llm_drafting(self) -> LLMPort:
        """LLM pour le drafting (DrafterAgent + CriticAgent). Haiku par défaut, clé drafting.

        Audit 2026-05-06: when ``COST_ENFORCEMENT_ENABLED=true`` the LLM
        is wrapped in :class:`CostGatedLLM` which raises
        ``CostBudgetExceededError`` if the global monthly or per-user
        daily cap is hit. Off by default so the wiring is invisible
        until ops flips the switch.
        """
        if self._llm_drafting is None:
            inner = self._create_llm_categorized(
                tier="label", api_key=self.config.anthropic_api_key_drafting
            )
            self._llm_drafting = self._maybe_cost_gate(inner)
        return self._llm_drafting

    @property
    def llm_drafting_smart(self) -> LLMPort:
        """LLM Sonnet pour drafting tone-sensitive (clé drafting). Disponible si besoin."""
        if self._llm_drafting_smart is None:
            inner = self._create_llm_categorized(
                tier="smart", api_key=self.config.anthropic_api_key_drafting
            )
            self._llm_drafting_smart = self._maybe_cost_gate(inner)
        return self._llm_drafting_smart

    @staticmethod
    def _maybe_cost_gate(inner: LLMPort) -> LLMPort:
        """Wrap LLM ports with enabled runtime gates.

        Lazy imports keep optional enforcement modules out of the import graph
        for callers (tests, scripts) that don't touch these code paths.
        """
        # The mock LLM incurs no real API spend, so cost-gating it is pointless
        # and would obscure the adapter type for tests/dev/load-runs booted with
        # AGENTYS_MOCK_LLM=true (enforcement now defaults ON in prod).
        if isinstance(inner, MockLLMAdapter):
            return inner

        wrapped = inner
        try:
            from app.infrastructure.cost_enforcer import (
                CostGatedLLM, _is_enforcement_enabled,
            )
            if _is_enforcement_enabled():
                wrapped = CostGatedLLM(wrapped)  # type: ignore[assignment]
        except Exception:
            pass
        try:
            from app.infrastructure.entitlement_gate import (
                EntitlementGatedLLM, _is_billing_enforcement_enabled,
            )
            if _is_billing_enforcement_enabled():
                wrapped = EntitlementGatedLLM(wrapped)  # type: ignore[assignment]
        except Exception:
            pass
        return wrapped

    @property
    def llm_onboarding(self) -> LLMPort:
        """LLM Sonnet pour l'onboarding (5 agents). Clé onboarding."""
        if self._llm_onboarding is None:
            inner = self._create_llm_categorized(
                tier="smart", api_key=self.config.anthropic_api_key_onboarding
            )
            self._llm_onboarding = self._maybe_cost_gate(inner)
        return self._llm_onboarding

    @property
    def llm_onboarding_label(self) -> LLMPort:
        """LLM Haiku pour l'onboarding manager (classification pendant l'onboarding). Clé onboarding."""
        if self._llm_onboarding_label is None:
            inner = self._create_llm_categorized(
                tier="label", api_key=self.config.anthropic_api_key_onboarding
            )
            self._llm_onboarding_label = self._maybe_cost_gate(inner)
        return self._llm_onboarding_label

    @property
    def llm_onboarding_worker(self) -> LLMPort:
        """LLM for onboarding worker agents (Profile / Knowledge / Style / Label).

        Default tier = "label" (Haiku) — ~22× cheaper than Sonnet. Override
        with ONBOARDING_WORKER_TIER=smart to roll back to Sonnet if eval
        regresses. EvaluationAgent intentionally keeps `llm_onboarding`
        (Sonnet) — judge ≠ writer (cf. eval-harness.md lesson 52524115:
        same-model self-eval added +5–8 pts of false positives).
        """
        if self._llm_onboarding_worker is None:
            tier = os.getenv("ONBOARDING_WORKER_TIER", "label").strip().lower()
            if tier not in ("label", "smart"):
                tier = "label"
            inner = self._create_llm_categorized(
                tier=tier, api_key=self.config.anthropic_api_key_onboarding
            )
            self._llm_onboarding_worker = self._maybe_cost_gate(inner)
        return self._llm_onboarding_worker

    @property
    def llm_background(self) -> LLMPort:
        """LLM Haiku pour classifiers background per-email (FAQ, Classifier, TaskExtractor, etc.). Clé background."""
        if self._llm_background is None:
            inner = self._create_llm_categorized(
                tier="label", api_key=self.config.anthropic_api_key_background
            )
            self._llm_background = self._maybe_cost_gate(inner)
        return self._llm_background

    @property
    def llm_background_smart(self) -> LLMPort:
        """LLM Sonnet pour escalation depuis le tier label background.

        Used by ``LabelEmailUseCase.llm_premium`` when Haiku returns a
        confidence below ``smart_route_threshold`` — typically <5% of
        emails routed to the LLM. Billed under the background API key so
        the spend lands in the same line item as primary classification.
        """
        if self._llm_background_smart is None:
            inner = self._create_llm_categorized(
                tier="smart", api_key=self.config.anthropic_api_key_background
            )
            self._llm_background_smart = self._maybe_cost_gate(inner)
        return self._llm_background_smart

    @property
    def second_brain(self):  # -> SecondBrainPort (lazy import to avoid circulars)
        """Retourne l'adapter SecondBrain (lazy loading).

        Agrège les 4 sources de mémoire (MemPalace vectoriel, graphe MCP,
        memoire.md, KB par compte) derrière une façade unique. Voir issue #261.
        Les agents génériques (migration à venir) lisent leur contexte via
        `get_container().second_brain.retrieve(role, task)`.
        """
        if self._second_brain is None:
            from app.config import (
                SECOND_BRAIN_ACCOUNT_DB,
                SECOND_BRAIN_GRAPH_DB,
                SECOND_BRAIN_MEMOIRE_MD,
                SECOND_BRAIN_MEMPALACE_DB,
            )
            from app.infrastructure.second_brain_adapter import (
                SecondBrainAdapter,
                SecondBrainConfig,
            )
            self._second_brain = SecondBrainAdapter(
                config=SecondBrainConfig(
                    mempalace_db_path=SECOND_BRAIN_MEMPALACE_DB,
                    mempalace_graph_path=SECOND_BRAIN_GRAPH_DB,
                    memoire_md_path=SECOND_BRAIN_MEMOIRE_MD,
                    account_db_path=SECOND_BRAIN_ACCOUNT_DB,
                ),
            )
        return self._second_brain

    @property
    def knowledge_base(self) -> str:
        """Retourne la base de connaissances (lazy loading)."""
        if self._knowledge_base is None:
            self._knowledge_base = self._load_knowledge_base()
        return self._knowledge_base

    @property
    def token_usage(self) -> TokenUsage:
        """Retourne le compteur de tokens partagé."""
        return self._token_usage

    @property
    def token_counter(self) -> "TokenCounterPort":
        """Per-agent breakdown adapter (lazy alias for get_token_counter()).

        Returning the same singleton as get_token_counter() — exposed as a
        property for symmetry with token_usage. Used by ``_track_token_usage``
        in agents.py to record (input, output, model, agent) tuples after
        every LLM completion (audit 2026-05-05).
        """
        return self.get_token_counter()

    @property
    def data_dir(self) -> Path:
        """Retourne le répertoire de données.

        Honore AGENTYS_DATA_DIR (volume persistant en prod Railway :
        /data/agentys). Sans ça, tous les JSON (labels/assignments, learning,
        marketplace, templates…) écrivent dans /app/data qui est wipé à chaque
        redeploy.
        """
        env_dir = os.environ.get("AGENTYS_DATA_DIR")
        if env_dir:
            return Path(env_dir)
        return self.config.project_root / "data"

    @property
    def clock(self) -> TimeProvider:
        """
        Retourne le TimeProvider (lazy loading).

        Par défaut, utilise SystemClock qui retourne l'heure système réelle.
        Pour les tests, utilisez set_clock() pour injecter un FakeClock.

        Returns:
            TimeProvider: Instance de clock configurée.
        """
        if self._clock is None:
            self._clock = SystemClock()
        return self._clock

    def set_clock(self, clock: TimeProvider) -> None:
        """
        Injecte un TimeProvider personnalisé.

        Utile pour les tests avec FakeClock permettant de contrôler le temps.

        Args:
            clock: Instance de TimeProvider à utiliser.

        Example:
            >>> from app.infrastructure.clock import FakeClock
            >>> container.set_clock(FakeClock(datetime(2024, 1, 1)))
        """
        self._clock = clock

    # =========================================================================
    # Private Factory Methods
    # =========================================================================

    def _create_llm(self) -> LLMPort:
        """Crée le provider LLM selon la configuration."""
        if self._mock_llm_enabled():
            return self._create_mock_llm(tier="default")
        if self.config.llm_provider == "claude-code":
            return ClaudeCodeAdapter(model="sonnet")
        elif self.config.llm_provider == "ollama":
            return OllamaAdapter(
                model=self.config.llm_model,
                base_url=self.config.ollama_base_url
            )
        else:
            return ClaudeAdapter(
                model=self.config.llm_model,
                api_key=self.config.anthropic_api_key
            )

    def _create_llm_label(self) -> LLMPort:
        """Crée un LLM léger pour le labeling (Haiku si Claude, sinon default)."""
        if self._mock_llm_enabled():
            return self._create_mock_llm(tier="label")
        if self.config.llm_provider == "claude-code":
            return ClaudeCodeAdapter(model="haiku")
        elif self.config.llm_provider == "ollama":
            # Ollama: même modèle pour tout
            return self.llm
        else:
            # Claude: Haiku pour labeling (rapide, pas cher)
            from app.config import CLAUDE_MODEL_LABEL
            return ClaudeAdapter(
                model=CLAUDE_MODEL_LABEL,
                api_key=self.config.anthropic_api_key,
            )

    def _create_llm_sonnet(self) -> LLMPort:
        """Crée un LLM Sonnet pour les emails tone-sensitive."""
        if self._mock_llm_enabled():
            return self._create_mock_llm(tier="smart")
        if self.config.llm_provider == "claude-code":
            return ClaudeCodeAdapter(model="sonnet")
        elif self.config.llm_provider == "ollama":
            return self.llm
        else:
            from app.config import CLAUDE_MODEL_FAST
            return ClaudeAdapter(
                model=CLAUDE_MODEL_FAST,
                api_key=self.config.anthropic_api_key,
            )

    def _create_llm_categorized(self, *, tier: str, api_key: Optional[str]) -> LLMPort:
        """Crée un LLM avec tier + clé spécialisée.

        Args:
            tier: "label" (Haiku) ou "smart" (Sonnet).
            api_key: Clé Anthropic à utiliser (catégorisée). Ignorée pour claude-code/ollama.
        """
        if self._mock_llm_enabled():
            return self._create_mock_llm(tier=tier)
        if self.config.llm_provider == "claude-code":
            model = "haiku" if tier == "label" else "sonnet"
            return ClaudeCodeAdapter(model=model)
        if self.config.llm_provider == "ollama":
            return self.llm  # Ollama ignore le tier
        from app.config import CLAUDE_MODEL_FAST, CLAUDE_MODEL_LABEL
        model = CLAUDE_MODEL_LABEL if tier == "label" else CLAUDE_MODEL_FAST
        return ClaudeAdapter(model=model, api_key=api_key)

    def _mock_llm_enabled(self) -> bool:
        return (
            self.config.llm_provider == "mock"
            or os.getenv("AGENTYS_MOCK_LLM", "").strip().lower()
            in {"1", "true", "yes", "on"}
        )

    def _create_mock_llm(self, *, tier: str) -> LLMPort:
        return MockLLMAdapter(tier=tier)

    def _load_knowledge_base(self) -> str:
        """Charge la base de connaissances."""
        kb_path = self.config.knowledge_path

        if kb_path.exists():
            return kb_path.read_text(encoding="utf-8")

        # Créer un fichier par défaut
        default_content = """# Base de Connaissances

## Identité
- Assistant de réponse email

## Règles
- Répondre dans la même langue que l'email reçu
- Être professionnel et concis
- Ne pas inventer d'informations
"""
        kb_path.parent.mkdir(parents=True, exist_ok=True)
        kb_path.write_text(default_content, encoding="utf-8")
        return default_content

    # =========================================================================
    # Store Factories (Infrastructure Layer)
    # =========================================================================

    def get_wizard_config_store(self) -> WizardConfigPort:
        """Retourne le store de configuration wizard (singleton)."""
        if self._wizard_config_store is None:
            from app.infrastructure.wizard_config_store import JsonFileWizardConfigStore
            filepath = self.data_dir / "wizard_config.json"
            self._wizard_config_store = JsonFileWizardConfigStore(filepath)
        return self._wizard_config_store

    def get_device_store(self) -> DeviceStorePort:
        """Retourne le store de devices push (singleton)."""
        if self._device_store is None:
            from app.infrastructure.device_store import JsonFileDeviceStore
            filepath = self.data_dir / "push_devices.json"
            self._device_store = JsonFileDeviceStore(filepath)
        return self._device_store

    def get_cryptographer(self) -> CryptographerPort:
        """Retourne le cryptographer (singleton).

        Le cryptographer Fernet est utilisé pour le chiffrement applicatif
        (history anonymization, OAuth token storage helpers). Il a son propre
        env var (`AGENTYS_FERNET_KEY` ou `OAUTH_TOKEN_ENCRYPTION_KEY`) au format
        Fernet (44 chars urlsafe-base64).

        CASA P0 (#206 follow-up): l'ancienne version lisait `AGENTYS_ENCRYPTION_KEY`
        directement, mais cet env var est maintenant le hex SQLCipher (64 chars).
        Le passer brut à Fernet crash avec `ValueError: Fernet key must be 32
        url-safe base64-encoded bytes`. On lit donc d'abord les vars dédiées Fernet,
        puis on rejette explicitement un `AGENTYS_ENCRYPTION_KEY` au format hex
        (signal qu'il s'agit de la clé SQLCipher mal câblée).

        SECURITY: la clé doit être configurée en prod. Sans clé, une clé éphémère
        est générée et les données chiffrées seront perdues au redémarrage.
        """
        if self._cryptographer is None:
            import logging
            import os
            import re

            from app.infrastructure.adapters.cryptographer_adapter import FernetCryptographerAdapter

            # Priorité : var dédiée Fernet > OAuth token key (legacy alias) > rejet
            # explicite d'AGENTYS_ENCRYPTION_KEY au format hex (= SQLCipher).
            key = os.environ.get("AGENTYS_FERNET_KEY") or os.environ.get("OAUTH_TOKEN_ENCRYPTION_KEY")

            if not key:
                _legacy = os.environ.get("AGENTYS_ENCRYPTION_KEY")
                if _legacy and re.fullmatch(r"[0-9a-fA-F]{64}", _legacy):
                    raise RuntimeError(
                        "SECURITY ERROR: AGENTYS_ENCRYPTION_KEY is in SQLCipher hex "
                        "format (64 chars), which is NOT a valid Fernet key. "
                        "Set AGENTYS_FERNET_KEY (or OAUTH_TOKEN_ENCRYPTION_KEY) "
                        "to a Fernet key generated via: "
                        "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\". "
                        "See docs/security/data-at-rest.md."
                    )
                # Backwards-compat: accept AGENTYS_ENCRYPTION_KEY only if it parses
                # as a Fernet key (44-char urlsafe-b64). This covers legacy deploys
                # where the var name is reused for Fernet.
                if _legacy:
                    key = _legacy

            if not key:
                from app.api._auth_helpers import is_production
                if is_production():
                    raise RuntimeError(
                        "SECURITY ERROR: AGENTYS_FERNET_KEY (or OAUTH_TOKEN_ENCRYPTION_KEY) "
                        "must be set in production. Generate via: "
                        "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                    )
                logging.warning(
                    "SECURITY WARNING: AGENTYS_FERNET_KEY/OAUTH_TOKEN_ENCRYPTION_KEY not set. "
                    "Using ephemeral key - encrypted data will be LOST on restart. "
                    "Set AGENTYS_FERNET_KEY for production use."
                )

            self._cryptographer = FernetCryptographerAdapter(key)
        return self._cryptographer

    def _init_marketplace_stores(self) -> None:
        """Initialise tous les stores marketplace."""
        if self._marketplace_agent_store is None:
            from app.infrastructure.marketplace_store import (
                JsonMarketplaceAgentStore,
                JsonAgentPackStore,
                JsonAgentInstallationStore,
                JsonAgentReviewStore,
                JsonPublisherStore,
            )
            marketplace_dir = self.data_dir / "marketplace"
            marketplace_dir.mkdir(parents=True, exist_ok=True)

            self._marketplace_agent_store = JsonMarketplaceAgentStore(
                marketplace_dir / "agents.json"
            )
            self._agent_pack_store = JsonAgentPackStore(
                marketplace_dir / "packs.json"
            )
            self._agent_installation_store = JsonAgentInstallationStore(
                marketplace_dir / "installations.json"
            )
            self._agent_review_store = JsonAgentReviewStore(
                marketplace_dir / "reviews.json"
            )
            self._publisher_store = JsonPublisherStore(
                marketplace_dir / "publishers.json"
            )

    def get_marketplace_agent_store(self) -> MarketplaceAgentPort:
        """Retourne le store d'agents marketplace."""
        self._init_marketplace_stores()
        return self._marketplace_agent_store

    def get_agent_pack_store(self) -> AgentPackPort:
        """Retourne le store de packs d'agents."""
        self._init_marketplace_stores()
        return self._agent_pack_store

    def get_agent_installation_store(self) -> AgentInstallationPort:
        """Retourne le store d'installations d'agents."""
        self._init_marketplace_stores()
        return self._agent_installation_store

    def get_agent_review_store(self) -> AgentReviewPort:
        """Retourne le store d'avis d'agents."""
        self._init_marketplace_stores()
        return self._agent_review_store

    def get_publisher_store(self) -> PublisherPort:
        """Retourne le store d'éditeurs."""
        self._init_marketplace_stores()
        return self._publisher_store

    def _init_fine_tuning_stores(self) -> None:
        """Initialise tous les stores fine-tuning."""
        if self._user_correction_store is None:
            from app.infrastructure.fine_tuning_store import (
                JsonUserCorrectionStore,
                JsonUserFeedbackStore,
                JsonCorrectionPatternStore,
                JsonImprovementModelStore,
                JsonFineTuningSessionStore,
                DefaultFineTuningAnalyzer,
            )
            ft_dir = self.data_dir / "fine_tuning"
            ft_dir.mkdir(parents=True, exist_ok=True)

            self._user_correction_store = JsonUserCorrectionStore(
                ft_dir / "corrections.json"
            )
            self._user_feedback_store = JsonUserFeedbackStore(
                ft_dir / "feedbacks.json"
            )
            self._correction_pattern_store = JsonCorrectionPatternStore(
                ft_dir / "patterns.json"
            )
            self._improvement_model_store = JsonImprovementModelStore(
                ft_dir / "models.json"
            )
            self._fine_tuning_session_store = JsonFineTuningSessionStore(
                ft_dir / "sessions.json"
            )
            self._fine_tuning_analyzer = DefaultFineTuningAnalyzer()

    def get_user_correction_store(self) -> UserCorrectionPort:
        """Retourne le store de corrections utilisateur."""
        self._init_fine_tuning_stores()
        return self._user_correction_store

    def get_user_feedback_store(self) -> UserFeedbackPort:
        """Retourne le store de feedbacks utilisateur."""
        self._init_fine_tuning_stores()
        return self._user_feedback_store

    def get_correction_pattern_store(self) -> CorrectionPatternPort:
        """Retourne le store de patterns de correction."""
        self._init_fine_tuning_stores()
        return self._correction_pattern_store

    def get_improvement_model_store(self) -> ImprovementModelPort:
        """Retourne le store de modèles d'amélioration."""
        self._init_fine_tuning_stores()
        return self._improvement_model_store

    def get_fine_tuning_session_store(self) -> FineTuningSessionPort:
        """Retourne le store de sessions fine-tuning."""
        self._init_fine_tuning_stores()
        return self._fine_tuning_session_store

    def get_fine_tuning_analyzer(self) -> FineTuningAnalyzerPort:
        """Retourne l'analyseur de fine-tuning."""
        self._init_fine_tuning_stores()
        return self._fine_tuning_analyzer

    def _init_mobile_stores(self) -> None:
        """Initialise tous les stores mobile companion."""
        if self._mobile_session_store is None:
            from app.infrastructure.mobile_companion_store import (
                JsonFileMobileSessionStore,
                JsonFileMobileSyncStore,
                JsonFileMobileDraftActionStore,
                JsonFileMobileAnalyticsStore,
                JsonFileMobilePreferencesStore,
                JsonFileMobileAppConfigStore,
            )
            mobile_dir = self.data_dir / "mobile"
            mobile_dir.mkdir(parents=True, exist_ok=True)

            self._mobile_session_store = JsonFileMobileSessionStore(
                mobile_dir / "sessions.json"
            )
            self._mobile_sync_store = JsonFileMobileSyncStore(
                mobile_dir / "sync.json"
            )
            self._mobile_draft_action_store = JsonFileMobileDraftActionStore(
                mobile_dir / "actions.json",
                sync_store=self._mobile_sync_store,
            )
            self._mobile_analytics_store = JsonFileMobileAnalyticsStore(
                mobile_dir / "analytics.json"
            )
            self._mobile_preferences_store = JsonFileMobilePreferencesStore(
                mobile_dir / "preferences.json"
            )
            self._mobile_config_store = JsonFileMobileAppConfigStore(
                mobile_dir / "config.json"
            )

    def get_mobile_session_store(self) -> MobileSessionPort:
        """Retourne le store de sessions mobile."""
        self._init_mobile_stores()
        return self._mobile_session_store

    def get_mobile_sync_store(self) -> MobileSyncPort:
        """Retourne le store de synchronisation mobile."""
        self._init_mobile_stores()
        return self._mobile_sync_store

    def get_mobile_draft_action_store(self) -> MobileDraftActionPort:
        """Retourne le store d'actions sur brouillons mobile."""
        self._init_mobile_stores()
        return self._mobile_draft_action_store

    def get_mobile_analytics_store(self) -> MobileAnalyticsPort:
        """Retourne le store d'analytics mobile."""
        self._init_mobile_stores()
        return self._mobile_analytics_store

    def get_mobile_preferences_store(self) -> MobileUserPreferencesPort:
        """Retourne le store de préférences mobile."""
        self._init_mobile_stores()
        return self._mobile_preferences_store

    def get_mobile_config_store(self) -> MobileAppConfigPort:
        """Retourne le store de configuration mobile."""
        self._init_mobile_stores()
        return self._mobile_config_store

    # =========================================================================
    # Classification & Prioritization Adapters
    # =========================================================================

    def get_classifier(self) -> ClassifierPort:
        """Retourne le classifier d'emails (singleton)."""
        if self._classifier is None:
            from app.adapters.classification import LLMClassifierAdapter
            self._classifier = LLMClassifierAdapter(
                llm=self.llm_background,  # Per-email classification → background key
                max_tokens=self.config.max_tokens_classification,
                token_usage=self._token_usage,
            )
        return self._classifier

    def get_prioritizer(self) -> PrioritizationPort:
        """Retourne le prioriseur d'emails (singleton)."""
        if self._prioritizer is None:
            from app.adapters.classification import LLMPrioritizationAdapter
            self._prioritizer = LLMPrioritizationAdapter(
                llm=self.llm_background,  # Per-email prioritization → background key
                max_tokens=self.config.max_tokens_prioritization,
                token_usage=self._token_usage,
            )
        return self._prioritizer

    def get_email_analyzer(self) -> EmailAnalyzerPort:
        """Retourne l'analyseur d'emails complet (singleton).

        Issue #684 : utilise UnifiedEmailAnalyzerAgent (1 appel LLM
        category+priority+intent+tasks) au lieu des 2 appels classifier+
        prioritizer. Gain : -50% appels Haiku sur ce chemin, ~1 RTT
        économisé par email analysé. Les anciens ports restent câblés
        en fallback si ``unified`` rencontre un problème lors de
        l'initialisation.
        """
        if self._email_analyzer is None:
            from app.adapters.classification import LLMEmailAnalyzerAdapter
            from app.agents import UnifiedEmailAnalyzerAgent
            self._email_analyzer = LLMEmailAnalyzerAdapter(
                classifier=self.get_classifier(),
                prioritizer=self.get_prioritizer(),
                unified=UnifiedEmailAnalyzerAgent(),
            )
        return self._email_analyzer

    # =========================================================================
    # Core Email Use Case Factories
    # =========================================================================

    def get_draft_use_case(self) -> DraftEmailUseCase:
        """Crée un use case de génération de brouillon."""
        return DraftEmailUseCase(
            llm=self.llm_drafting,  # User-facing draft → drafting key
            knowledge_base=self.knowledge_base,
            max_tokens=self.config.max_tokens_draft,
            token_usage=self._token_usage
        )

    def get_critique_use_case(self) -> CritiqueEmailUseCase:
        """Crée un use case d'évaluation."""
        return CritiqueEmailUseCase(
            llm=self.llm_drafting,  # Critic in drafting loop → drafting key
            knowledge_base=self.knowledge_base,
            max_tokens=self.config.max_tokens_critique,
            token_usage=self._token_usage
        )

    def get_process_use_case(self) -> ProcessEmailUseCase:
        """Crée un use case de traitement complet."""
        return ProcessEmailUseCase(
            llm=self.llm_drafting,  # End-to-end email draft pipeline → drafting key
            knowledge_base=self.knowledge_base,
            max_tokens_draft=self.config.max_tokens_draft,
            max_tokens_critique=self.config.max_tokens_critique,
            token_usage=self._token_usage
        )

    def get_refine_use_case(self) -> RefineEmailUseCase:
        """Crée un use case de refinement de brouillon."""
        return RefineEmailUseCase(
            llm=self.llm_drafting,  # User-triggered draft refine → drafting key
            knowledge_base=self.knowledge_base,
            max_tokens_draft=self.config.max_tokens_draft,
            max_tokens_critique=self.config.max_tokens_critique,
            token_usage=self._token_usage
        )

    def get_regenerate_use_case(self) -> RegenerateEmailUseCase:
        """Crée un use case de regeneration de brouillon."""
        return RegenerateEmailUseCase(
            llm=self.llm_drafting,  # User-triggered draft regenerate → drafting key
            knowledge_base=self.knowledge_base,
            max_tokens_draft=self.config.max_tokens_draft,
            max_tokens_critique=self.config.max_tokens_critique,
            token_usage=self._token_usage
        )

    def get_classify_email_use_case(self) -> ClassifyEmailUseCase:
        """Crée un use case de classification d'email."""
        return ClassifyEmailUseCase(classifier=self.get_classifier())

    def get_prioritize_email_use_case(self) -> PrioritizeEmailUseCase:
        """Crée un use case de priorisation d'email."""
        return PrioritizeEmailUseCase(prioritizer=self.get_prioritizer())

    def get_analyze_email_use_case(self) -> AnalyzeEmailUseCase:
        """Crée un use case d'analyse complète d'email.

        Issue #684 : passe par EmailAnalyzerPort (unifié, 1 appel)
        plutôt que par classifier+prioritizer séparés (2 appels). Le
        downstream caller (routes_helpers._process_email_with_use_case
        Ollama branch) ne change pas, mais consomme 50% moins d'appels
        Haiku.
        """
        return AnalyzeEmailUseCase(
            analyzer=self.get_email_analyzer(),
        )

    # =========================================================================
    # Health Check Use Case Factory
    # =========================================================================

    def get_health_check_use_case(
        self,
        email_provider_factory: Optional[Callable[[], EmailPort]] = None,
        llm_factory: Optional[Callable[[], LLMPort]] = None,
    ) -> HealthCheckUseCase:
        """
        Crée un use case de health check.

        Args:
            email_provider_factory: Factory pour créer le provider email.
                                   Si None, utilise le factory par défaut.
            llm_factory: Factory pour créer le LLM.
                        Si None, utilise get_llm_adapter.

        Returns:
            Instance configurée de HealthCheckUseCase.
        """
        from app.providers.factory import get_email_provider

        def _account_aware_email_factory() -> EmailPort:
            """Crée un provider email basé sur le compte actif (pas le défaut env var)."""
            try:
                from app.multi_accounts import get_current_account, create_provider_for_account
                account = get_current_account()
                if account:
                    provider = create_provider_for_account(account)
                    if provider:
                        return provider
            except Exception:
                pass
            return get_email_provider()

        return HealthCheckUseCase(
            email_provider_factory=email_provider_factory or _account_aware_email_factory,
            llm_factory=llm_factory or get_llm_adapter,
        )

    # =========================================================================
    # Draft Completion Use Case Factory
    # =========================================================================

    def get_complete_draft_use_case(self) -> CompleteDraftUseCase:
        """Crée un use case de complétion de brouillon."""
        return CompleteDraftUseCase(
            llm=self.llm_drafting,  # Auto-complete while typing → drafting key
            knowledge_base=self.knowledge_base,
        )

    # =========================================================================
    # Wizard Configuration Use Case Factories
    # =========================================================================

    def get_save_wizard_config_use_case(self) -> SaveWizardConfigUseCase:
        """Crée un use case de sauvegarde de configuration wizard."""
        return SaveWizardConfigUseCase(persistence=self.get_wizard_config_store())

    def get_load_wizard_config_use_case(self) -> LoadWizardConfigUseCase:
        """Crée un use case de chargement de configuration wizard."""
        return LoadWizardConfigUseCase(persistence=self.get_wizard_config_store())

    def get_create_wizard_config_use_case(self) -> CreateWizardConfigUseCase:
        """Crée un use case de création de configuration wizard."""
        return CreateWizardConfigUseCase(persistence=self.get_wizard_config_store())

    def get_toggle_agent_use_case(self) -> ToggleAgentUseCase:
        """Crée un use case d'activation/désactivation d'agent."""
        return ToggleAgentUseCase(persistence=self.get_wizard_config_store())

    def get_import_knowledge_base_use_case(self) -> ImportKnowledgeBaseUseCase:
        """Crée un use case d'import de knowledge base."""
        return ImportKnowledgeBaseUseCase(persistence=self.get_wizard_config_store())

    def get_export_config_use_case(self) -> ExportConfigUseCase:
        """Crée un use case d'export de configuration."""
        return ExportConfigUseCase(persistence=self.get_wizard_config_store())

    # =========================================================================
    # Marketplace Use Case Factories
    # =========================================================================

    def get_register_publisher_use_case(self) -> RegisterPublisherUseCase:
        """Crée un use case d'enregistrement d'éditeur."""
        return RegisterPublisherUseCase(publisher_port=self.get_publisher_store())

    def get_publisher_use_case(self) -> GetPublisherUseCase:
        """Crée un use case de récupération d'éditeur."""
        return GetPublisherUseCase(publisher_port=self.get_publisher_store())

    def get_publish_agent_use_case(self) -> PublishAgentUseCase:
        """Crée un use case de publication d'agent."""
        return PublishAgentUseCase(
            agent_port=self.get_marketplace_agent_store(),
            publisher_port=self.get_publisher_store(),
        )

    def get_submit_agent_for_review_use_case(self) -> SubmitAgentForReviewUseCase:
        """Crée un use case de soumission d'agent pour review."""
        return SubmitAgentForReviewUseCase(
            agent_port=self.get_marketplace_agent_store()
        )

    def get_approve_agent_use_case(self) -> ApproveAgentUseCase:
        """Crée un use case d'approbation d'agent."""
        return ApproveAgentUseCase(agent_port=self.get_marketplace_agent_store())

    def get_update_agent_use_case(self) -> UpdateAgentUseCase:
        """Crée un use case de mise à jour d'agent."""
        return UpdateAgentUseCase(agent_port=self.get_marketplace_agent_store())

    def get_search_agents_use_case(self) -> SearchAgentsUseCase:
        """Crée un use case de recherche d'agents."""
        return SearchAgentsUseCase(agent_port=self.get_marketplace_agent_store())

    def get_agent_details_use_case(self) -> GetAgentDetailsUseCase:
        """Crée un use case de détails d'agent."""
        return GetAgentDetailsUseCase(
            agent_port=self.get_marketplace_agent_store(),
            review_port=self.get_agent_review_store(),
            installation_port=self.get_agent_installation_store(),
        )

    def get_list_featured_agents_use_case(self) -> ListFeaturedAgentsUseCase:
        """Crée un use case de liste des agents featured."""
        return ListFeaturedAgentsUseCase(
            agent_port=self.get_marketplace_agent_store()
        )

    def get_list_agents_by_category_use_case(self) -> ListAgentsByCategoryUseCase:
        """Crée un use case de liste des agents par catégorie."""
        return ListAgentsByCategoryUseCase(
            agent_port=self.get_marketplace_agent_store()
        )

    def get_install_agent_use_case(self) -> InstallAgentUseCase:
        """Crée un use case d'installation d'agent."""
        return InstallAgentUseCase(
            agent_port=self.get_marketplace_agent_store(),
            installation_port=self.get_agent_installation_store(),
        )

    def get_uninstall_agent_use_case(self) -> UninstallAgentUseCase:
        """Crée un use case de désinstallation d'agent."""
        return UninstallAgentUseCase(
            agent_port=self.get_marketplace_agent_store(),
            installation_port=self.get_agent_installation_store(),
        )

    def get_list_installed_agents_use_case(self) -> ListInstalledAgentsUseCase:
        """Crée un use case de liste des agents installés."""
        return ListInstalledAgentsUseCase(
            installation_port=self.get_agent_installation_store(),
            agent_port=self.get_marketplace_agent_store(),
        )

    def get_record_agent_usage_use_case(self) -> RecordAgentUsageUseCase:
        """Crée un use case d'enregistrement d'utilisation d'agent."""
        return RecordAgentUsageUseCase(
            installation_port=self.get_agent_installation_store()
        )

    def get_submit_review_use_case(self) -> SubmitReviewUseCase:
        """Crée un use case de soumission d'avis."""
        return SubmitReviewUseCase(
            review_port=self.get_agent_review_store(),
            installation_port=self.get_agent_installation_store(),
            agent_port=self.get_marketplace_agent_store(),
        )

    def get_respond_to_review_use_case(self) -> RespondToReviewUseCase:
        """Crée un use case de réponse à un avis."""
        return RespondToReviewUseCase(
            review_port=self.get_agent_review_store(),
            agent_port=self.get_marketplace_agent_store(),
        )

    def get_list_agent_reviews_use_case(self) -> ListAgentReviewsUseCase:
        """Crée un use case de liste des avis d'un agent."""
        return ListAgentReviewsUseCase(review_port=self.get_agent_review_store())

    def get_create_agent_pack_use_case(self) -> CreateAgentPackUseCase:
        """Crée un use case de création de pack d'agents."""
        return CreateAgentPackUseCase(
            pack_port=self.get_agent_pack_store(),
            agent_port=self.get_marketplace_agent_store(),
            publisher_port=self.get_publisher_store(),
        )

    def get_install_pack_use_case(self) -> InstallPackUseCase:
        """Crée un use case d'installation de pack."""
        return InstallPackUseCase(
            pack_port=self.get_agent_pack_store(),
            install_agent_use_case=self.get_install_agent_use_case(),
        )

    # =========================================================================
    # Fine-tuning Use Case Factories
    # =========================================================================

    def get_record_correction_use_case(self) -> RecordCorrectionUseCase:
        """Crée un use case d'enregistrement de correction."""
        return RecordCorrectionUseCase(
            correction_store=self.get_user_correction_store(),
            pattern_store=self.get_correction_pattern_store(),
            analyzer=self.get_fine_tuning_analyzer(),
        )

    def get_record_feedback_use_case(self) -> RecordFeedbackUseCase:
        """Crée un use case d'enregistrement de feedback."""
        return RecordFeedbackUseCase(
            feedback_store=self.get_user_feedback_store()
        )

    def get_extract_patterns_use_case(self) -> ExtractPatternsUseCase:
        """Crée un use case d'extraction de patterns."""
        return ExtractPatternsUseCase(
            correction_store=self.get_user_correction_store(),
            pattern_store=self.get_correction_pattern_store(),
            analyzer=self.get_fine_tuning_analyzer(),
        )

    def get_create_improvement_model_use_case(self) -> CreateImprovementModelUseCase:
        """Crée un use case de création de modèle d'amélioration."""
        return CreateImprovementModelUseCase(
            model_store=self.get_improvement_model_store(),
            pattern_store=self.get_correction_pattern_store(),
            analyzer=self.get_fine_tuning_analyzer(),
        )

    def get_activate_model_use_case(self) -> ActivateModelUseCase:
        """Crée un use case d'activation de modèle."""
        return ActivateModelUseCase(
            model_store=self.get_improvement_model_store()
        )

    def get_disable_model_use_case(self) -> DisableModelUseCase:
        """Crée un use case de désactivation de modèle."""
        return DisableModelUseCase(
            model_store=self.get_improvement_model_store()
        )

    def get_apply_improvements_use_case(self) -> ApplyImprovementsUseCase:
        """Crée un use case d'application d'améliorations."""
        return ApplyImprovementsUseCase(
            model_store=self.get_improvement_model_store(),
            pattern_store=self.get_correction_pattern_store(),
            analyzer=self.get_fine_tuning_analyzer(),
        )

    def get_prompt_enhancements_use_case(self) -> GetPromptEnhancementsUseCase:
        """Crée un use case de récupération des améliorations de prompt."""
        return GetPromptEnhancementsUseCase(
            model_store=self.get_improvement_model_store(),
            pattern_store=self.get_correction_pattern_store(),
        )

    def get_run_fine_tuning_session_use_case(self) -> RunFineTuningSessionUseCase:
        """Crée un use case de session de fine-tuning."""
        return RunFineTuningSessionUseCase(
            session_store=self.get_fine_tuning_session_store(),
            correction_store=self.get_user_correction_store(),
            feedback_store=self.get_user_feedback_store(),
            pattern_store=self.get_correction_pattern_store(),
            model_store=self.get_improvement_model_store(),
            analyzer=self.get_fine_tuning_analyzer(),
        )

    def get_fine_tuning_stats_use_case(self) -> GetFineTuningStatsUseCase:
        """Crée un use case de statistiques de fine-tuning."""
        return GetFineTuningStatsUseCase(
            correction_store=self.get_user_correction_store(),
            feedback_store=self.get_user_feedback_store(),
            pattern_store=self.get_correction_pattern_store(),
            model_store=self.get_improvement_model_store(),
        )

    def get_list_patterns_use_case(self) -> ListPatternsUseCase:
        """Crée un use case de liste des patterns."""
        return ListPatternsUseCase(
            pattern_store=self.get_correction_pattern_store()
        )

    def get_list_models_use_case(self) -> ListModelsUseCase:
        """Crée un use case de liste des modèles."""
        return ListModelsUseCase(
            model_store=self.get_improvement_model_store()
        )

    # =========================================================================
    # Mobile Companion Use Case Factories
    # =========================================================================

    def get_start_mobile_session_use_case(self) -> StartMobileSessionUseCase:
        """Crée un use case de démarrage de session mobile."""
        return StartMobileSessionUseCase(
            session_port=self.get_mobile_session_store(),
            config_port=self.get_mobile_config_store(),
            preferences_port=self.get_mobile_preferences_store(),
        )

    def get_end_mobile_session_use_case(self) -> EndMobileSessionUseCase:
        """Crée un use case de fin de session mobile."""
        return EndMobileSessionUseCase(
            session_port=self.get_mobile_session_store(),
            analytics_port=self.get_mobile_analytics_store(),
        )

    def get_touch_session_use_case(self) -> TouchSessionUseCase:
        """Crée un use case de heartbeat de session mobile."""
        return TouchSessionUseCase(
            session_port=self.get_mobile_session_store()
        )

    def get_sync_mobile_data_use_case(self) -> SyncMobileDataUseCase:
        """Crée un use case de synchronisation mobile."""
        return SyncMobileDataUseCase(
            sync_port=self.get_mobile_sync_store(),
            analytics_port=self.get_mobile_analytics_store(),
        )

    def get_draft_details_use_case(self) -> GetDraftDetailsUseCase:
        """Crée un use case de détails de brouillon mobile."""
        return GetDraftDetailsUseCase(
            sync_port=self.get_mobile_sync_store(),
            analytics_port=self.get_mobile_analytics_store(),
        )

    def get_pending_drafts_use_case(self) -> GetPendingDraftsUseCase:
        """Crée un use case de brouillons en attente mobile."""
        return GetPendingDraftsUseCase(
            sync_port=self.get_mobile_sync_store()
        )

    def get_apply_draft_action_use_case(self) -> ApplyDraftActionUseCase:
        """Crée un use case d'action sur brouillon mobile."""
        return ApplyDraftActionUseCase(
            action_port=self.get_mobile_draft_action_store(),
            sync_port=self.get_mobile_sync_store(),
            analytics_port=self.get_mobile_analytics_store(),
        )

    def get_apply_batch_actions_use_case(self) -> ApplyBatchActionsUseCase:
        """Crée un use case d'actions batch sur brouillons mobiles."""
        return ApplyBatchActionsUseCase(
            action_port=self.get_mobile_draft_action_store(),
            analytics_port=self.get_mobile_analytics_store(),
        )

    def get_mark_draft_read_use_case(self) -> MarkDraftReadUseCase:
        """Crée un use case de marquage lu de brouillon mobile."""
        return MarkDraftReadUseCase(
            action_port=self.get_mobile_draft_action_store()
        )

    def get_track_mobile_event_use_case(self) -> TrackMobileEventUseCase:
        """Crée un use case de tracking d'événement mobile."""
        return TrackMobileEventUseCase(
            analytics_port=self.get_mobile_analytics_store()
        )

    def get_mobile_stats_use_case(self) -> GetMobileStatsUseCase:
        """Crée un use case de statistiques mobile."""
        return GetMobileStatsUseCase(
            analytics_port=self.get_mobile_analytics_store()
        )

    def get_preferences_use_case(self) -> GetPreferencesUseCase:
        """Crée un use case de récupération de préférences mobile."""
        return GetPreferencesUseCase(
            preferences_port=self.get_mobile_preferences_store()
        )

    def get_update_preferences_use_case(self) -> UpdatePreferencesUseCase:
        """Crée un use case de mise à jour de préférences mobile."""
        return UpdatePreferencesUseCase(
            preferences_port=self.get_mobile_preferences_store(),
            analytics_port=self.get_mobile_analytics_store(),
        )

    def get_app_config_use_case(self) -> GetAppConfigUseCase:
        """Crée un use case de récupération de configuration mobile."""
        return GetAppConfigUseCase(
            config_port=self.get_mobile_config_store()
        )

    def get_update_app_config_use_case(self) -> UpdateAppConfigUseCase:
        """Crée un use case de mise à jour de configuration mobile."""
        return UpdateAppConfigUseCase(
            config_port=self.get_mobile_config_store()
        )

    def get_mobile_companion_service(self) -> MobileCompanionService:
        """Crée le service complet Mobile Companion."""
        return MobileCompanionService(
            session_port=self.get_mobile_session_store(),
            sync_port=self.get_mobile_sync_store(),
            action_port=self.get_mobile_draft_action_store(),
            analytics_port=self.get_mobile_analytics_store(),
            preferences_port=self.get_mobile_preferences_store(),
            config_port=self.get_mobile_config_store(),
        )

    # =========================================================================
    # Push Notification Use Case Factory
    # =========================================================================

    def get_push_notification_service(self) -> PushNotificationService:
        """Crée le service de notifications push."""
        from app.infrastructure.push_adapter_factory import get_push_adapter
        return PushNotificationService(
            device_store=self.get_device_store(),
            notification_adapter=get_push_adapter(),
        )

    # =========================================================================
    # Learning Stores
    # =========================================================================

    def get_learning_pattern_store(self) -> LearningPatternStorePort:
        """Retourne le store de patterns appris (singleton, SQLite)."""
        if self._learning_pattern_store is None:
            from app.infrastructure.adapters.sqlite_learning_store import SqliteLearningPatternStore
            from app.infrastructure.database import db
            self._learning_pattern_store = SqliteLearningPatternStore(db)
        return self._learning_pattern_store

    def get_adjustment_store(self) -> AdjustmentStorePort:
        """Retourne le store d'ajustements de prompt (singleton, SQLite)."""
        if self._adjustment_store is None:
            from app.infrastructure.adapters.sqlite_learning_store import SqliteAdjustmentStore
            from app.infrastructure.database import db
            self._adjustment_store = SqliteAdjustmentStore(db)
        return self._adjustment_store

    def get_learning_feedback_provider(self) -> LearningFeedbackProviderPort:
        """Retourne le provider de feedbacks pour le learning (singleton)."""
        if self._learning_feedback_provider is None:
            from app.infrastructure.learning_store import HistoryFeedbackAdapter
            self._learning_feedback_provider = HistoryFeedbackAdapter()
        return self._learning_feedback_provider

    # =========================================================================
    # Learning Use Case Factories
    # =========================================================================

    def get_analyze_feedback_use_case(self) -> AnalyzeFeedbackUseCase:
        """Crée un use case d'analyse des feedbacks."""
        return AnalyzeFeedbackUseCase(
            feedback_store=self.get_learning_feedback_provider()
        )

    def get_learning_extract_patterns_use_case(self) -> LearningExtractPatternsUseCase:
        """Crée un use case d'extraction de patterns pour le learning."""
        return LearningExtractPatternsUseCase(
            feedback_store=self.get_learning_feedback_provider(),
            pattern_store=self.get_learning_pattern_store(),
            llm=self.llm_onboarding_label,  # Pattern learning from user feedback → onboarding key
        )

    def get_should_require_review_use_case(self) -> ShouldRequireReviewUseCase:
        """Crée un use case de détermination de review."""
        return ShouldRequireReviewUseCase(
            insights_provider=self.get_learning_feedback_provider(),
        )

    def get_generate_adjustment_use_case(self) -> GenerateAdjustmentUseCase:
        """Crée un use case de génération d'ajustement."""
        return GenerateAdjustmentUseCase(
            pattern_store=self.get_learning_pattern_store(),
            adjustment_store=self.get_adjustment_store(),
        )

    def get_learning_stats_use_case(self) -> GetLearningStatsUseCase:
        """Crée un use case de statistiques d'apprentissage."""
        return GetLearningStatsUseCase(
            pattern_store=self.get_learning_pattern_store(),
            adjustment_store=self.get_adjustment_store(),
            feedback_store=self.get_learning_feedback_provider(),
        )

    def get_enhance_prompt_use_case(self) -> EnhancePromptUseCase:
        """Crée un use case d'amélioration de prompt."""
        return EnhancePromptUseCase(
            adjustment_store=self.get_adjustment_store()
        )

    def get_active_adjustments_use_case(self) -> GetActiveAdjustmentsUseCase:
        """Crée un use case pour récupérer les ajustements actifs."""
        return GetActiveAdjustmentsUseCase(
            adjustment_store=self.get_adjustment_store()
        )

    def get_learning_service(self) -> LearningService:
        """Crée le service complet d'apprentissage."""
        return LearningService(
            analyze_use_case=self.get_analyze_feedback_use_case(),
            extract_use_case=self.get_learning_extract_patterns_use_case(),
            should_review_use_case=self.get_should_require_review_use_case(),
            generate_adjustment_use_case=self.get_generate_adjustment_use_case(),
            stats_use_case=self.get_learning_stats_use_case(),
            enhance_prompt_use_case=self.get_enhance_prompt_use_case(),
            get_active_adjustments_use_case=self.get_active_adjustments_use_case(),
        )

    # =========================================================================
    # Real-time Edit Store & Use Cases
    # =========================================================================

    def get_realtime_edit_store(self) -> EditSessionStorePort:
        """Retourne le store de sessions d'édition temps réel (singleton)."""
        if self._realtime_edit_store is None:
            from app.infrastructure.realtime_edit_store import JsonEditSessionStore
            filepath = self.data_dir / "realtime_edit" / "sessions.json"
            self._realtime_edit_store = JsonEditSessionStore(filepath)
        return self._realtime_edit_store

    def get_start_edit_session_use_case(self) -> "StartEditSessionUseCase":
        """Crée un use case de démarrage de session d'édition."""
        from app.application.realtime_edit import StartEditSessionUseCase
        return StartEditSessionUseCase(
            session_store=self.get_realtime_edit_store()
        )

    def get_process_text_change_use_case(self) -> "ProcessTextChangeUseCase":
        """Crée un use case de traitement de changement de texte."""
        from app.application.realtime_edit import ProcessTextChangeUseCase
        return ProcessTextChangeUseCase(
            session_store=self.get_realtime_edit_store()
        )

    def get_suggestion_use_case(self) -> "GetSuggestionUseCase":
        """Crée un use case de génération de suggestion."""
        from app.application.realtime_edit import GetSuggestionUseCase
        return GetSuggestionUseCase(
            session_store=self.get_realtime_edit_store(),
            llm=self.llm_drafting,  # Realtime typing suggestion → drafting key
        )

    def get_apply_suggestion_use_case(self) -> "ApplySuggestionUseCase":
        """Crée un use case d'application de suggestion."""
        from app.application.realtime_edit import ApplySuggestionUseCase
        return ApplySuggestionUseCase(
            session_store=self.get_realtime_edit_store()
        )

    def get_close_edit_session_use_case(self) -> "CloseEditSessionUseCase":
        """Crée un use case de fermeture de session d'édition."""
        from app.application.realtime_edit import CloseEditSessionUseCase
        return CloseEditSessionUseCase(
            session_store=self.get_realtime_edit_store()
        )

    def get_edit_session_use_case(self) -> "GetEditSessionUseCase":
        """Crée un use case de récupération de session d'édition."""
        from app.application.realtime_edit import GetEditSessionUseCase
        return GetEditSessionUseCase(
            session_store=self.get_realtime_edit_store()
        )

    # =========================================================================
    # Legacy Migration Adapters
    # =========================================================================

    def get_draft_history(self) -> DraftHistoryPort:
        """
        Retourne l'adapter d'historique des brouillons (singleton, SQLite).

        Returns:
            DraftHistoryPort: Adapter pour la persistance des brouillons.
        """
        if self._draft_history is None:
            from app.infrastructure.adapters.sqlite_learning_store import SqliteDraftHistoryAdapter
            from app.infrastructure.database import db
            self._draft_history = SqliteDraftHistoryAdapter(db)
        return self._draft_history

    def get_analytics(self) -> AnalyticsPort:
        """
        Retourne l'adapter d'analytics (singleton).

        Returns:
            AnalyticsPort: Adapter pour les metriques de qualite.
        """
        if self._analytics is None:
            from app.infrastructure.adapters.analytics_adapter import LegacyAnalyticsAdapter
            self._analytics = LegacyAnalyticsAdapter()
        return self._analytics

    def get_token_counter(self) -> TokenCounterPort:
        """
        Retourne l'adapter de comptage de tokens (singleton).

        Utilise l'instance TokenUsage partagee du container.

        Returns:
            TokenCounterPort: Adapter pour le comptage des tokens.
        """
        if self._token_counter is None:
            from app.infrastructure.adapters.token_counter_adapter import LegacyTokenCounterAdapter
            self._token_counter = LegacyTokenCounterAdapter(token_usage=self._token_usage)
        return self._token_counter

    def get_processed_emails_tracker(self) -> ProcessedEmailsTrackerPort:
        """
        Retourne le tracker d'emails traités (singleton, SQLite).

        Returns:
            ProcessedEmailsTrackerPort: Adapter pour le suivi des emails traités.
        """
        if self._processed_emails_tracker is None:
            from app.infrastructure.adapters.sqlite_learning_store import SqliteProcessedEmailsTracker
            from app.infrastructure.database import db
            self._processed_emails_tracker = SqliteProcessedEmailsTracker(db)
        return self._processed_emails_tracker

    def get_processed_drafts_tracker(self) -> ProcessedDraftsTrackerPort:
        """
        Retourne le tracker de brouillons traites (singleton).

        Returns:
            ProcessedDraftsTrackerPort: Adapter pour le suivi des brouillons completes.
        """
        if self._processed_drafts_tracker is None:
            from app.infrastructure.adapters.processed_drafts_adapter import JsonProcessedDraftsTracker
            filepath = self.data_dir / "processed_drafts.json"
            self._processed_drafts_tracker = JsonProcessedDraftsTracker(filepath)
        return self._processed_drafts_tracker

    def get_task_repository(self) -> TaskPort:
        if self._task_repository is None:
            from app.infrastructure.database import TaskRepository
            self._task_repository = TaskRepository()
        return self._task_repository

    def get_pending_draft_store(self) -> PendingDraftStorePort:
        """
        Retourne le store des pending drafts (singleton).

        Returns:
            PendingDraftStorePort: Store pour les brouillons en attente.
        """
        if self._pending_draft_store is None:
            from app.infrastructure.pending_draft_store import InMemoryPendingDraftStore
            self._pending_draft_store = InMemoryPendingDraftStore()
        return self._pending_draft_store

    def get_commitment_tracker(self) -> "CommitmentTrackerPort":
        """
        Retourne le tracker d'engagements (singleton).

        Returns:
            CommitmentTrackerPort: Adapter SQLite pour le suivi des engagements.
        """
        if self._commitment_tracker is None:
            from app.infrastructure.adapters.commitment_adapter import CommitmentAdapter
            # Migration 045 : table `commitments` de la DB principale
            # (l'adapter importe une fois le legacy data/commitments.db).
            self._commitment_tracker = CommitmentAdapter(use_main_db=True)
        return self._commitment_tracker

    # =========================================================================
    # Email Templates Store & Use Cases
    # =========================================================================

    def get_email_template_store(self) -> "EmailTemplateStorePort":
        """Retourne le store de templates email (singleton)."""
        from app.infrastructure.email_template_store import JsonEmailTemplateStore
        filepath = self.data_dir / "email_templates.json"
        return JsonEmailTemplateStore(filepath)

    def get_create_template_use_case(self) -> "CreateTemplateUseCase":
        """Crée un use case de création de template."""
        from app.application.email_template import CreateTemplateUseCase
        return CreateTemplateUseCase(store=self.get_email_template_store())

    def get_get_template_use_case(self) -> "GetTemplateUseCase":
        """Crée un use case de récupération de template."""
        from app.application.email_template import GetTemplateUseCase
        return GetTemplateUseCase(store=self.get_email_template_store())

    def get_list_templates_use_case(self) -> "ListTemplatesUseCase":
        """Crée un use case de liste des templates."""
        from app.application.email_template import ListTemplatesUseCase
        return ListTemplatesUseCase(store=self.get_email_template_store())

    def get_update_template_use_case(self) -> "UpdateTemplateUseCase":
        """Crée un use case de mise à jour de template."""
        from app.application.email_template import UpdateTemplateUseCase
        return UpdateTemplateUseCase(store=self.get_email_template_store())

    def get_delete_template_use_case(self) -> "DeleteTemplateUseCase":
        """Crée un use case de suppression de template."""
        from app.application.email_template import DeleteTemplateUseCase
        return DeleteTemplateUseCase(store=self.get_email_template_store())

    def get_match_template_use_case(self) -> "MatchTemplateUseCase":
        """Crée un use case de matching de template."""
        from app.application.email_template import MatchTemplateUseCase
        return MatchTemplateUseCase(store=self.get_email_template_store())

    def get_render_template_use_case(self) -> "RenderTemplateUseCase":
        """Crée un use case de rendu de template."""
        from app.application.email_template import RenderTemplateUseCase
        return RenderTemplateUseCase(store=self.get_email_template_store())

    def get_email_template_stats_use_case(self) -> "GetTemplateStatsUseCase":
        """Crée un use case de statistiques de templates."""
        from app.application.email_template import GetTemplateStatsUseCase
        return GetTemplateStatsUseCase(store=self.get_email_template_store())

    # =========================================================================
    # Email Labels Store & Use Cases
    # =========================================================================

    def get_label_store(self, account_id: Optional[int] = None) -> "LabelStore":
        """Retourne le store de labels email.

        ISO-02 fix (2026-04-24): when called with an `account_id`, returns
        a per-account store backed by `data/labels/<account_id>/`. Without
        an account_id (Tauri desktop legacy path), returns the global
        singleton at `data/labels/` so existing JSON files remain readable.

        The deeper schema fix (adding `account_id` to `email_labels` SQL +
        scoping every read/write) requires a data migration that is too
        risky for this audit pass. The architectural seam is now in
        place — call sites can opt into isolation by passing account_id.
        """
        from app.infrastructure.adapters.label_store import LabelStore

        if account_id is None:
            if self._label_store is None:
                labels_dir = str(self.data_dir / "labels")
                self._label_store = LabelStore(storage_dir=labels_dir)
            return self._label_store

        # Per-account store. Cached in a dict so repeated calls return the
        # same instance and don't replay __post_init__ each time.
        if not hasattr(self, "_label_stores_by_account"):
            self._label_stores_by_account = {}
        if account_id not in self._label_stores_by_account:
            labels_dir = str(self.data_dir / "labels" / str(int(account_id)))
            self._label_stores_by_account[account_id] = LabelStore(storage_dir=labels_dir)
        return self._label_stores_by_account[account_id]

    def get_template_label_cache(self):
        """Singleton TemplateLabelCache — shared across all label use cases."""
        if getattr(self, "_template_label_cache", None) is None:
            from app.infrastructure.adapters.template_label_cache import TemplateLabelCache
            labels_dir = str(self.data_dir / "labels")
            self._template_label_cache = TemplateLabelCache(storage_dir=labels_dir)
        return self._template_label_cache

    def get_label_email_use_case(
        self,
        user_email: str = "",
        account_id: Optional[int] = None,
    ) -> LabelEmailUseCase:
        """
        Crée un use case de labellisation d'email.

        Args:
            user_email: Email de l'utilisateur pour détecter CC.
            account_id: Account DB id. When provided, the use case reads
                rules and labels from the per-account store at
                ``data/labels/<account_id>/`` instead of the global one.
                The UI's LabelEditor writes to the per-account store, so
                without this the labelling pipeline would always read a
                stale global ruleset and user-defined custom-label rules
                (VIP, etc.) would never fire.

        Returns:
            Instance configurée de LabelEmailUseCase.
        """
        store = self.get_label_store(account_id=account_id)
        # llm_window_days defaults to 0 → LabelEmailUseCase resolves to the
        # module-level constant, which itself reads AGENTYS_LLM_LABEL_WINDOW_DAYS
        # from the env. No extra plumbing needed here.
        return LabelEmailUseCase(
            llm=self.llm_background,  # Per-email auto-labeling → background key (Haiku)
            llm_premium=self.llm_background_smart,  # Sonnet escalation for low-conf cases
            labels=store.get_labels(),
            rules=store.get_rules(),
            max_tokens=512,
            token_usage=self._token_usage,
            user_email=user_email,
            template_cache=self.get_template_label_cache(),
        )

    def get_learn_labeling_rule_use_case(self) -> LearnLabelingRuleUseCase:
        """Crée un use case d'apprentissage de règles de labellisation."""
        return LearnLabelingRuleUseCase(
            llm=self.llm_background,  # Label learning from user feedback → background key
            max_tokens=256,
            token_usage=self._token_usage,
        )

    # =========================================================================
    # Writing Style Analysis Stores & Service
    # =========================================================================

    def get_writing_style_profile(self, account_id: int = None):
        """Get writing style profile for template variable filling.

        Returns ``WritingStyleProfile`` from disk (or ``None`` if none saved).
        NOTE: the store port only defines ``load()`` — calling ``get_profile()``
        here throws AttributeError and, because every caller wraps this in a
        broad try/except, the error was silently disabling per-contact style
        adaptation (nickname, greeting, closing, tier) across the entire draft
        and compose pipeline. Do not revert to ``store.get_profile``.
        """
        store = self.get_writing_style_store()
        return store.load(account_id) if account_id else None

    def get_writing_style_store(self):
        """
        Retourne le store de profils de style d'écriture (singleton).

        Returns:
            WritingStyleStorePort: Store local pour les profils de style.
        """
        from app.infrastructure.writing_style_store import FileWritingStyleStore

        if not hasattr(self, "_writing_style_store") or self._writing_style_store is None:
            learning_dir = self.data_dir / "learning"
            self._writing_style_store = FileWritingStyleStore(data_dir=learning_dir)
        return self._writing_style_store

    def get_contact_style_store(self):
        """Retourne le store SQLite des profils de style per-contact (singleton).

        Source de vérité pour les ``ContactStyleProfile`` (PR6 follow-up). Remplace
        l'ancienne ``Dict[str, Any]`` field sur ``WritingStyleProfile`` qui
        forçait :
            (1) un global ``_FILE_LOCK`` pour éviter la corruption JSON sous
                écritures concurrentes (4 onboarding agents en parallèle),
            (2) un re-load complet du profil JSON pour chaque lookup contact
                (~200 contacts par account = O(N) disk read par draft).

        Le SQLite-backed adapter résout les deux : primary key
        ``(account_id, email_lower)`` → row-level locking + lookup O(1) par
        contact. Schema auto-bootstrappé sur première instanciation.

        Returns:
            ContactStyleStorePort: Store SQLite per-contact (singleton).
        """
        from app.infrastructure.contact_style_store_sqlite import (
            SqliteContactStyleStore,
        )

        if (
            not hasattr(self, "_contact_style_store")
            or self._contact_style_store is None
        ):
            self._contact_style_store = SqliteContactStyleStore()
        return self._contact_style_store

    def get_writing_style_analyzer(self):
        """
        Retourne l'analyseur de style d'écriture (singleton).

        Returns:
            WritingStyleAnalyzerPort: Adapter LLM pour l'analyse de style.
        """
        from app.adapters.style import WritingStyleAnalyzerAdapter

        if not hasattr(self, "_writing_style_analyzer") or self._writing_style_analyzer is None:
            # Writing style analysis from stored emails → background key
            self._writing_style_analyzer = WritingStyleAnalyzerAdapter(llm=self.llm_background)
        return self._writing_style_analyzer

    def get_writing_style_service(self):
        """
        Crée le service de gestion du style d'écriture.

        Combine l'analyse LLM et le stockage local.

        Returns:
            WritingStyleService: Service façade pour le style d'écriture.
        """
        from app.domain.services.writing_style_service import WritingStyleService

        return WritingStyleService(
            analyzer=self.get_writing_style_analyzer(),
            store=self.get_writing_style_store(),
        )

    # =========================================================================
    # Style Adaptation Service (Story 4-4)
    # =========================================================================

    def get_style_similarity_analyzer(self):
        """
        Retourne l'analyseur de similarité de style (singleton).

        Returns:
            StyleSimilarityAnalyzer: Analyseur pour comparer brouillons et profils.
        """
        from app.adapters.style import StyleSimilarityAnalyzer

        if not hasattr(self, "_style_similarity_analyzer") or self._style_similarity_analyzer is None:
            self._style_similarity_analyzer = StyleSimilarityAnalyzer()
        return self._style_similarity_analyzer

    def get_style_adaptation_service(self):
        """
        Crée le service d'adaptation de style d'écriture (Story 4-4).

        Orchestre l'adaptation de style dans la génération de brouillons.

        Returns:
            StyleAdaptationService: Service façade pour l'adaptation de style.
        """
        from app.domain.services.style_adaptation_service import StyleAdaptationService
        from app.agents import DrafterAgent

        return StyleAdaptationService(
            writing_style_service=self.get_writing_style_service(),
            similarity_analyzer=self.get_style_similarity_analyzer(),
            drafter_agent=DrafterAgent(),
        )

    # =========================================================================
    # Contact Analysis Use Case Factory
    # =========================================================================

    def get_contact_analyzer(self) -> ContactAnalyzerPort:
        """
        Crée un adapter d'analyse de contact.

        Returns:
            Instance de ContactHistoryAdapter utilisant Claude.
        """
        from app.adapters.analysis import ContactHistoryAdapter

        # Contact history analysis → background key
        return ContactHistoryAdapter(llm=self.llm_background)

    def get_analyze_contact_history_use_case(
        self, email_repository: "EmailRepository"
    ) -> AnalyzeContactHistoryUseCase:
        """
        Crée un use case d'analyse de l'historique des contacts.

        Args:
            email_repository: Repository email (doit être fourni avec une session active).

        Returns:
            Instance configurée de AnalyzeContactHistoryUseCase.
        """
        return AnalyzeContactHistoryUseCase(
            email_repository=email_repository,
            contact_analyzer=self.get_contact_analyzer(),
        )


# Instance globale (singleton)
_container: Optional[Container] = None


def get_container() -> Container:
    """Retourne l'instance globale du container."""
    global _container
    if _container is None:
        _container = Container()
    return _container


def reset_container() -> None:
    """Réinitialise le container (utile pour les tests)."""
    global _container
    _container = None
