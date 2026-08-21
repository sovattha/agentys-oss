# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Régression thread-safety pour GmailAdapter._service.

Contexte: prod backend Railway s'est crashé avec `malloc(): unsorted double
linked list corrupted` le 2026-04-24. Root cause = `httplib2.Http` n'est pas
thread-safe, et `ProviderPool` partage le même GmailAdapter entre un thread
de request handler et un thread `_prefetch_bodies_bg`. Deux `.execute()`
simultanés sur le même `self._service` corrompent les BIO OpenSSL.

Fix: `_service` est maintenant un `@property` qui stocke par-thread via
`threading.local()`. Chaque thread obtient son propre `httplib2.Http`.

Ces tests verrouillent le comportement attendu pour éviter la régression.
"""

import ast
from pathlib import Path
import threading

from app.providers.gmail_adapter import GmailAdapter


def test_gmail_execute_calls_go_through_adapter_gate():
    """Every Gmail API execute must go through quota/timing helpers."""
    source_path = Path(__file__).resolve().parents[1] / "app/providers/gmail_adapter.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    allowed_methods = {"_execute_gmail_request", "_execute_gmail_batch"}
    violations = []

    class ExecuteVisitor(ast.NodeVisitor):
        def __init__(self):
            self.method_stack = []

        def visit_FunctionDef(self, node):
            self.method_stack.append(node.name)
            self.generic_visit(node)
            self.method_stack.pop()

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                method_name = self.method_stack[-1] if self.method_stack else "<module>"
                if method_name not in allowed_methods:
                    violations.append((node.lineno, method_name))
            self.generic_visit(node)

    ExecuteVisitor().visit(tree)

    assert violations == []


def test_service_storage_is_thread_local():
    """Un `_service` défini dans un thread n'est pas visible depuis un autre."""
    adapter = GmailAdapter()
    adapter._service = "main-service"

    seen = {}

    def worker():
        seen["before_set"] = adapter._service
        adapter._service = "worker-service"
        seen["after_set"] = adapter._service

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert adapter._service == "main-service", (
        "Main thread saw its _service clobbered by worker — thread-local broken"
    )
    assert seen["before_set"] is None, (
        "Worker thread inherited main's _service — thread-local broken"
    )
    assert seen["after_set"] == "worker-service"


def test_service_defaults_to_none_before_authenticate():
    """Avant authenticate(), `_service` retourne None (préserve le check
    legacy `if not self._service: authenticate()`)."""
    adapter = GmailAdapter()
    assert adapter._service is None


def test_service_setter_survives_missing_storage():
    """Le setter crée `_service_storage` à la volée si absent (cas subclass
    qui set `_service` avant super().__init__())."""
    adapter = GmailAdapter.__new__(GmailAdapter)  # skip __init__
    assert not hasattr(adapter, "_service_storage")
    # Setter should lazily create the storage without AttributeError.
    adapter._service = "injected"
    assert adapter._service == "injected"


def test_concurrent_service_reads_do_not_cross_threads():
    """Stress: 10 threads lisent/écrivent `_service` en parallèle, chacun
    doit voir uniquement sa propre valeur."""
    adapter = GmailAdapter()
    results = {}
    errors = []

    def worker(tid):
        try:
            adapter._service = f"service-{tid}"
            # Boucle pour maximiser les chances de voir un état inter-thread
            for _ in range(100):
                v = adapter._service
                if v != f"service-{tid}":
                    errors.append(
                        f"thread {tid} saw {v!r} instead of service-{tid}"
                    )
                    return
            results[tid] = v
        except Exception as e:  # pragma: no cover — signale tout crash
            errors.append(f"thread {tid}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"cross-thread leaks: {errors}"
    assert len(results) == 10
    assert set(results.values()) == {f"service-{i}" for i in range(10)}
