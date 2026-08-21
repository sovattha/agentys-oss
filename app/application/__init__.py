# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Application Layer - Use Cases.

Cette couche contient la logique métier sous forme de use cases.
Chaque use case orchestre les entités du domaine et utilise les ports.

Règle : Cette couche dépend uniquement du domaine (entities + ports).
"""

from .draft_email import DraftEmailUseCase
from .critique_email import CritiqueEmailUseCase
from .process_email import ProcessEmailUseCase
from .refine_email import RefineEmailUseCase as RefineEmailUseCase, RefineResult as RefineResult
from .regenerate_email import RegenerateEmailUseCase, RegenerateResult
from .analyze_email import ClassifyEmailUseCase, PrioritizeEmailUseCase, AnalyzeEmailUseCase
from .health_check import HealthCheckUseCase, HealthStatus, SystemHealthStatus
from .send_push_notification import SendPushNotificationUseCase
from .push_notification_service import PushNotificationService
from .complete_draft import CompleteDraftUseCase
from .wizard_config import (
    SaveWizardConfigUseCase,
    LoadWizardConfigUseCase,
    CreateWizardConfigUseCase,
    ToggleAgentUseCase,
    ImportKnowledgeBaseUseCase,
    ExportConfigUseCase,
    get_available_packs,
    get_available_agents,
    PACK_CONFIGURATIONS,
)
from .marketplace import (
    # Publisher
    RegisterPublisherUseCase,
    GetPublisherUseCase,
    # Agent Publication
    PublishAgentUseCase,
    SubmitAgentForReviewUseCase,
    ApproveAgentUseCase,
    UpdateAgentUseCase,
    # Search
    SearchAgentsUseCase,
    GetAgentDetailsUseCase,
    ListFeaturedAgentsUseCase,
    ListAgentsByCategoryUseCase,
    # Installation
    InstallAgentUseCase,
    UninstallAgentUseCase,
    ListInstalledAgentsUseCase,
    RecordAgentUsageUseCase,
    # Reviews
    SubmitReviewUseCase,
    RespondToReviewUseCase,
    ListAgentReviewsUseCase,
    # Packs
    CreateAgentPackUseCase,
    InstallPackUseCase,
)
from .fine_tuning import (
    RecordCorrectionUseCase,
    RecordCorrectionResult,
    RecordFeedbackUseCase,
    RecordFeedbackResult,
    ExtractPatternsUseCase,
    ExtractPatternsResult,
    CreateImprovementModelUseCase,
    CreateModelResult,
    ActivateModelUseCase,
    DisableModelUseCase,
    ApplyImprovementsUseCase,
    ApplyImprovementsResult,
    GetPromptEnhancementsUseCase,
    RunFineTuningSessionUseCase,
    FineTuningSessionResult,
    GetFineTuningStatsUseCase,
    ListPatternsUseCase,
    ListModelsUseCase,
)
from .mobile_companion import (
    # Session
    StartSessionResult,
    StartMobileSessionUseCase,
    EndMobileSessionUseCase,
    TouchSessionUseCase,
    # Sync
    SyncMobileDataUseCase,
    GetDraftDetailsUseCase,
    GetPendingDraftsUseCase,
    # Actions
    DraftActionResult,
    ApplyDraftActionUseCase,
    BatchActionsResult,
    ApplyBatchActionsUseCase,
    MarkDraftReadUseCase,
    # Analytics
    TrackMobileEventUseCase,
    GetMobileStatsUseCase,
    # Preferences
    GetPreferencesUseCase,
    UpdatePreferencesUseCase,
    # Config
    GetAppConfigUseCase,
    UpdateAppConfigUseCase,
    # Service
    MobileCompanionService,
)
from .realtime_edit import (
    StartEditSessionUseCase,
    ProcessTextChangeUseCase,
    GetSuggestionUseCase,
    ApplySuggestionUseCase,
    CloseEditSessionUseCase,
    GetEditSessionUseCase,
    CleanupExpiredSessionsUseCase,
)
from .detect_phishing import DetectPhishingUseCase
from .commitment_tracking import CommitmentTrackingUseCase
from .label_email import LabelEmailUseCase, LearnLabelingRuleUseCase
from .analyze_contact_history import AnalyzeContactHistoryUseCase

__all__ = [
    "DraftEmailUseCase",
    "CritiqueEmailUseCase",
    "ProcessEmailUseCase",
    "ClassifyEmailUseCase",
    "PrioritizeEmailUseCase",
    "AnalyzeEmailUseCase",
    "HealthCheckUseCase",
    "HealthStatus",
    "SystemHealthStatus",
    "SendPushNotificationUseCase",
    "PushNotificationService",
    "CompleteDraftUseCase",
    "SaveWizardConfigUseCase",
    "LoadWizardConfigUseCase",
    "CreateWizardConfigUseCase",
    "ToggleAgentUseCase",
    "ImportKnowledgeBaseUseCase",
    "ExportConfigUseCase",
    "get_available_packs",
    "get_available_agents",
    "PACK_CONFIGURATIONS",
    # Marketplace
    "RegisterPublisherUseCase",
    "GetPublisherUseCase",
    "PublishAgentUseCase",
    "SubmitAgentForReviewUseCase",
    "ApproveAgentUseCase",
    "UpdateAgentUseCase",
    "SearchAgentsUseCase",
    "GetAgentDetailsUseCase",
    "ListFeaturedAgentsUseCase",
    "ListAgentsByCategoryUseCase",
    "InstallAgentUseCase",
    "UninstallAgentUseCase",
    "ListInstalledAgentsUseCase",
    "RecordAgentUsageUseCase",
    "SubmitReviewUseCase",
    "RespondToReviewUseCase",
    "ListAgentReviewsUseCase",
    "CreateAgentPackUseCase",
    "InstallPackUseCase",
    # Fine-tuning
    "RecordCorrectionUseCase",
    "RecordCorrectionResult",
    "RecordFeedbackUseCase",
    "RecordFeedbackResult",
    "ExtractPatternsUseCase",
    "ExtractPatternsResult",
    "CreateImprovementModelUseCase",
    "CreateModelResult",
    "ActivateModelUseCase",
    "DisableModelUseCase",
    "ApplyImprovementsUseCase",
    "ApplyImprovementsResult",
    "GetPromptEnhancementsUseCase",
    "RunFineTuningSessionUseCase",
    "FineTuningSessionResult",
    "GetFineTuningStatsUseCase",
    "ListPatternsUseCase",
    "ListModelsUseCase",
    # Mobile companion
    "StartSessionResult",
    "StartMobileSessionUseCase",
    "EndMobileSessionUseCase",
    "TouchSessionUseCase",
    "SyncMobileDataUseCase",
    "GetDraftDetailsUseCase",
    "GetPendingDraftsUseCase",
    "DraftActionResult",
    "ApplyDraftActionUseCase",
    "BatchActionsResult",
    "ApplyBatchActionsUseCase",
    "MarkDraftReadUseCase",
    "TrackMobileEventUseCase",
    "GetMobileStatsUseCase",
    "GetPreferencesUseCase",
    "UpdatePreferencesUseCase",
    "GetAppConfigUseCase",
    "UpdateAppConfigUseCase",
    "MobileCompanionService",
    # Real-time Edit
    "StartEditSessionUseCase",
    "ProcessTextChangeUseCase",
    "GetSuggestionUseCase",
    "ApplySuggestionUseCase",
    "CloseEditSessionUseCase",
    "GetEditSessionUseCase",
    "CleanupExpiredSessionsUseCase",
    # Phishing Detection
    "DetectPhishingUseCase",
    # Commitment Tracking
    "CommitmentTrackingUseCase",
    # Email Labels
    "LabelEmailUseCase",
    "LearnLabelingRuleUseCase",
    # Contact Analysis
    "AnalyzeContactHistoryUseCase",
    # Regenerate Draft
    "RegenerateEmailUseCase",
    "RegenerateResult",
]
