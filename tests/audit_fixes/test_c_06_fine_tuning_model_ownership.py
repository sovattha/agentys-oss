# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix C-6 (issue #526) — `ImprovementModel` cross-tenant takeover.

Bug : `ImprovementModel` (`app/domain/entities/fine_tuning.py:208`) n'avait
pas de champ `account_id`. Toutes les routes `app/api/fine_tuning.py`
opéraient sans aucun ownership check :

  * `POST /models/<id>/activate` — flippait le statut de N'IMPORTE quel
    `model_id` ; l'`ActivateModelUseCase` dépréciait au passage tous les
    autres modèles « actifs » globalement, donc activer son propre modèle
    dépréciait celui des autres tenants.
  * `POST /models/<id>/disable` — désactivait n'importe quel modèle (un
    user pouvait dégrader le drafting d'un voisin en disable son actif).
  * `POST /models` — créait un modèle sans owner ; visible par tous.
  * `GET /models` — énumération cross-tenant des `model_id`.
  * `GET /models/<id>` — lecture cross-tenant.
  * `POST /improve` — pouvait pointer un `model_id` étranger.
  * `POST /sessions` — créait des modèles sans owner.

Fix : `ImprovementModel.account_id: Optional[int]` stamped à la création.
Routes résolvent via `_resolve_account_id_for_user()` et passent au use
case ; les use cases (`ActivateModelUseCase`, `DisableModelUseCase`,
`ApplyImprovementsUseCase`, `GetPromptEnhancementsUseCase`,
`ListModelsUseCase`, `RunFineTuningSessionUseCase`,
`CreateImprovementModelUseCase`) acceptent `account_id` et filtrent les
lookups. Les modèles legacy (`account_id=None`) sont invisibles aux
lookups scopées — pas de takeover possible.

Run: `pytest tests/audit_fixes/test_c_06_fine_tuning_model_ownership.py -v`
"""

from __future__ import annotations

import pytest

pytest.importorskip("flask_cors")

from app.application.fine_tuning import (
    ActivateModelUseCase,
    DisableModelUseCase,
    ListModelsUseCase,
    ApplyImprovementsUseCase,
    GetPromptEnhancementsUseCase,
    CreateImprovementModelUseCase,
)
from app.domain.entities.fine_tuning import (
    ImprovementModel,
    ImprovementStatus,
)


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #

class _InMemoryModelStore:
    """Minimal `ImprovementModelPort` impl for unit tests."""

    def __init__(self):
        self._by_id: dict[str, ImprovementModel] = {}

    # `save` returns the assigned id and adds to the dict.
    def save(self, model: ImprovementModel) -> str:
        self._by_id[model.id] = model
        return model.id

    def update(self, model: ImprovementModel) -> bool:
        if model.id in self._by_id:
            self._by_id[model.id] = model
            return True
        return False

    def get_by_id(self, model_id: str):
        return self._by_id.get(model_id)

    def get_active_models(self):
        return [m for m in self._by_id.values()
                if m.status == ImprovementStatus.ACTIVE]

    def get_by_status(self, status, limit: int = 100):
        return [m for m in self._by_id.values() if m.status == status][:limit]

    def get_latest(self):
        if not self._by_id:
            return None
        return max(self._by_id.values(), key=lambda m: m.created_at)

    def count(self) -> int:
        return len(self._by_id)

    def delete(self, model_id: str) -> bool:
        return self._by_id.pop(model_id, None) is not None


class _StubPatternStore:
    def get_reliable_patterns(self, min_confidence=0.6):
        return []

    def get_by_id(self, _):
        return None


class _StubAnalyzer:
    def generate_prompt_adjustments(self, _patterns):
        return []

    def apply_improvements(self, text, _model, _patterns):
        return text


# --------------------------------------------------------------------------- #
# Entity-level: account_id round-trips through JSON store.
# --------------------------------------------------------------------------- #


def test_improvement_model_default_account_id_is_none():
    """Backward compat: an ImprovementModel built without account_id is
    `None`, which is invisible to scoped lookups (legacy data)."""
    m = ImprovementModel.create(name="x", description="y")
    assert m.account_id is None


def test_improvement_model_create_stamps_account_id():
    m = ImprovementModel.create(name="x", description="y", account_id=42)
    assert m.account_id == 42


def test_json_store_roundtrips_account_id(tmp_path):
    """Save → load preserves `account_id`. A regression here means new
    models lose tenant ownership at the next process boot."""
    from app.infrastructure.fine_tuning_store import JsonImprovementModelStore

    store = JsonImprovementModelStore(file_path=tmp_path / "models.json")
    m = ImprovementModel.create(name="m1", description="d", account_id=42)
    store.save(m)

    fresh_store = JsonImprovementModelStore(file_path=tmp_path / "models.json")
    loaded = fresh_store.get_by_id(m.id)
    assert loaded is not None
    assert loaded.account_id == 42


def test_json_store_legacy_model_without_account_id_loads_as_none():
    """Models written before the C-6 fix have no `account_id` key. They
    must round-trip as `None` (invisible to scoped lookups)."""
    from app.infrastructure.fine_tuning_store import JsonImprovementModelStore

    store = JsonImprovementModelStore.__new__(JsonImprovementModelStore)
    legacy_dict = {
        "id": "legacy-1",
        "version": "1.0.0",
        "name": "legacy",
        "description": "no account_id key on disk",
        "patterns": [],
        "prompt_adjustments": [],
        "status": "active",
        "impact_score": 0.0,
        "drafts_improved": 0,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    loaded = store._from_dict(legacy_dict)
    assert loaded.account_id is None


# --------------------------------------------------------------------------- #
# ActivateModelUseCase: cross-tenant takeover MUST be blocked.
# --------------------------------------------------------------------------- #


def test_activate_rejects_foreign_model():
    """User 42 cannot activate a model owned by user 99."""
    store = _InMemoryModelStore()
    foreign = ImprovementModel.create(name="foreign", description="d", account_id=99)
    store.save(foreign)

    use_case = ActivateModelUseCase(model_store=store)
    with pytest.raises(ValueError):
        use_case.execute(foreign.id, account_id=42)
    # The foreign model must NOT have flipped to ACTIVE.
    assert store.get_by_id(foreign.id).status == ImprovementStatus.PENDING


def test_activate_does_not_deprecate_other_tenants_active_models():
    """When user 42 activates their own model, user 99's active model must
    NOT be deprecated. This was the headline takeover vector."""
    store = _InMemoryModelStore()
    own_pending = ImprovementModel.create(name="own", description="d", account_id=42)
    other_active = ImprovementModel.create(name="other", description="d", account_id=99)
    other_active.activate()
    store.save(own_pending)
    store.save(other_active)

    use_case = ActivateModelUseCase(model_store=store)
    use_case.execute(own_pending.id, account_id=42)

    # User 42's model is now active.
    assert store.get_by_id(own_pending.id).status == ImprovementStatus.ACTIVE
    # User 99's model MUST remain active (not deprecated).
    assert store.get_by_id(other_active.id).status == ImprovementStatus.ACTIVE


def test_activate_legacy_account_none_model_is_blocked():
    """A legacy model (`account_id=None`) cannot be activated by any
    scoped caller — only admin/script paths with `account_id=None`."""
    store = _InMemoryModelStore()
    legacy = ImprovementModel.create(name="legacy", description="d")  # account_id=None
    store.save(legacy)

    use_case = ActivateModelUseCase(model_store=store)
    with pytest.raises(ValueError):
        use_case.execute(legacy.id, account_id=42)


# --------------------------------------------------------------------------- #
# DisableModelUseCase: same ownership check.
# --------------------------------------------------------------------------- #


def test_disable_rejects_foreign_model():
    """Tenant A cannot disable tenant B's active model (drafting
    degradation attack)."""
    store = _InMemoryModelStore()
    other_active = ImprovementModel.create(name="other", description="d", account_id=99)
    other_active.activate()
    store.save(other_active)

    use_case = DisableModelUseCase(model_store=store)
    with pytest.raises(ValueError):
        use_case.execute(other_active.id, account_id=42)
    assert store.get_by_id(other_active.id).status == ImprovementStatus.ACTIVE


# --------------------------------------------------------------------------- #
# ApplyImprovementsUseCase / GetPromptEnhancementsUseCase: scoped reads.
# --------------------------------------------------------------------------- #


def test_apply_improvements_scopes_active_models_by_account():
    """User 42's `/improve` (no model_id) must NOT consume user 99's
    active model — that would let user 99 shape user 42's drafts."""
    store = _InMemoryModelStore()
    foreign_active = ImprovementModel.create(
        name="foreign-active", description="d", account_id=99
    )
    foreign_active.activate()
    store.save(foreign_active)

    use_case = ApplyImprovementsUseCase(
        model_store=store, pattern_store=_StubPatternStore(),
        analyzer=_StubAnalyzer(),
    )
    result = use_case.execute(text="hello", account_id=42)
    # No model owned by 42 → no improvement applied. Critically, the
    # foreign model is NOT consumed.
    assert result.improvements_applied == 0
    assert result.patterns_used == []


def test_apply_improvements_with_foreign_model_id_is_silent_noop():
    """Explicit `model_id` pointing at a foreign model must be treated as
    introuvable — same shape as no model. No oracle of existence."""
    store = _InMemoryModelStore()
    foreign = ImprovementModel.create(name="foreign", description="d", account_id=99)
    foreign.activate()
    store.save(foreign)

    use_case = ApplyImprovementsUseCase(
        model_store=store, pattern_store=_StubPatternStore(),
        analyzer=_StubAnalyzer(),
    )
    result = use_case.execute(text="hello", model_id=foreign.id, account_id=42)
    assert result.improvements_applied == 0


def test_get_prompt_enhancements_scopes_to_account():
    """Prompt adjustments aggregated from active models must be filtered
    to the caller — sinon un user produit des prompts pour un autre."""
    store = _InMemoryModelStore()
    foreign = ImprovementModel.create(
        name="foreign", description="d", account_id=99
    )
    foreign.activate()
    foreign.prompt_adjustments.append("foreign-instruction-leak")
    store.save(foreign)

    use_case = GetPromptEnhancementsUseCase(
        model_store=store, pattern_store=_StubPatternStore(),
    )
    adjustments = use_case.execute(account_id=42)
    assert "foreign-instruction-leak" not in adjustments
    assert adjustments == []


# --------------------------------------------------------------------------- #
# ListModelsUseCase: cross-tenant enumeration is filtered out.
# --------------------------------------------------------------------------- #


def test_list_models_filters_by_account():
    store = _InMemoryModelStore()
    own = ImprovementModel.create(name="own", description="d", account_id=42)
    foreign = ImprovementModel.create(name="foreign", description="d", account_id=99)
    legacy = ImprovementModel.create(name="legacy", description="d")
    store.save(own)
    store.save(foreign)
    store.save(legacy)

    use_case = ListModelsUseCase(model_store=store)
    visible = use_case.execute(account_id=42)
    visible_ids = {m.id for m in visible}
    assert own.id in visible_ids
    assert foreign.id not in visible_ids
    assert legacy.id not in visible_ids


# --------------------------------------------------------------------------- #
# CreateImprovementModelUseCase: stamps the account_id at creation.
# --------------------------------------------------------------------------- #


def test_create_stamps_account_id():
    store = _InMemoryModelStore()
    use_case = CreateImprovementModelUseCase(
        model_store=store, pattern_store=_StubPatternStore(),
        analyzer=_StubAnalyzer(),
    )
    result = use_case.execute(name="m", description="d", account_id=42)
    saved = store.get_by_id(result.model_id)
    assert saved is not None
    assert saved.account_id == 42


# --------------------------------------------------------------------------- #
# Route-level: 401 when account cannot be resolved.
# --------------------------------------------------------------------------- #


@pytest.fixture
def app_client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield app, client


def test_create_route_rejects_caller_without_account(app_client):
    """If `_resolve_account_id_for_user` returns the -1 sentinel, the
    route must 401 — never silently create an unowned model."""
    from unittest.mock import patch
    _, client = app_client

    with patch(
        "app.api.fine_tuning._resolve_account_id_for_user", return_value=-1
    ):
        resp = client.post(
            "/api/fine-tuning/models",
            json={"name": "n", "description": "d"},
            content_type="application/json",
        )
    assert resp.status_code == 401


def test_list_route_rejects_caller_without_account(app_client):
    """List must also reject — leaking the global model dump was the
    enumeration vector that fed the takeover."""
    from unittest.mock import patch
    _, client = app_client

    with patch(
        "app.api.fine_tuning._resolve_account_id_for_user", return_value=-1
    ):
        resp = client.get("/api/fine-tuning/models")
    assert resp.status_code == 401
