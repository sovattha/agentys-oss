from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from app.onboarding import manager as manager_module
from app.onboarding.manager import OnboardingManager


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _install_refresh_fakes(monkeypatch, sessions: list[_FakeSession], agent_checks: list[str]) -> None:
    class _FakeEmailRepository:
        def __init__(self, session):
            self.session = session

    class _FakeRepositoryLoader:
        def __init__(self, repo, account_id, user_email):
            self.repo = repo

        def load(self, **kwargs):
            return [object()], {"total_emails": 1}

    class _FakeEmailIndexer:
        def __init__(self, user_email, account_id):
            pass

        def index(self, emails):
            return SimpleNamespace(total_count=len(emails), by_contact={})

    class _FakeAgent:
        def __init__(self, name: str):
            self.name = name

        def analyse(self, indexed, **kwargs):
            assert sessions[0].closed is True
            agent_checks.append(self.name)
            return {}

    def _agent_module(module_name: str, class_name: str, agent_name: str) -> ModuleType:
        module = ModuleType(module_name)
        setattr(module, class_name, lambda *args, **kwargs: _FakeAgent(agent_name))
        return module

    monkeypatch.setattr(manager_module, "EmailRepository", _FakeEmailRepository)
    monkeypatch.setattr(manager_module, "RepositoryLoader", _FakeRepositoryLoader)
    monkeypatch.setattr(manager_module, "EmailIndexer", _FakeEmailIndexer)
    monkeypatch.setitem(
        sys.modules,
        "app.onboarding.agents.knowledge_agent",
        _agent_module("app.onboarding.agents.knowledge_agent", "KnowledgeAgent", "knowledge"),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.onboarding.agents.style_agent",
        _agent_module("app.onboarding.agents.style_agent", "StyleAgent", "style"),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.onboarding.agents.label_agent",
        _agent_module("app.onboarding.agents.label_agent", "LabelAgent", "label"),
    )


def test_incremental_refresh_closes_loader_session_before_agent_calls(monkeypatch):
    sessions: list[_FakeSession] = []
    agent_checks: list[str] = []

    def session_factory():
        session = _FakeSession()
        sessions.append(session)
        return session

    _install_refresh_fakes(monkeypatch, sessions, agent_checks)

    mgr = OnboardingManager(session_factory=session_factory)
    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(mgr, "_emit", lambda name, data: emitted.append((name, data)))
    monkeypatch.setattr(mgr, "_fetch_provider_folders", lambda account_id: [])
    monkeypatch.setattr(
        mgr,
        "_merge_into_knowledge_base",
        lambda *args, **kwargs: {"new_contacts": 0, "new_rules": 0},
    )
    monkeypatch.setattr(mgr, "_persist_contact_profiles", lambda *args, **kwargs: None)
    monkeypatch.setattr(mgr, "_save_category_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(mgr, "_apply_rules_from_db", lambda *args, **kwargs: 0)

    mgr._run_refresh(account_id=1, user_email="me@example.com", days=7)

    assert sessions and sessions[0].closed is True
    assert agent_checks == ["knowledge", "style", "label"]
    assert emitted[-1][0] == "onboarding:learning_completed"
    assert emitted[-1][1]["status"] == "completed"


def test_deep_refresh_closes_loader_session_before_agent_calls(monkeypatch):
    sessions: list[_FakeSession] = []
    agent_checks: list[str] = []

    def session_factory():
        session = _FakeSession()
        sessions.append(session)
        return session

    _install_refresh_fakes(monkeypatch, sessions, agent_checks)

    mgr = OnboardingManager(session_factory=session_factory)
    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(mgr, "_emit", lambda name, data: emitted.append((name, data)))
    monkeypatch.setattr(mgr, "_create_opus_llm", lambda: object())
    monkeypatch.setattr(mgr, "_fetch_provider_folders", lambda account_id: [])
    monkeypatch.setattr(
        mgr,
        "_merge_into_knowledge_base",
        lambda *args, **kwargs: {"new_contacts": 0, "new_rules": 0},
    )
    monkeypatch.setattr(mgr, "_persist_contact_profiles", lambda *args, **kwargs: None)
    monkeypatch.setattr(mgr, "_save_category_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(mgr, "_apply_rules_from_db", lambda *args, **kwargs: 0)

    mgr._run_deep_refresh(account_id=1, user_email="me@example.com")

    assert sessions and sessions[0].closed is True
    assert agent_checks == ["knowledge", "style", "label"]
    assert emitted[-1][0] == "onboarding:learning_completed"
    assert emitted[-1][1]["status"] == "completed"
    assert emitted[-1][1]["deep"] is True
