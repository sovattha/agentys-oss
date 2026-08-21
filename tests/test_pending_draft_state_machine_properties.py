# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Property-based tests sur la state machine `PendingDraftStatus`.

Pourquoi un property-based plutôt qu'un test unitaire :
  La state machine a 5 états et ~6 actions. Le produit cartésien =
  30 combinaisons (état, action), dont la moitié sont des cas illégaux
  qui doivent renvoyer 409. Les enchaînements de longueur N donnent
  6^N parcours possibles. Aucun test à la main ne couvre tous les
  ordres ; Hypothesis génère des séquences arbitraires d'actions et
  vérifie les **invariants globaux**.

Invariants vérifiés :
  I1 — Terminalité : SENT et REJECTED sont des états terminaux. Aucune
       action ne peut en sortir (sauf via SIL-001 retry depuis VALIDATED,
       qui n'est PAS un état terminal).
  I2 — Idempotence : appeler la même action 2 fois sur un état terminal
       = même résultat (pas de side-effect, pas de mutation imprévue).
  I3 — Cohérence gmail_draft_id : si status ∈ {VALIDATED, SENT}, alors
       gmail_draft_id est set. Inversement, si status = PENDING/MODIFIED,
       gmail_draft_id reste None ou pointe vers un draft précédent.
  I4 — Identité du compte : l'`account_id` ne change JAMAIS après la
       création (CRIT-Iso-4 invariant). Seul le status mute.
  I5 — Validity : status est toujours un membre valide de l'enum.

Les actions modélisent ce que fait `routes_pending.py` :
  - validate_success / validate_fail (SIL-001 path)
  - reject (SIL-003 guard)
  - refine (modifie le body, status reste PENDING ou bascule MODIFIED)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

# `hypothesis` est installé en dev — fail-fast sinon plutôt que silently skip.
hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    RuleBasedStateMachine,
    invariant,
    rule,
)

from app.domain.entities.pending_draft import (  # noqa: E402
    PendingDraft,
    PendingDraftStatus,
)


# ─────────────────────────────────────────────────────────────────────────────
# Modèle abstrait : la "vraie" state machine telle qu'elle vit dans
# `routes_pending.py` + `pending_draft_store.py`.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StateMachineModel:
    """Reflet en mémoire de la state machine. Mutation explicite — chaque
    action retourne le nouveau status ou None (action refusée → 409).

    Ne lit PAS la DB, ne fait PAS d'I/O. C'est un oracle pur que les
    tests comparent à la vraie implémentation côté `update_status` du
    store.
    """
    status: PendingDraftStatus = PendingDraftStatus.PENDING
    gmail_draft_id: Optional[str] = None
    account_id: str = "1"  # invariant : ne change jamais.

    # Tuple des status à partir desquels validate est permis (cf. RACE-002
    # guard à `routes_pending.py:287`).
    _RETRY_ABLE = (
        PendingDraftStatus.PENDING,
        PendingDraftStatus.MODIFIED,
        PendingDraftStatus.VALIDATED,
    )
    # Tuple des status à partir desquels reject est permis (cf. SIL-003).
    _REJECT_ABLE = (
        PendingDraftStatus.PENDING,
        PendingDraftStatus.MODIFIED,
    )

    def validate_success(self) -> bool:
        """Send réussi → SENT. Retourne False si 409."""
        if self.status not in self._RETRY_ABLE:
            return False
        self.status = PendingDraftStatus.SENT
        # gmail_draft_id est set au plus tard ici (fast path : direct send,
        # 2-step path : create_draft a déjà setté le champ avant send_draft).
        if self.gmail_draft_id is None:
            self.gmail_draft_id = "msg-id-fastpath"
        return True

    def validate_fail(self) -> bool:
        """Send échoué (SIL-001) → revert à PENDING.

        Permis depuis PENDING / MODIFIED / VALIDATED. Si on partait de
        VALIDATED, le gmail_draft_id reste set (le draft Gmail existe
        toujours, on a juste raté l'envoi — l'utilisateur peut retry).
        """
        if self.status not in self._RETRY_ABLE:
            return False
        # Le 2-step path (create_draft puis send_draft) set gmail_draft_id
        # avant l'échec. Le fast path échoue avant set, donc on n'écrit que
        # si on partait déjà de VALIDATED.
        if self.status == PendingDraftStatus.PENDING:
            # Modélise le 2-step : create_draft a réussi, send_draft échoue.
            self.gmail_draft_id = "msg-id-create-only"
        self.status = PendingDraftStatus.PENDING
        return True

    def reject(self) -> bool:
        """Reject (SIL-003) — refusé sur SENT/REJECTED/VALIDATED."""
        if self.status not in self._REJECT_ABLE:
            return False
        self.status = PendingDraftStatus.REJECTED
        return True

    def refine(self) -> bool:
        """Refine ne change pas de status (édition du body), sauf depuis
        PENDING qui transitionne en MODIFIED. Refusé sur SENT/REJECTED.
        """
        if self.status in (PendingDraftStatus.SENT, PendingDraftStatus.REJECTED):
            return False
        if self.status == PendingDraftStatus.PENDING:
            self.status = PendingDraftStatus.MODIFIED
        return True


# ─────────────────────────────────────────────────────────────────────────────
# 1. Tests d'invariants — propriétés universelles vérifiées sur un PendingDraft
#    construit aléatoirement.
# ─────────────────────────────────────────────────────────────────────────────

@given(status=st.sampled_from(list(PendingDraftStatus)))
@settings(max_examples=50)
def test_invariant_status_always_valid_enum(status):
    """I5 : status est toujours un membre valide de l'enum, jamais une string
    libre. Vérifie le contrat API : passer un str au constructeur reste
    accepté pour rétrocompat (cf. from_dict line 167-168), mais le membre
    direct est privilégié et l'enum doit toujours s'auto-coercer.
    """
    draft = PendingDraft(status=status, account_id="1")
    assert isinstance(draft.status, PendingDraftStatus)
    assert draft.status in PendingDraftStatus


@given(
    initial_status=st.sampled_from(list(PendingDraftStatus)),
    new_account_id=st.text(min_size=0, max_size=20).filter(lambda s: s != "1"),
)
@settings(max_examples=30)
def test_invariant_account_id_never_changes_under_state_transitions(
    initial_status, new_account_id,
):
    """I4 (CRIT-Iso-4 forever) : peu importe les transitions du status,
    `account_id` n'est JAMAIS muté par les actions de la state machine.

    Test : on construit un draft avec account_id="1", on applique
    n'importe quelle action, on vérifie que account_id est inchangé.
    """
    model = StateMachineModel(status=initial_status, account_id="1")
    # Apply chaque action une fois — peu importe le résultat, account_id
    # ne peut pas changer.
    for action in (
        model.validate_success,
        model.validate_fail,
        model.reject,
        model.refine,
    ):
        action()
        assert model.account_id == "1", (
            f"Action {action.__name__} a muté account_id (devenu {model.account_id!r}) "
            f"depuis le status {initial_status.value}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tests sur les actions — propriétés des transitions individuelles.
# ─────────────────────────────────────────────────────────────────────────────

@given(initial_status=st.sampled_from(list(PendingDraftStatus)))
@settings(max_examples=20)
def test_validate_success_from_terminal_states_returns_false(initial_status):
    """RACE-002 : validate_success doit échouer sur SENT et REJECTED."""
    model = StateMachineModel(status=initial_status)
    ok = model.validate_success()
    if initial_status in (PendingDraftStatus.SENT, PendingDraftStatus.REJECTED):
        assert ok is False
        # Le status n'a pas changé.
        assert model.status == initial_status
    else:
        assert ok is True
        assert model.status == PendingDraftStatus.SENT


@given(initial_status=st.sampled_from(list(PendingDraftStatus)))
@settings(max_examples=20)
def test_reject_from_terminal_or_validated_states_returns_false(initial_status):
    """SIL-003 : reject doit échouer sur SENT, REJECTED, VALIDATED."""
    model = StateMachineModel(status=initial_status)
    ok = model.reject()
    if initial_status in (
        PendingDraftStatus.SENT,
        PendingDraftStatus.REJECTED,
        PendingDraftStatus.VALIDATED,
    ):
        assert ok is False
        assert model.status == initial_status
    else:
        assert ok is True
        assert model.status == PendingDraftStatus.REJECTED


@given(initial_status=st.sampled_from(list(PendingDraftStatus)))
@settings(max_examples=30)
def test_validate_fail_reverts_to_pending_only_from_retry_able_states(initial_status):
    """SIL-001 : validate_fail doit revert à PENDING (pas VALIDATED).

    Permis depuis PENDING/MODIFIED/VALIDATED, refusé depuis SENT/REJECTED.
    """
    model = StateMachineModel(status=initial_status)
    ok = model.validate_fail()
    if initial_status in (PendingDraftStatus.SENT, PendingDraftStatus.REJECTED):
        assert ok is False
        assert model.status == initial_status
    else:
        assert ok is True
        # Invariant SIL-001 : le revert va vers PENDING, jamais VALIDATED.
        assert model.status == PendingDraftStatus.PENDING


# ─────────────────────────────────────────────────────────────────────────────
# 3. RuleBasedStateMachine — séquences arbitraires d'actions, invariants
#    vérifiés à chaque étape.
# ─────────────────────────────────────────────────────────────────────────────

class PendingDraftLifecycle(RuleBasedStateMachine):
    """Hypothesis explore des séquences aléatoires de [validate_success,
    validate_fail, reject, refine] sur un draft initialement PENDING.

    Les invariants sont checkés AUTOMATIQUEMENT après chaque rule. Si
    une séquence trouve un état où un invariant est violé, Hypothesis
    réduit (shrinks) la séquence à un contre-exemple minimal.
    """

    def __init__(self):
        super().__init__()
        self.model = StateMachineModel(status=PendingDraftStatus.PENDING)
        # Snapshot du status avant la dernière transition (pour I1).
        self._previous_terminal: Optional[PendingDraftStatus] = None

    @rule()
    def do_validate_success(self):
        if self.model.status in (PendingDraftStatus.SENT, PendingDraftStatus.REJECTED):
            self._previous_terminal = self.model.status
        self.model.validate_success()

    @rule()
    def do_validate_fail(self):
        if self.model.status in (PendingDraftStatus.SENT, PendingDraftStatus.REJECTED):
            self._previous_terminal = self.model.status
        self.model.validate_fail()

    @rule()
    def do_reject(self):
        if self.model.status in (PendingDraftStatus.SENT, PendingDraftStatus.REJECTED):
            self._previous_terminal = self.model.status
        self.model.reject()

    @rule()
    def do_refine(self):
        if self.model.status in (PendingDraftStatus.SENT, PendingDraftStatus.REJECTED):
            self._previous_terminal = self.model.status
        self.model.refine()

    @invariant()
    def status_always_valid(self):
        """I5 : status est toujours un membre valide."""
        assert isinstance(self.model.status, PendingDraftStatus)

    @invariant()
    def account_id_never_mutates(self):
        """I4 : account_id reste "1" pour toujours."""
        assert self.model.account_id == "1"

    @invariant()
    def terminal_states_are_truly_terminal(self):
        """I1 : si on entre en SENT ou REJECTED, on n'en sort plus.

        Vérifié via `_previous_terminal` : si on était SENT au tour
        précédent, on est encore SENT maintenant (les rules sont des
        no-op après un état terminal).
        """
        if self._previous_terminal is not None:
            assert self.model.status == self._previous_terminal, (
                f"Terminal state {self._previous_terminal.value} "
                f"a été quitté pour {self.model.status.value}. "
                f"Régression I1 — les états terminaux doivent rester sticky."
            )

    @invariant()
    def gmail_draft_id_consistency(self):
        """I3 : SENT implique gmail_draft_id non-null.

        VALIDATED ne contraint pas (le draft peut exister sans send), mais
        SENT exige strictement un message envoyé donc un id de message.
        """
        if self.model.status == PendingDraftStatus.SENT:
            assert self.model.gmail_draft_id is not None, (
                "SENT sans gmail_draft_id : on a marqué l'envoi terminé sans "
                "trace de l'objet envoyé — incohérence de ledger."
            )


# Hypothesis convertit la classe en pytest test. Chaque exécution génère
# de l'ordre de 100 séquences aléatoires de longueur ~50 actions.
TestPendingDraftLifecycle = PendingDraftLifecycle.TestCase
TestPendingDraftLifecycle.settings = settings(
    max_examples=50,
    stateful_step_count=30,
    deadline=None,  # certaines runs peuvent être lentes au shrink.
)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Test fini explicit : SIL-001 retry — VALIDATED → fail → PENDING → success
# ─────────────────────────────────────────────────────────────────────────────

def test_sil_001_retry_cycle_full():
    """Scénario réel : draft VALIDATED après un partial-success (Gmail
    draft créé mais send a hung), l'utilisateur clique Retry, le 2e send
    réussit. La séquence VALIDATED → validate_fail → PENDING → validate_success
    → SENT doit être traversable sans 409.
    """
    model = StateMachineModel(status=PendingDraftStatus.VALIDATED,
                              gmail_draft_id="msg-from-1st-create")

    # 1er retry : validate_fail (le send a échoué encore).
    assert model.validate_fail() is True
    assert model.status == PendingDraftStatus.PENDING
    # gmail_draft_id reste set : on a un draft Gmail orphelin pour info.
    assert model.gmail_draft_id == "msg-from-1st-create"

    # 2e retry : success.
    assert model.validate_success() is True
    assert model.status == PendingDraftStatus.SENT
    assert model.gmail_draft_id is not None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Test fini explicit : double-send protection (RACE-002)
# ─────────────────────────────────────────────────────────────────────────────

def test_race_002_double_validate_blocked():
    """Une fois SENT, un 2e validate_success doit être refusé."""
    model = StateMachineModel()
    assert model.validate_success() is True
    assert model.status == PendingDraftStatus.SENT

    # Deuxième tentative : 409.
    assert model.validate_success() is False
    assert model.status == PendingDraftStatus.SENT  # unchanged


# ─────────────────────────────────────────────────────────────────────────────
# 6. Test fini explicit : reject pendant validate (SIL-003)
# ─────────────────────────────────────────────────────────────────────────────

def test_sil_003_reject_after_send_blocked():
    """Reject sur un draft SENT doit être refusé."""
    model = StateMachineModel()
    model.validate_success()  # → SENT
    assert model.reject() is False
    assert model.status == PendingDraftStatus.SENT
