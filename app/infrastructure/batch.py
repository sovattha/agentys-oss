# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Batch processing optimisé pour le traitement de multiples emails.

Permet de traiter les emails par lots avec parallélisation,
gestion des erreurs et reprise après échec.

Usage:
    from app.infrastructure.batch import BatchProcessor, BatchResult

    processor = BatchProcessor(
        process_func=process_email,
        batch_size=10,
        max_workers=4
    )

    results = processor.process(emails)
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from typing import TypeVar, Generic, List, Callable, Optional, Dict
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

from app.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar('T')
R = TypeVar('R')


# ============================================================================
# ENUMS ET TYPES
# ============================================================================

class BatchItemStatus(Enum):
    """Statut d'un élément du batch."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class BatchItemResult(Generic[T, R]):
    """Résultat du traitement d'un élément."""
    item: T
    status: BatchItemStatus
    result: Optional[R] = None
    error: Optional[str] = None
    processing_time: float = 0.0
    retries: int = 0


@dataclass
class BatchResult(Generic[T, R]):
    """Résultat global du traitement batch."""
    total: int
    successful: int
    failed: int
    skipped: int
    items: List[BatchItemResult[T, R]]
    total_time: float
    started_at: datetime
    finished_at: datetime

    @property
    def success_rate(self) -> float:
        """Taux de succès en pourcentage."""
        if self.total == 0:
            return 0.0
        return (self.successful / self.total) * 100

    @property
    def avg_processing_time(self) -> float:
        """Temps de traitement moyen par élément."""
        successful_items = [i for i in self.items if i.status == BatchItemStatus.SUCCESS]
        if not successful_items:
            return 0.0
        return sum(i.processing_time for i in successful_items) / len(successful_items)

    def get_failed_items(self) -> List[BatchItemResult[T, R]]:
        """Retourne les éléments en échec."""
        return [i for i in self.items if i.status == BatchItemStatus.FAILED]

    def to_dict(self) -> dict:
        """Convertit en dictionnaire."""
        return {
            "total": self.total,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "success_rate": round(self.success_rate, 2),
            "avg_processing_time": round(self.avg_processing_time, 3),
            "total_time": round(self.total_time, 2),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
        }


# ============================================================================
# BATCH PROCESSOR
# ============================================================================

class BatchProcessor(Generic[T, R]):
    """
    Processeur de batch avec parallélisation.

    Attributes:
        process_func: Fonction de traitement pour chaque élément
        batch_size: Nombre d'éléments par batch
        max_workers: Nombre de workers parallèles
        max_retries: Nombre maximum de tentatives par élément
        retry_delay: Délai entre les tentatives (secondes)
    """

    def __init__(
        self,
        process_func: Callable[[T], R],
        batch_size: int = 10,
        max_workers: int = 4,
        max_retries: int = 2,
        retry_delay: float = 1.0,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_item_complete: Optional[Callable[[BatchItemResult], None]] = None,
    ):
        self.process_func = process_func
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.on_progress = on_progress
        self.on_item_complete = on_item_complete

        self._stop_requested = threading.Event()
        self._lock = threading.Lock()
        self._processed_count = 0

    def process(
        self,
        items: List[T],
        skip_func: Optional[Callable[[T], bool]] = None
    ) -> BatchResult[T, R]:
        """
        Traite une liste d'éléments par batch.

        Args:
            items: Liste d'éléments à traiter
            skip_func: Fonction pour décider si un élément doit être ignoré

        Returns:
            BatchResult avec les résultats
        """
        started_at = datetime.now()
        self._stop_requested.clear()
        self._processed_count = 0

        results: List[BatchItemResult[T, R]] = []
        total = len(items)

        logger.info(f"Starting batch processing: {total} items, batch_size={self.batch_size}")

        # Traiter par batches
        for batch_start in range(0, total, self.batch_size):
            if self._stop_requested.is_set():
                logger.warning("Batch processing stopped by request")
                break

            batch_end = min(batch_start + self.batch_size, total)
            batch = items[batch_start:batch_end]

            batch_results = self._process_batch(batch, skip_func)
            results.extend(batch_results)

            # Callback de progression
            if self.on_progress:
                self.on_progress(len(results), total)

        finished_at = datetime.now()
        total_time = (finished_at - started_at).total_seconds()

        # Compiler les statistiques
        successful = sum(1 for r in results if r.status == BatchItemStatus.SUCCESS)
        failed = sum(1 for r in results if r.status == BatchItemStatus.FAILED)
        skipped = sum(1 for r in results if r.status == BatchItemStatus.SKIPPED)

        logger.info(
            f"Batch processing complete: {successful}/{total} successful, "
            f"{failed} failed, {skipped} skipped in {total_time:.2f}s"
        )

        return BatchResult(
            total=total,
            successful=successful,
            failed=failed,
            skipped=skipped,
            items=results,
            total_time=total_time,
            started_at=started_at,
            finished_at=finished_at,
        )

    def _process_batch(
        self,
        batch: List[T],
        skip_func: Optional[Callable[[T], bool]]
    ) -> List[BatchItemResult[T, R]]:
        """Traite un batch d'éléments en parallèle."""
        results: List[BatchItemResult[T, R]] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_item: Dict[Future, T] = {}

            for item in batch:
                # Vérifier si l'élément doit être ignoré
                if skip_func and skip_func(item):
                    results.append(BatchItemResult(
                        item=item,
                        status=BatchItemStatus.SKIPPED,
                    ))
                    continue

                future = executor.submit(self._process_item_with_retry, item)
                future_to_item[future] = item

            # Collecter les résultats
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    result = future.result()
                    results.append(result)

                    if self.on_item_complete:
                        self.on_item_complete(result)

                except Exception as e:
                    logger.error(f"Unexpected error processing item: {e}")
                    results.append(BatchItemResult(
                        item=item,
                        status=BatchItemStatus.FAILED,
                        error=str(e),
                    ))

        return results

    def _process_item_with_retry(self, item: T) -> BatchItemResult[T, R]:
        """Traite un élément avec retry."""
        start_time = time.time()
        last_error = None
        retries = 0

        for attempt in range(self.max_retries + 1):
            try:
                result = self.process_func(item)
                processing_time = time.time() - start_time

                with self._lock:
                    self._processed_count += 1

                return BatchItemResult(
                    item=item,
                    status=BatchItemStatus.SUCCESS,
                    result=result,
                    processing_time=processing_time,
                    retries=retries,
                )

            except Exception as e:
                last_error = str(e)
                retries = attempt

                if attempt < self.max_retries:
                    logger.warning(f"Retry {attempt + 1}/{self.max_retries} for item: {e}")
                    time.sleep(self.retry_delay * (attempt + 1))  # Backoff
                else:
                    logger.error(f"Failed after {self.max_retries + 1} attempts: {e}")

        processing_time = time.time() - start_time

        return BatchItemResult(
            item=item,
            status=BatchItemStatus.FAILED,
            error=last_error,
            processing_time=processing_time,
            retries=retries,
        )

    def stop(self) -> None:
        """Demande l'arrêt du traitement."""
        self._stop_requested.set()

    @property
    def processed_count(self) -> int:
        """Nombre d'éléments traités."""
        return self._processed_count


# ============================================================================
# HELPERS
# ============================================================================

def process_in_batches(
    items: List[T],
    process_func: Callable[[T], R],
    batch_size: int = 10,
    max_workers: int = 4,
) -> BatchResult[T, R]:
    """
    Helper pour traiter rapidement une liste par batch.

    Args:
        items: Liste d'éléments
        process_func: Fonction de traitement
        batch_size: Taille des batches
        max_workers: Nombre de workers

    Returns:
        BatchResult
    """
    processor = BatchProcessor(
        process_func=process_func,
        batch_size=batch_size,
        max_workers=max_workers,
    )
    return processor.process(items)
