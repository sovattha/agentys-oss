# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Ports (Interfaces) du domaine.

Les ports définissent les contrats que les adapters externes doivent implémenter.
Cela permet de découpler le domaine des implémentations concrètes.

Organisation:
- Core: LLM, Email, Time, Notifications
- Classification & Prioritization
- Wizard Configuration
- Marketplace
- Fine-tuning
- Mobile Companion
"""

# Core Ports
from .llm_port import LLMPort, LLMResponse, LLMStreamChunk
from .email_port import EmailPort
from .time_provider import TimeProvider
from .notification_port import (
    NotificationPort,
    NotificationPlatform,
    NotificationPriority,
    PushNotificationResult,
)
from .device_store_port import DeviceStorePort

# Wizard Configuration
from .wizard_config_port import WizardConfigPort

# Classification & Prioritization
from .classification_port import (
    ClassifierPort,
    PrioritizationPort,
    EmailAnalyzerPort,
)

# Marketplace
from .marketplace_port import (
    MarketplaceAgentPort,
    AgentPackPort,
    AgentInstallationPort,
    AgentReviewPort,
    PublisherPort,
)

# Fine-tuning
from .fine_tuning_port import (
    UserCorrectionPort,
    UserFeedbackPort,
    CorrectionPatternPort,
    ImprovementModelPort,
    FineTuningSessionPort,
    FineTuningAnalyzerPort,
    FineTuningStatsPort,
)

# Mobile Companion
from .mobile_companion_port import (
    MobileSessionPort,
    MobileSyncPort,
    MobileDraftActionPort,
    MobileAnalyticsPort,
    MobileUserPreferencesPort,
    MobileAppConfigPort,
)

# Learning
from .learning_port import (
    LearningPatternStorePort,
    AdjustmentStorePort,
    LearningFeedbackProviderPort,
    LearningServicePort,
)

# Real-time Edit
from .realtime_edit_port import (
    EditSessionStorePort,
    RealTimeEditPort,
    SuggestionHistoryPort,
)

# Item Tracking (Generic Port)
from .item_tracker_port import ItemTrackerPort

# Legacy Migration Ports
from .draft_history_port import DraftHistoryPort
from .analytics_port import AnalyticsPort
from .token_counter_port import TokenCounterPort
from .processed_emails_port import ProcessedEmailsTrackerPort
from .processed_drafts_port import ProcessedDraftsTrackerPort

# Commitment
from .commitment_port import CommitmentTrackerPort

# Task Extraction
from .task_port import TaskPort

# Sensitive Data Detection
from .sensitive_data_port import SensitiveDataDetectorPort

# Communication Channel
from .communication_channel_port import CommunicationChannelPort

# Cryptography
from .cryptographer_port import CryptographerPort

# Pending Drafts
from .pending_draft_port import PendingDraftStorePort

# Contact Analyzer
from .contact_analyzer_port import ContactAnalyzerPort

# Calendar
from .calendar_port import CalendarPort

__all__ = [
    # Core Ports
    "LLMPort",
    "LLMResponse",
    "LLMStreamChunk",
    "EmailPort",
    "TimeProvider",
    "NotificationPort",
    "NotificationPlatform",
    "NotificationPriority",
    "PushNotificationResult",
    "DeviceStorePort",
    # Wizard Configuration
    "WizardConfigPort",
    # Classification & Prioritization
    "ClassifierPort",
    "PrioritizationPort",
    "EmailAnalyzerPort",
    # Marketplace
    "MarketplaceAgentPort",
    "AgentPackPort",
    "AgentInstallationPort",
    "AgentReviewPort",
    "PublisherPort",
    # Fine-tuning
    "UserCorrectionPort",
    "UserFeedbackPort",
    "CorrectionPatternPort",
    "ImprovementModelPort",
    "FineTuningSessionPort",
    "FineTuningAnalyzerPort",
    "FineTuningStatsPort",
    # Mobile Companion
    "MobileSessionPort",
    "MobileSyncPort",
    "MobileDraftActionPort",
    "MobileAnalyticsPort",
    "MobileUserPreferencesPort",
    "MobileAppConfigPort",
    # Learning
    "LearningPatternStorePort",
    "AdjustmentStorePort",
    "LearningFeedbackProviderPort",
    "LearningServicePort",
    # Real-time Edit
    "EditSessionStorePort",
    "RealTimeEditPort",
    "SuggestionHistoryPort",
    # Item Tracking (Generic Port)
    "ItemTrackerPort",
    # Legacy Migration Ports
    "DraftHistoryPort",
    "AnalyticsPort",
    "TokenCounterPort",
    "ProcessedEmailsTrackerPort",
    "ProcessedDraftsTrackerPort",
    # Commitment
    "CommitmentTrackerPort",
    # Task Extraction
    "TaskPort",
    # Sensitive Data Detection
    "SensitiveDataDetectorPort",
    # Communication Channel
    "CommunicationChannelPort",
    # Cryptography
    "CryptographerPort",
    # Pending Drafts
    "PendingDraftStorePort",
    # Contact Analyzer
    "ContactAnalyzerPort",
    # Calendar
    "CalendarPort",
]
