#!/usr/bin/env python3
"""Linter AST — détecte les queries sur tables account-scoped sans filter account_id.

Fait échouer la CI si un appel `session.query(X).filter(...)` ou
`Repository.get_*()` sur une table account-scoped (Email, Draft, Contact,
Label, KnowledgeEntry, …) n'a pas de clause `account_id` visible dans
les arguments.

C'est une heuristique statique : des faux positifs existeront. Dans ce
cas, annoter la ligne avec `# noqa: account-scoping` avec justification.

Usage:
    python scripts/lint_account_scoping.py                     # scan défaut
    python scripts/lint_account_scoping.py app/api/ app/db/    # chemins ciblés

Exit 0 si OK, 1 si violations trouvées.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable

# Ressources account-scoped — toute query sans filter account_id est suspecte.
SCOPED_TABLES = {
    "Email",
    "Draft",
    "DraftHistory",
    "Contact",
    "Label",
    "EmailLabel",
    "EmailLabelRecord",
    "KnowledgeEntry",
    "RelationshipOverride",
    "PendingDraft",
}

# Repository méthodes de lecture qui DOIVENT recevoir un account_id.
SCOPED_REPO_METHODS = {
    # DraftHistoryPort legacy names — si trouvé en prod, lever.
    "get_all",
    "get_by_id",
    "get_recent",
    "update_feedback",
}

# Tokens qui exonèrent une ligne (présents dans le fichier, pas juste la ligne).
FILE_EXONERATIONS = {
    "noqa: account-scoping",
    "# legacy-unscoped-ok",
}

# Fichiers complètement ignorés (tests + adapters legacy + migrations).
IGNORED_PATHS = (
    "/tests/",
    "/migrations/",
    "/infrastructure/adapters/draft_history_adapter.py",
    "/infrastructure/adapters/sqlite_learning_store.py",
    "/scripts/",
    "/dashboard.py",   # dashboard legacy Tauri mono-compte
)


def _iter_python_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            yield root
        elif root.is_dir():
            for p in root.rglob("*.py"):
                yield p


def _has_account_id_filter(call_node: ast.Call) -> bool:
    """True si la Call node a un argument mentionnant account_id."""
    for kw in call_node.keywords:
        if kw.arg and "account_id" in kw.arg:
            return True
    # Scan .filter(Email.account_id == ...) patterns
    for arg in call_node.args:
        src = ast.unparse(arg) if hasattr(ast, "unparse") else ""
        if "account_id" in src:
            return True
    return False


def _is_ignored(path: Path) -> bool:
    s = str(path.as_posix())
    return any(frag in s for frag in IGNORED_PATHS)


def _file_exonerates(source: str) -> bool:
    return any(tok in source for tok in FILE_EXONERATIONS)


def _chain_has_account_id(root_expr: ast.AST) -> bool:
    """Scan toutes les sous-nodes Call pour trouver un filter/where
    qui contient `account_id`. Gère les chaînes .query().filter().filter()."""
    src = ast.unparse(root_expr) if hasattr(ast, "unparse") else ""
    return "account_id" in src


class _Visitor(ast.NodeVisitor):
    def __init__(self, source: str, tree: ast.AST) -> None:
        self.violations: list[tuple[int, str]] = []
        self.source_lines = source.splitlines()
        self.tree = tree
        # Pré-indexe : pour chaque Call, son parent "statement" (Expr, Assign)
        self._expr_parents: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Return)):
                for child in ast.walk(node):
                    self._expr_parents[id(child)] = node

    def _line_exonerated(self, lineno: int) -> bool:
        if lineno - 1 < 0 or lineno - 1 >= len(self.source_lines):
            return False
        return any(tok in self.source_lines[lineno - 1] for tok in FILE_EXONERATIONS)

    def _enclosing_expr_has_account_id(self, node: ast.Call) -> bool:
        parent = self._expr_parents.get(id(node))
        if parent is None:
            return False
        return _chain_has_account_id(parent)

    def visit_Call(self, node: ast.Call) -> None:
        # Pattern 1 : session.query(Email).filter(...).first() sans account_id.
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {
            "query", "filter", "filter_by", "where",
        }:
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in SCOPED_TABLES:
                    if (
                        not _has_account_id_filter(node)
                        and not self._enclosing_expr_has_account_id(node)
                        and not self._line_exonerated(node.lineno)
                    ):
                        self.violations.append((
                            node.lineno,
                            f"query sur {arg.id} sans filter account_id",
                        ))

        # Pattern 2 : appel direct à method legacy (get_all, get_by_id, …)
        # sur un objet dont le nom suggère un repo/port draft_history.
        if (
            isinstance(func, ast.Attribute)
            and func.attr in SCOPED_REPO_METHODS
            and not self._line_exonerated(node.lineno)
        ):
            # Heuristique : l'objet appelé contient "draft_history" ou "repo"
            owner_src = ast.unparse(func.value) if hasattr(ast, "unparse") else ""
            if "draft_history" in owner_src.lower():
                self.violations.append((
                    node.lineno,
                    f"appel {func.attr}() sur draft_history sans scoped variante _for_account",
                ))

        self.generic_visit(node)


def scan(paths: list[Path]) -> int:
    total_violations = 0
    for f in _iter_python_files(paths):
        if _is_ignored(f):
            continue
        try:
            src = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if _file_exonerates(src):
            continue
        try:
            tree = ast.parse(src, filename=str(f))
        except SyntaxError:
            continue
        v = _Visitor(src, tree)
        v.visit(tree)
        for lineno, msg in v.violations:
            print(f"{f}:{lineno}: {msg}")
            total_violations += 1

    if total_violations:
        print(f"\n{total_violations} violation(s) d'isolation multi-compte détectée(s).")
        print("Corrigez ou annotez la ligne avec `# noqa: account-scoping` + justification.")
        return 1
    print("OK : aucune violation d'isolation multi-compte détectée.")
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        roots = [Path(p) for p in sys.argv[1:]]
    else:
        roots = [Path("app")]
    return scan(roots)


if __name__ == "__main__":
    raise SystemExit(main())
