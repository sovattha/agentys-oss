"""
Gestion de l'historique des brouillons générés.

Stocke les brouillons créés par le daemon dans un fichier JSON
pour traçabilité et analyse.
"""

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any

from app.config import PROJECT_ROOT, should_persist_email_content
from app.domain.services.anonymizer_service import DataAnonymizer
from app.domain.ports.sensitive_data_port import SensitiveDataDetectorPort
from app.domain.entities.anonymization import SecureAnonymizedData

# ============================================================================
# CONFIGURATION
# ============================================================================

HISTORY_DIR = PROJECT_ROOT / "data" / "history"
HISTORY_FILE = HISTORY_DIR / "drafts_history.json"

# ============================================================================
# MODÈLES
# ============================================================================

@dataclass
class DraftRecord:
    """Enregistrement d'un brouillon généré."""
    id: str                          # ID unique
    timestamp: str                   # Date/heure ISO
    email_id: str                    # ID de l'email original
    email_sender: str                # Expéditeur
    email_subject: str               # Sujet
    email_preview: str               # Aperçu de l'email (100 premiers chars)
    draft_v1: str                    # Première version
    critique: str                    # Critique du Critic
    draft_final: str                 # Version finale
    status: str                      # VALIDÉ V1 / CORRIGÉ V2
    account_id: Optional[int] = None # ID du compte propriétaire (isolation multi-compte)
    draft_id: Optional[str] = None   # ID du brouillon créé (Gmail/Outlook)
    tokens_used: int = 0             # Tokens utilisés
    model: str = ""                  # Modèle utilisé
    feedback: Optional[str] = None   # Feedback utilisateur (pour apprentissage)
    feedback_rating: Optional[int] = None  # Note (1-5)
    feedback_comment: Optional[str] = None  # Commentaire de feedback
    processing_time_ms: int = 0      # Temps de traitement en millisecondes
    priority_score: Optional[int] = None  # Score de priorité (0-100)
    category: Optional[str] = None   # Catégorie de l'email

    def to_correction_context(self) -> Dict[str, Any]:
        """
        Retourne les métadonnées pour les corrections.

        Returns:
            Dictionnaire avec sender, subject et category.
        """
        return {
            "sender": self.email_sender,
            "subject": self.email_subject,
            "category": self.category,
        }


@dataclass
class AnonymizationConfig:
    """Configuration pour l'anonymisation dans DraftHistory."""
    anonymizer: DataAnonymizer
    detector: SensitiveDataDetectorPort
    encryption_key: bytes


# ============================================================================
# GESTIONNAIRE D'HISTORIQUE
# ============================================================================

class DraftHistory:
    """
    Gestionnaire de l'historique des brouillons.

    Stocke les brouillons dans un fichier JSON pour :
    - Traçabilité
    - Analyse des performances
    - Mode apprentissage (feedback)
    """

    def __init__(
        self,
        history_file: Path = HISTORY_FILE,
        anonymization_config: Optional[AnonymizationConfig] = None,
    ):
        self.history_file = history_file
        self._anonymization_config = anonymization_config
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Crée le dossier si nécessaire."""
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

    _CONTENT_FIELDS = ("email_preview", "draft_v1", "critique", "draft_final")
    _SENSITIVE_FIELDS = ("email_sender", "email_preview", "draft_v1", "draft_final")

    def _minimize_record_dict(self, record_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Supprime le contenu email/draft si le mode metadata-only est actif."""
        if should_persist_email_content():
            return record_dict
        for field in self._CONTENT_FIELDS:
            record_dict[field] = ""
        return record_dict

    def _anonymize_record(self, record_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Anonymise les champs sensibles d'un record."""
        if not self._anonymization_config:
            return record_dict

        config = self._anonymization_config
        anonymization_data: Dict[str, Any] = {}

        for field in self._SENSITIVE_FIELDS:
            if field not in record_dict or not record_dict[field]:
                continue

            text = record_dict[field]
            detection = config.detector.detect(text, "")
            secure_data = config.anonymizer.anonymize(
                text, detection, config.encryption_key
            )

            record_dict[field] = secure_data.result.anonymized_text
            anonymization_data[field] = secure_data.to_dict()

        if anonymization_data:
            record_dict["_anonymization_data"] = anonymization_data

        return record_dict

    def _reveal_record(self, record_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Révèle les données anonymisées d'un record."""
        if not self._anonymization_config:
            return record_dict

        if "_anonymization_data" not in record_dict:
            return record_dict

        config = self._anonymization_config
        anonymization_data = record_dict["_anonymization_data"]

        for field in self._SENSITIVE_FIELDS:
            if field not in anonymization_data:
                continue

            secure_data = SecureAnonymizedData.from_dict(anonymization_data[field])
            record_dict[field] = config.anonymizer.reveal(
                secure_data, config.encryption_key
            )

        return record_dict

    def _load(self) -> List[dict]:
        """Charge l'historique depuis le fichier."""
        if not self.history_file.exists():
            return []
        try:
            data = json.loads(self.history_file.read_text(encoding="utf-8"))
            # Gérer le cas où le JSON contient null ou n'est pas une liste
            if not isinstance(data, list):
                return []
            return data
        except (json.JSONDecodeError, Exception):
            return []

    def _save(self, records: List[dict]) -> None:
        """Sauvegarde l'historique."""
        self.history_file.write_text(
            json.dumps(records, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def add(self, record: DraftRecord) -> None:
        """
        Ajoute un brouillon à l'historique.

        Args:
            record: Enregistrement du brouillon.
        """
        records = self._load()
        record_dict = asdict(record)
        record_dict = self._minimize_record_dict(record_dict)
        record_dict = self._anonymize_record(record_dict)
        records.append(record_dict)
        self._save(records)

    def get_all(self, limit: int = 100) -> List[DraftRecord]:
        """
        Récupère tous les brouillons.

        Args:
            limit: Nombre maximum de brouillons.

        Returns:
            Liste des brouillons (plus récents en premier).
        """
        records = self._load()
        records = sorted(records, key=lambda x: x.get("timestamp", ""), reverse=True)
        result = []
        for r in records[:limit]:
            try:
                revealed = self._reveal_record(r.copy())
                revealed.pop("_anonymization_data", None)
                result.append(DraftRecord(**revealed))
            except TypeError:
                continue
        return result

    def get_by_id(self, record_id: str) -> Optional[DraftRecord]:
        """
        Récupère un brouillon par son ID.

        Args:
            record_id: ID du brouillon.

        Returns:
            Le brouillon ou None.
        """
        records = self._load()
        for r in records:
            if r.get("id") == record_id:
                revealed = self._reveal_record(r.copy())
                revealed.pop("_anonymization_data", None)
                return DraftRecord(**revealed)
        return None

    def update_feedback(
        self,
        record_id: str,
        feedback: str,
        comment: str = ""
    ) -> bool:
        """
        Met à jour le feedback d'un brouillon.

        Args:
            record_id: ID du brouillon.
            feedback: Type de feedback ("positive", "negative", "neutral").
            comment: Commentaire optionnel.

        Returns:
            True si mis à jour.
        """
        records = self._load()
        for r in records:
            if r.get("id") == record_id:
                r["feedback"] = feedback
                r["feedback_comment"] = comment
                self._save(records)
                return True
        return False

    def _get_empty_stats(self) -> dict:
        """Retourne des statistiques vides."""
        return {
            "total": 0,
            "validated_v1": 0,
            "corrected_v2": 0,
            "avg_rating": 0,
            "total_tokens": 0,
            "time_saved_minutes": 0,
            "avg_processing_time_ms": 0,
            "automation_rate": 0,
            "daily_stats": [],
        }

    def _count_by_status(self, records: List[dict]) -> tuple:
        """Compte les brouillons par statut (V1, V2)."""
        validated_v1 = sum(1 for r in records if "V1" in r.get("status", ""))
        corrected_v2 = sum(1 for r in records if "V2" in r.get("status", ""))
        return validated_v1, corrected_v2

    def _compute_rating_stats(self, records: List[dict]) -> tuple:
        """Calcule les statistiques de notation."""
        ratings = [r.get("feedback_rating") for r in records if r.get("feedback_rating")]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0
        return avg_rating, len(ratings)

    def _compute_processing_time(self, records: List[dict]) -> float:
        """Calcule le temps moyen de traitement."""
        processing_times = [
            r.get("processing_time_ms", 0)
            for r in records
            if r.get("processing_time_ms", 0) > 0
        ]
        return sum(processing_times) / len(processing_times) if processing_times else 0

    def _compute_automation_rate(self, total: int, validated_v1: int, corrected_v2: int) -> int:
        """Calcule le taux d'automatisation (V1 = 100%, V2 = 50%)."""
        if total == 0:
            return 0
        return round((validated_v1 * 100 + corrected_v2 * 50) / total)

    def get_stats(self) -> dict:
        """
        Calcule les statistiques de l'historique.

        Returns:
            Dictionnaire de statistiques.
        """
        records = self._load()

        if not records:
            return self._get_empty_stats()

        total = len(records)
        validated_v1, corrected_v2 = self._count_by_status(records)
        avg_rating, ratings_count = self._compute_rating_stats(records)
        avg_processing_time_ms = self._compute_processing_time(records)
        automation_rate = self._compute_automation_rate(total, validated_v1, corrected_v2)

        total_tokens = sum(r.get("tokens_used", 0) for r in records)
        time_saved_minutes = total * 5  # 5 min par email traité

        return {
            "total": total,
            "validated_v1": validated_v1,
            "corrected_v2": corrected_v2,
            "v1_percent": round(validated_v1 / total * 100),
            "v2_percent": round(corrected_v2 / total * 100),
            "avg_rating": round(avg_rating, 1),
            "ratings_count": ratings_count,
            "total_tokens": total_tokens,
            "time_saved_minutes": time_saved_minutes,
            "time_saved_hours": round(time_saved_minutes / 60, 1),
            "avg_processing_time_ms": round(avg_processing_time_ms),
            "avg_processing_time_sec": round(avg_processing_time_ms / 1000, 1),
            "automation_rate": automation_rate,
            "daily_stats": self._get_daily_stats(records),
        }

    def _get_daily_stats(self, records: List[dict]) -> List[dict]:
        """Calcule les statistiques par jour pour les graphiques."""
        from collections import defaultdict

        daily = defaultdict(lambda: {"date": "", "total": 0, "v1": 0, "v2": 0, "tokens": 0})

        for r in records:
            timestamp = r.get("timestamp", "")
            if timestamp:
                date = timestamp[:10]  # YYYY-MM-DD
                daily[date]["date"] = date
                daily[date]["total"] += 1
                if "V1" in r.get("status", ""):
                    daily[date]["v1"] += 1
                if "V2" in r.get("status", ""):
                    daily[date]["v2"] += 1
                daily[date]["tokens"] += r.get("tokens_used", 0)

        # Trier par date et retourner les 30 derniers jours
        sorted_days = sorted(daily.values(), key=lambda x: x["date"])
        return sorted_days[-30:]

    def search(
        self,
        query: Optional[str] = None,
        status: Optional[str] = None,
        min_rating: Optional[int] = None,
        limit: int = 50
    ) -> List[DraftRecord]:
        """
        Recherche dans l'historique.

        Args:
            query: Texte à rechercher dans sujet/expéditeur.
            status: Filtrer par status (V1, V2).
            min_rating: Note minimale.
            limit: Nombre maximum de résultats.

        Returns:
            Liste des brouillons correspondants.
        """
        records = self._load()
        results = []

        for r in records:
            # Filtre par query
            if query:
                query_lower = query.lower()
                email_subject = r.get("email_subject") or ""
                email_sender = r.get("email_sender") or ""
                if (query_lower not in email_subject.lower() and
                    query_lower not in email_sender.lower()):
                    continue

            # Filtre par status
            if status and status not in r.get("status", ""):
                continue

            # Filtre par rating
            if min_rating and (r.get("feedback_rating") or 0) < min_rating:
                continue

            # Retirer les métadonnées d'anonymisation avant création du record
            record_data = {k: v for k, v in r.items() if k != "_anonymization_data"}
            results.append(DraftRecord(**record_data))

        # Trier par date décroissante
        results.sort(key=lambda x: x.timestamp, reverse=True)
        return results[:limit]

    def export_for_training(self) -> List[dict]:
        """
        Exporte les données pour entraînement/fine-tuning.

        Returns:
            Liste de paires (email, réponse idéale) avec bon rating.
        """
        if not should_persist_email_content():
            return []

        records = self._load()
        training_data = []

        for r in records:
            # Inclure seulement les brouillons avec bon feedback
            rating = r.get("feedback_rating")
            if rating is not None and rating >= 4:
                training_data.append({
                    "email": r.get("email_preview", ""),
                    "response": r.get("draft_final", ""),
                    "rating": r.get("feedback_rating"),
                })

        return training_data

    def export_csv(self) -> str:
        """
        Exporte l'historique au format CSV.

        Returns:
            Contenu CSV en string.
        """
        import csv
        from io import StringIO

        records = self._load()
        if not records:
            return "Aucune donnée"

        output = StringIO()
        fieldnames = [
            "id", "timestamp", "email_sender", "email_subject",
            "status", "tokens_used", "model", "feedback_rating",
            "processing_time_ms", "priority_score", "category"
        ]

        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for r in records:
            writer.writerow(r)

        return output.getvalue()

    def clear(self) -> None:
        """Efface tout l'historique."""
        self._save([])


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def create_record(
    email_id: str,
    email_sender: str,
    email_subject: str,
    email_body: str,
    draft_v1: str,
    critique: str,
    draft_final: str,
    status: str,
    account_id: Optional[int] = None,
    draft_id: Optional[str] = None,
    tokens_used: int = 0,
    model: str = "",
    processing_time_ms: int = 0,
    priority_score: Optional[int] = None,
    category: Optional[str] = None,
) -> DraftRecord:
    """
    Crée un enregistrement de brouillon.

    Helper pour créer un DraftRecord avec ID et timestamp automatiques.

    account_id doit être fourni par l'appelant (résolu via JWT ou via
    le contexte daemon/batch). Un record sans account_id ne sera pas
    persisté par les adapters scoped (ils assertent > 0).
    """
    import uuid

    return DraftRecord(
        id=str(uuid.uuid4())[:8],
        timestamp=datetime.now().isoformat(),
        email_id=email_id,
        email_sender=email_sender,
        email_subject=email_subject,
        email_preview=email_body[:100] + "..." if len(email_body) > 100 else email_body,
        draft_v1=draft_v1,
        critique=critique,
        draft_final=draft_final,
        status=status,
        account_id=account_id,
        draft_id=draft_id,
        tokens_used=tokens_used,
        model=model,
        processing_time_ms=processing_time_ms,
        priority_score=priority_score,
        category=category,
    )


# Instance globale
draft_history = DraftHistory()
