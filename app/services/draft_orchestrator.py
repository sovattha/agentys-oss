# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
DraftOrchestrator — orchestration du pipeline Drafter/Critic.

Coordonne la boucle DrafterAgent → CriticAgent → DrafterAgent V2 :

    1. génération initiale (V1)
    2. évaluation par CriticAgent
    3. si REJECT, révision par DrafterAgent avec feedback (V2)
    4. répétition jusqu'à VALID ou ``max_iterations``

Story 5-3 (Draft Regeneration Loop).

Historique architectural — gate SelfCritique retiré (2026-05-04) : un gate
optionnel (``AGENTYS_SELF_CRITIQUE_GATE``) compensait précédemment un FP rate
Critic de ~31 %. La refonte du Critic le 2026-05-04 (placeholder hard-rule
+ décision déterministe + 5 exemples calibrés en few-shot) a baissé le FP
à ~9 % (effectif 2.2 % sur cas labellisés cohéremment) — le gate est
devenu redondant et a été supprimé pour simplifier l'architecture. Voir
``docs/runbooks/self-critique-gate-rollout.md`` (notice de dépréciation)
pour le détail.
"""

import dataclasses
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from app.agents import DrafterAgent, CriticAgent
from app.domain.entities.draft_generation import DraftRequest, DraftResult, DraftStatus
from app.domain.entities.critique import (
    CritiqueDecision,
    CritiqueRequest,
    CritiqueResult,
    CritiqueStatus,
)
from app.domain.entities.orchestration import (
    OrchestrationStatus,
    IterationRecord,
    OrchestrationRequest,
    OrchestrationResult,
)

logger = logging.getLogger(__name__)


@dataclass
class DraftOrchestrator:
    """
    Orchestrateur du pipeline Drafter/Critic.

    Coordonne la génération de brouillons avec validation qualité via:
    1. Génération initiale par DrafterAgent
    2. Évaluation par CriticAgent
    3. Si REJECT: révision par DrafterAgent avec feedback
    4. Répétition jusqu'à VALID ou max_iterations

    Attributes:
        drafter: Instance du DrafterAgent.
        critic: Instance du CriticAgent.
        max_iterations: Nombre maximum d'itérations (default: 2).
        quality_threshold: Seuil de qualité (default: 70).
        timeout_seconds: Timeout global en secondes (default: 240).
        iteration_timeout_seconds: Timeout par itération (default: 60).
    """

    drafter: DrafterAgent = field(default_factory=DrafterAgent)
    critic: CriticAgent = field(default_factory=CriticAgent)
    max_iterations: int = 2
    quality_threshold: int = 70
    timeout_seconds: int = 240  # 4 minutes total (NFR2)
    iteration_timeout_seconds: int = 60

    def orchestrate(
        self,
        request: OrchestrationRequest,
        on_iteration_start: Optional[callable] = None,
        on_iteration_complete: Optional[callable] = None,
        on_draft_ready: Optional[callable] = None,
        on_critique_complete: Optional[callable] = None,
        on_revision_ready: Optional[callable] = None,
    ) -> OrchestrationResult:
        """
        Exécute le pipeline complet de génération avec validation.

        Args:
            request: Requête d'orchestration avec email et contexte.
            on_iteration_start: Callback appelé au début de chaque itération.
            on_iteration_complete: Callback appelé à la fin de chaque itération.
            on_draft_ready: NEW — Callback appelé dès que V1 est généré
                (avant le Critic). Permet à l'HTTP handler d'émettre un
                event WebSocket ``draft_ready_v1`` immédiatement, pour
                que le frontend affiche V1 et que l'utilisateur puisse
                lire/éditer pendant que le Critic tourne en arrière-plan.
                Signature : ``on_draft_ready(draft_result: DraftResult) -> None``.
            on_critique_complete: NEW — Callback appelé dès que le Critic
                rend son verdict pour une itération. Signature :
                ``on_critique_complete(critique: CritiqueResult,
                draft: DraftResult, iteration: int) -> None``.
                Permet d'émettre ``critique_complete`` pour mettre à
                jour le badge UI (⏳ → ✅ ou ⚠️).
            on_revision_ready: NEW — Callback appelé après génération
                d'une révision V2 (quand le Critic a rejeté V1).
                Signature : ``on_revision_ready(new_draft: DraftResult,
                prev_draft: DraftResult, prev_critique: CritiqueResult)
                -> None``. Permet d'émettre ``revision_suggested`` avec
                V1+V2 pour le diff prompt UI (option b).

        Audit 2026-05-04 (Async Critic backend) : les 3 nouveaux callbacks
        sont tous optionnels. Quand absents (default), l'orchestrateur se
        comporte exactement comme avant — ``OrchestrationResult`` reste
        retourné de façon synchrone. Quand présents, ils permettent au
        caller de découpler l'affichage de V1 du verdict Critic, gagnant
        ~1.5 s de latence perçue. Tous les callbacks sont try/except
        wrappés à l'intérieur de l'orchestrateur — une exception dans
        un callback n'interrompt JAMAIS le pipeline (même contrat que
        ``on_iteration_*``).

        Returns:
            OrchestrationResult avec le brouillon final et historique.
        """
        start_time = time.time()
        iterations: list[IterationRecord] = []
        current_draft_request = request.to_draft_request()

        logger.info(
            f"Starting orchestration for email {request.email_id or 'unknown'} "
            f"(max_iterations={request.max_iterations})"
        )

        # Utiliser les valeurs de la requête ou les defaults
        max_iters = request.max_iterations or self.max_iterations
        global_timeout = request.timeout_seconds or self.timeout_seconds

        for iteration_num in range(1, max_iters + 2):  # 1-based, +1 pour inclure génération initiale
            iteration_start = time.time()

            # Vérifier timeout global
            elapsed_total = time.time() - start_time
            if elapsed_total >= global_timeout:
                logger.warning(
                    f"Global timeout reached after {elapsed_total:.1f}s, "
                    f"returning best draft from {len(iterations)} iterations"
                )
                return self._create_timeout_result(
                    iterations=iterations,
                    total_duration_ms=int(elapsed_total * 1000),
                )

            # Callback de début d'itération
            if on_iteration_start:
                try:
                    on_iteration_start(request.email_id, iteration_num)
                except Exception as e:
                    logger.warning(f"on_iteration_start callback failed: {e}")

            # Générer ou réviser le brouillon
            if iteration_num == 1:
                logger.debug(f"Iteration {iteration_num}: Initial draft generation")
                draft_result = self._generate_initial_draft(current_draft_request)
                # Audit 2026-05-04 (Async Critic backend) : V1 prêt — fire
                # ``on_draft_ready`` AVANT le Critic. C'est le moment où
                # le frontend peut afficher V1 et débloquer Send.
                if on_draft_ready and draft_result.is_successful():
                    try:
                        on_draft_ready(draft_result)
                    except Exception as e:
                        logger.warning(f"on_draft_ready callback failed: {e}")
            else:
                previous_critique = iterations[-1].critique_result
                if previous_critique is None:
                    logger.error("No critique available for revision")
                    break

                logger.debug(
                    f"Iteration {iteration_num}: Revision based on critique "
                    f"(score={previous_critique.get_overall_score()})"
                )
                # Capture the prev draft / critique before we generate V2 —
                # both fields are needed by ``on_revision_ready`` so the
                # frontend can render the V1↔V2 diff (option b).
                prev_draft_for_callback = iterations[-1].draft_result
                # Audit F-07 (2026-05-03): build a copy carrying the draft
                # content for the revision call instead of mutating the
                # stored CritiqueResult — preserves audit-trail integrity
                # for any downstream replay/persistence consumer.
                revision_critique = dataclasses.replace(
                    previous_critique,
                    draft_content=iterations[-1].draft_result.content,
                )
                draft_result = self._revise_draft(current_draft_request, revision_critique)
                # Audit 2026-05-04 (Async Critic backend) : V2 prêt — fire
                # ``on_revision_ready`` avec V1 + V2 + critique pour que
                # le frontend puisse présenter le diff prompt.
                if on_revision_ready and draft_result.is_successful():
                    try:
                        on_revision_ready(
                            draft_result,
                            prev_draft_for_callback,
                            previous_critique,
                        )
                    except Exception as e:
                        logger.warning(f"on_revision_ready callback failed: {e}")

            # Vérifier si la génération a réussi (status ET contenu non-vide)
            if not draft_result.is_successful():
                logger.warning(
                    f"Draft generation failed: status={draft_result.status}, "
                    f"content_len={len(draft_result.content or '')}"
                )
                iteration_duration = int((time.time() - iteration_start) * 1000)
                iterations.append(
                    IterationRecord(
                        draft_result=draft_result,
                        critique_result=None,
                        iteration_number=iteration_num,
                        duration_ms=iteration_duration,
                    )
                )
                return self._create_failed_result(
                    iterations=iterations,
                    total_duration_ms=int((time.time() - start_time) * 1000),
                    error_message=f"Draft generation failed: {draft_result.status.value}",
                )

            # Évaluer le brouillon avec le Critic.
            critique_request = CritiqueRequest(
                draft_content=draft_result.content,
                original_email=request.email_content,
                context=request.instructions,
            )
            critique_result = self._evaluate_draft(critique_request)

            # Audit 2026-05-04 (Async Critic backend) : verdict du Critic
            # disponible — fire ``on_critique_complete`` pour mettre à
            # jour le badge UI (⏳ → ✅ ou ⚠️). Wrappé try/except : un
            # bug dans le callback ne doit JAMAIS interrompre la suite
            # de l'orchestration (notamment la possible révision V2).
            if on_critique_complete:
                try:
                    on_critique_complete(critique_result, draft_result, iteration_num)
                except Exception as e:
                    logger.warning(f"on_critique_complete callback failed: {e}")

            # Enregistrer l'itération
            iteration_duration = int((time.time() - iteration_start) * 1000)
            iteration_record = IterationRecord(
                draft_result=draft_result,
                critique_result=critique_result,
                iteration_number=iteration_num,
                duration_ms=iteration_duration,
            )
            iterations.append(iteration_record)

            logger.info(
                f"Iteration {iteration_num} complete: "
                f"score={critique_result.get_overall_score()}, "
                f"decision={critique_result.decision.value}"
            )

            # Callback de fin d'itération
            if on_iteration_complete:
                try:
                    on_iteration_complete(
                        request.email_id,
                        iteration_num,
                        critique_result.get_overall_score(),
                        critique_result.decision.value,
                    )
                except Exception as e:
                    logger.warning(f"on_iteration_complete callback failed: {e}")

            # Si le brouillon est validé, on retourne
            if critique_result.decision == CritiqueDecision.VALID:
                logger.info(
                    f"Draft validated on iteration {iteration_num} "
                    f"(score={critique_result.get_overall_score()})"
                )
                return OrchestrationResult(
                    final_draft=draft_result,
                    iterations=iterations,
                    total_duration_ms=int((time.time() - start_time) * 1000),
                    status=OrchestrationStatus.COMPLETED,
                )

        # Max iterations atteint - retourner le meilleur brouillon
        logger.info(
            f"Max iterations ({max_iters}) reached, returning best draft"
        )
        return self._select_best_result(
            iterations=iterations,
            total_duration_ms=int((time.time() - start_time) * 1000),
        )

    def _generate_initial_draft(self, request: DraftRequest) -> DraftResult:
        """Génère le brouillon initial avec gestion des erreurs."""
        try:
            return self.drafter.draft_with_retry(request)
        except Exception as e:
            logger.error(f"Initial draft generation failed: {e}")
            return DraftResult(
                content="",
                confidence=0.0,
                status=DraftStatus.FAILED,
                error_message=str(e),
            )

    def _revise_draft(
        self,
        request: DraftRequest,
        critique: CritiqueResult,
    ) -> DraftResult:
        """Révise le brouillon basé sur la critique."""
        try:
            return self.drafter.revise_with_critique_and_retry(request, critique)
        except Exception as e:
            logger.error(f"Draft revision failed: {e}")
            return DraftResult(
                content="",
                confidence=0.0,
                status=DraftStatus.FAILED,
                error_message=str(e),
            )

    def _evaluate_draft(self, request: CritiqueRequest) -> CritiqueResult:
        """Évalue le brouillon avec le CriticAgent."""
        try:
            return self.critic.evaluate_draft_with_retry(request)
        except Exception as e:
            logger.error(f"Draft evaluation failed: {e}")
            return CritiqueResult.create_failed(
                error_message=str(e),
                status=CritiqueStatus.FAILED,
            )

    def _select_best_result(
        self,
        iterations: list[IterationRecord],
        total_duration_ms: int,
    ) -> OrchestrationResult:
        """Sélectionne le meilleur brouillon parmi les itérations."""
        if not iterations:
            return OrchestrationResult.create_failed(
                error_message="No iterations completed",
                total_duration_ms=total_duration_ms,
            )

        best_iteration = max(iterations, key=lambda i: i.get_score())
        logger.info(
            f"Selected best draft from iteration {best_iteration.iteration_number} "
            f"(score={best_iteration.get_score()})"
        )

        return OrchestrationResult(
            final_draft=best_iteration.draft_result,
            iterations=iterations,
            total_duration_ms=total_duration_ms,
            status=OrchestrationStatus.COMPLETED,
        )

    def _create_timeout_result(
        self,
        iterations: list[IterationRecord],
        total_duration_ms: int,
    ) -> OrchestrationResult:
        """Crée un résultat pour timeout global."""
        if iterations:
            best_iteration = max(iterations, key=lambda i: i.get_score())
            return OrchestrationResult(
                final_draft=best_iteration.draft_result,
                iterations=iterations,
                total_duration_ms=total_duration_ms,
                status=OrchestrationStatus.TIMEOUT,
            )
        return OrchestrationResult.create_timeout(
            iterations=iterations,
            total_duration_ms=total_duration_ms,
        )

    def _create_failed_result(
        self,
        iterations: list[IterationRecord],
        total_duration_ms: int,
        error_message: str,
    ) -> OrchestrationResult:
        """Crée un résultat pour échec."""
        if iterations:
            best_iteration = max(iterations, key=lambda i: i.get_score())
            return OrchestrationResult(
                final_draft=best_iteration.draft_result,
                iterations=iterations,
                total_duration_ms=total_duration_ms,
                status=OrchestrationStatus.FAILED,
            )
        return OrchestrationResult.create_failed(
            error_message=error_message,
            total_duration_ms=total_duration_ms,
        )
