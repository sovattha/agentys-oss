# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Entités du domaine."""

from .email import Email
from .draft import Draft, Critique, ProcessingResult, DraftStatus
from .token_usage import TokenUsage
from .classification import (
    EmailCategory,
    Classification,
    Priority,
    EmailAnalysis,
)
from .email_labels import (
    DefaultLabel as DefaultLabel,
    EmailLabel as EmailLabel,
    LabelAssignment as LabelAssignment,
    LabelingRule as LabelingRule,
    LABEL_COLORS as LABEL_COLORS,
    get_default_labels as get_default_labels,
)
from .push_notification import (
    DeviceToken,
    DevicePlatform,
    PushNotification,
    PushNotificationStatus,
    PushNotificationCategory,
    PushNotificationRecord,
)
from .draft_input import DraftInput, DraftInputTone, CompletedDraft
from .wizard_config import (
    WizardConfig,
    BusinessSector,
    CompanySize,
    ConfigPack,
    AgentActivation,
    KnowledgeBaseConfig,
)
from .marketplace import (
    AgentCategory,
    AgentPricingModel,
    AgentStatus,
    InstallationStatus,
    AgentPricing,
    AgentCapabilitySpec,
    Publisher,
    MarketplaceAgent,
    AgentPack,
    AgentInstallation,
    AgentReview,
    MarketplaceSearchQuery,
    MarketplaceSearchResult,
)
from .fine_tuning import (
    CorrectionType,
    ImprovementStatus,
    FeedbackSentiment,
    UserCorrection,
    UserFeedback,
    CorrectionPattern,
    ImprovementModel,
    FineTuningSession,
    FineTuningStats,
)
from .mobile_companion import (
    MobileEventType,
    SyncStatus,
    MobileDraftAction,
    NotificationPreference,
    SyncFrequency,
    MobileSession,
    MobileSyncState,
    MobileAnalyticsEvent,
    MobileDraft,
    MobileUserPreferences,
    MobileAppConfig,
    MobileSyncResponse,
    MobileDraftActionRequest,
    MobileStats,
)
from .learning import (
    PatternType,
    LearningInsights,
    LearnedPattern,
    PromptAdjustment,
    ReviewRequirement,
    LearningStats,
)
from .realtime_edit import (
    ChangeType,
    TriggerType,
    SuggestionType,
    SuggestionStatus,
    TextDiff,
    TextChange,
    EditTrigger,
    Suggestion,
    SuggestionResult,
    EditSession,
)
from .draft_history import DraftRecord
from .calendar_event import (
    CalendarEvent,
    CalendarEventStatus,
    CalendarEventType,
)
from .followup_event import (
    FollowupEvent,
    FollowupEventStatus,
)
from .analytics import (
    QualityScore,
    HumanEdit,
    PerformanceMetrics,
    QualityMetrics,
    AIVsHumanComparison,
)
from .phishing import PhishingResult, SuspiciousUrl
from .commitment import (
    Commitment,
    CommitmentStatus,
)
from .sensitive_data import (
    SensitiveDataType,
    SensitiveDataItem,
    SensitiveDataDetection,
)
from .communication_channel import (
    ChannelType,
    ChannelStatus,
    ChannelConfig,
    ChannelMetrics,
    CommunicationChannel,
)
from .contact_context import (
    DominantTone,
    TopicInfo,
    ContactContext,
)
from .relationship_type import (
    RelationshipType,
    CommunicationFrequency,
    RelationshipDetection,
)
from .context_transparency import (
    AnalyzedEmailSummary,
    StyleProfileSummary,
    RelationshipSummary,
    ContextTransparencyData,
)
from .draft_generation import (
    DraftTone,
    DraftStatus as DraftGenerationStatus,
    DraftRequest,
    DraftResult,
    StreamingDraftChunk,
)
from .critique import (
    CritiqueDecision,
    CritiqueStatus,
    CritiqueScores,
    CritiqueRequest,
    CritiqueResult,
    ToneClassification,
    ToneResult,
    TONE_DESCRIPTIONS,
)
from .orchestration import (
    OrchestrationStatus,
    IterationRecord,
    OrchestrationRequest,
    OrchestrationResult,
)

__all__ = [
    "Email",
    "Draft",
    "Critique",
    "ProcessingResult",
    "DraftStatus",
    "TokenUsage",
    # Classification & Priority
    "EmailCategory",
    "Classification",
    "Priority",
    "EmailAnalysis",
    "DeviceToken",
    "DevicePlatform",
    "PushNotification",
    "PushNotificationStatus",
    "PushNotificationCategory",
    "PushNotificationRecord",
    "DraftInput",
    "DraftInputTone",
    "CompletedDraft",
    "WizardConfig",
    "BusinessSector",
    "CompanySize",
    "ConfigPack",
    "AgentActivation",
    "KnowledgeBaseConfig",
    # Marketplace
    "AgentCategory",
    "AgentPricingModel",
    "AgentStatus",
    "InstallationStatus",
    "AgentPricing",
    "AgentCapabilitySpec",
    "Publisher",
    "MarketplaceAgent",
    "AgentPack",
    "AgentInstallation",
    "AgentReview",
    "MarketplaceSearchQuery",
    "MarketplaceSearchResult",
    # Fine-tuning
    "CorrectionType",
    "ImprovementStatus",
    "FeedbackSentiment",
    "UserCorrection",
    "UserFeedback",
    "CorrectionPattern",
    "ImprovementModel",
    "FineTuningSession",
    "FineTuningStats",
    # Mobile companion
    "MobileEventType",
    "SyncStatus",
    "MobileDraftAction",
    "NotificationPreference",
    "SyncFrequency",
    "MobileSession",
    "MobileSyncState",
    "MobileAnalyticsEvent",
    "MobileDraft",
    "MobileUserPreferences",
    "MobileAppConfig",
    "MobileSyncResponse",
    "MobileDraftActionRequest",
    "MobileStats",
    # Learning
    "PatternType",
    "LearningInsights",
    "LearnedPattern",
    "PromptAdjustment",
    "ReviewRequirement",
    "LearningStats",
    # Real-time Edit
    "ChangeType",
    "TriggerType",
    "SuggestionType",
    "SuggestionStatus",
    "TextDiff",
    "TextChange",
    "EditTrigger",
    "Suggestion",
    "SuggestionResult",
    "EditSession",
    # Draft History
    "DraftRecord",
    # Calendar
    "CalendarEvent",
    "CalendarEventStatus",
    "CalendarEventType",
    # Followup Event (Calendar integration)
    "FollowupEvent",
    "FollowupEventStatus",
    # Analytics
    "QualityScore",
    "HumanEdit",
    "PerformanceMetrics",
    "QualityMetrics",
    "AIVsHumanComparison",
    # Phishing
    "PhishingResult",
    "SuspiciousUrl",
    # Commitment
    "Commitment",
    "CommitmentStatus",
    # Sensitive Data
    "SensitiveDataType",
    "SensitiveDataItem",
    "SensitiveDataDetection",
    # Communication Channel
    "ChannelType",
    "ChannelStatus",
    "ChannelConfig",
    "ChannelMetrics",
    "CommunicationChannel",
    # Contact Context
    "DominantTone",
    "TopicInfo",
    "ContactContext",
    # Relationship Type
    "RelationshipType",
    "CommunicationFrequency",
    "RelationshipDetection",
    # Context Transparency
    "AnalyzedEmailSummary",
    "StyleProfileSummary",
    "RelationshipSummary",
    "ContextTransparencyData",
    # Draft Generation (Story 5-1)
    "DraftTone",
    "DraftGenerationStatus",
    "DraftRequest",
    "DraftResult",
    "StreamingDraftChunk",
    # Critique (Story 5-2)
    "CritiqueDecision",
    "CritiqueStatus",
    "CritiqueScores",
    "CritiqueRequest",
    "CritiqueResult",
    # Tone Classification (Story 5-5)
    "ToneClassification",
    "ToneResult",
    "TONE_DESCRIPTIONS",
    # Orchestration (Story 5-3)
    "OrchestrationStatus",
    "IterationRecord",
    "OrchestrationRequest",
    "OrchestrationResult",
]
