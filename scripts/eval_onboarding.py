#!/usr/bin/env python3
"""
Onboarding evaluation runner — iterative prompt testing.

Runs the full onboarding pipeline (loader → indexer → agents) with real LLM
calls against test fixtures, then evaluates the output against ground truth.

Usage:
    python scripts/eval_onboarding.py                     # Full pipeline via claude -p (default)
    python scripts/eval_onboarding.py --agent profile     # Single agent
    python scripts/eval_onboarding.py --no-llm-judge      # Heuristic eval only
    python scripts/eval_onboarding.py --save               # Save results to file
    python scripts/eval_onboarding.py --compare RUN_FILE   # Compare with previous run
    python scripts/eval_onboarding.py --api                # Use API directly (instead of claude -p)
    python scripts/eval_onboarding.py --persona startup_ceo       # Specific persona
    python scripts/eval_onboarding.py --all-personas              # All personas comparison
    python scripts/eval_onboarding.py --fixture path/to/emails.json --ground-truth path/to/gt.json
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Project root setup
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.onboarding.loader import FixtureLoader
from app.onboarding.indexer import EmailIndexer
from app.onboarding.agents.profile_agent import ProfileAgent
from app.onboarding.agents.knowledge_agent import KnowledgeAgent
from app.onboarding.agents.style_agent import StyleAgent
from app.onboarding.agents.evaluation_agent import EvaluationAgent, EvaluationResult

FIXTURES_DIR = ROOT / "tests" / "fixtures"
DEFAULT_FIXTURES_PATH = FIXTURES_DIR / "test_emails.json"
DEFAULT_GROUND_TRUTH_PATH = FIXTURES_DIR / "ground_truth.json"
RESULTS_DIR = FIXTURES_DIR / "eval_runs"

# Available personas (id → description)
PERSONAS = {
    "default": "Sophie Martin — PM tech bilingue FR/EN",
    "lawyer_paris": "Marc-Antoine Barreau — Avocat d'affaires Paris",
    "sales_director": "Karim Mandat — Directeur commercial immobilier Lyon",
    "startup_ceo": "Priya Pivot — CEO startup SaaS bilingue",
    "hr_director": "Catherine Carrière — DRH banque",
    "consultant_intl": "James Conseil — Consultant stratégie international",
}


def resolve_persona_paths(persona_id: str) -> tuple[Path, Path]:
    """Resolve a persona ID to (fixtures_path, ground_truth_path)."""
    if persona_id == "default":
        return DEFAULT_FIXTURES_PATH, DEFAULT_GROUND_TRUTH_PATH
    fixtures = FIXTURES_DIR / f"test_emails_{persona_id}.json"
    gt = FIXTURES_DIR / f"ground_truth_{persona_id}.json"
    if not fixtures.exists():
        raise FileNotFoundError(f"Fixture non trouvée: {fixtures}")
    if not gt.exists():
        raise FileNotFoundError(f"Ground truth non trouvé: {gt}")
    return fixtures, gt

# ── Formatting ──────────────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"


def score_color(score: int) -> str:
    if score >= 80:
        return GREEN
    if score >= 50:
        return YELLOW
    return RED


def print_header(title: str):
    print(f"\n{BOLD}{CYAN}{'═' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 60}{RESET}")


def print_section(title: str):
    print(f"\n{BOLD}── {title} {'─' * (55 - len(title))}{RESET}")


def print_score_line(label: str, score: int, max_width: int = 30):
    bar_len = score // 5  # 0-20 chars
    bar = "█" * bar_len + "░" * (20 - bar_len)
    color = score_color(score)
    print(f"  {label:<{max_width}} {color}{bar} {score:>3}/100{RESET}")


def print_list(title: str, items: list, color: str = DIM):
    if not items:
        return
    print(f"  {title}:")
    for item in items[:10]:
        print(f"    {color}• {item}{RESET}")
    if len(items) > 10:
        print(f"    {DIM}  ... et {len(items) - 10} de plus{RESET}")


# ── Claude CLI adapter ─────────────────────────────────────────────────────

class ClaudeCLIAdapter:
    """
    LLM adapter that shells out to `claude -p` (Claude Code pipe mode).

    Uses the user's Claude Code subscription instead of an API key.
    Implements the same complete() interface as LLMPort.
    """

    def __init__(self, model: str = "sonnet"):
        self._model = model
        self._name = "claude-cli"

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ):
        """Call claude -p via le helper canonique `safe_claude_invoke`.

        Audit L-3 (#546, 2026-05-05) : avant la migration, ce path
        appelait `subprocess.run` direct avec `--setting-sources ""` +
        `--disable-slash-commands` mais SANS `--strict-mcp-config`,
        SANS `--tools ""`, et SANS `cwd=/tmp`. Maintenant on délègue à
        `safe_claude_invoke` qui force le pattern hardening complet,
        et on passe en `extra_args` les flags spécifiques à l'eval
        (clean session, no slash commands).
        """
        from ai_team.lib.claude_spawn import safe_claude_invoke
        from app.domain.ports.llm_port import LLMResponse

        result = safe_claude_invoke(
            prompt=user,
            model=self._model,
            system=system,
            timeout_s=300,
            extra_args=[
                # Clean session: no hooks, no plugins, no user config —
                # propre à l'eval (pas dans le helper par défaut car la
                # plupart des callers prod tolèrent les settings).
                "--setting-sources", "",
                "--disable-slash-commands",
            ],
        )

        if result.status != "success":
            err = result.error or "(no error)"
            text_preview = (result.text or "")[:500] or "(empty stdout)"
            print(f"  \033[31mclaude -p failed (status={result.status}):\033[0m")
            print(f"  \033[31m  error : {err}\033[0m")
            print(f"  \033[31m  stdout: {text_preview}\033[0m")
            raise RuntimeError(f"claude -p failed: {err} | stdout={text_preview}")

        return LLMResponse(
            content=result.text,
            input_tokens=result.tokens_in,
            output_tokens=result.tokens_out,
            model=f"claude-cli:{self._model}",
        )

    def is_available(self) -> bool:
        """Check if claude CLI is installed."""
        try:
            subprocess.run(["claude", "--version"], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


def activate_claude_cli(model: str = "sonnet", judge_model: str | None = None):
    """Monkey-patch the container to use claude -p for all LLM calls.

    If judge_model is provided and differs from model, the LLM-as-judge
    (EvaluationAgent) uses judge_model while the writer agents use model.
    This decouples writer and judge to get a fair cross-model comparison.
    """
    from app.infrastructure.container import get_container

    adapter = ClaudeCLIAdapter(model=model)

    if not adapter.is_available():
        print(f"  {RED}Erreur: 'claude' CLI non trouvé dans le PATH{RESET}")
        sys.exit(1)

    container = get_container()
    # Set the private fields so the lazy-loading properties return our adapter
    container._llm_sonnet = adapter
    container._llm_label = adapter
    container._llm = adapter

    print(f"  {CYAN}Mode claude-cli activé (modèle: {model}){RESET}")
    print(f"  {DIM}Utilise 'claude -p' au lieu de l'API directe{RESET}")

    if judge_model and judge_model != model:
        judge_adapter = ClaudeCLIAdapter(model=judge_model)
        if not judge_adapter.is_available():
            print(f"  {RED}Erreur: juge '{judge_model}' non disponible{RESET}")
            sys.exit(1)
        # Monkey-patch EvaluationAgent.__post_init__ to use the judge adapter
        from app.onboarding.agents import evaluation_agent as _eval_mod

        def _patched_post_init(self):
            self._llm = judge_adapter

        _eval_mod.EvaluationAgent.__post_init__ = _patched_post_init
        print(f"  {CYAN}Juge fixé: {judge_model}{RESET} {DIM}(découplé du writer){RESET}")


# ── Pipeline steps ──────────────────────────────────────────────────────────

def load_and_index(fixtures_path: Path = None) -> tuple:
    """Load fixtures and index emails."""
    path = fixtures_path or DEFAULT_FIXTURES_PATH
    loader = FixtureLoader(path)
    emails, metadata = loader.load()

    indexer = EmailIndexer(metadata["user_email"])
    indexed = indexer.index(emails)

    print(f"  Emails chargés: {BOLD}{len(emails)}{RESET}")
    print(f"  Emails envoyés: {indexed.sent_count}, reçus: {indexed.received_count}")
    print(f"  Contacts uniques: {len(indexed.contact_metrics)}")
    print(f"  Threads: {len(indexed.by_thread)}")

    return indexed, metadata


def run_agent(agent_class, indexed, agent_name: str) -> dict:
    """Run a single agent and time it."""
    print(f"\n  {DIM}▶ {agent_name}...{RESET}", end="", flush=True)
    start = time.monotonic()

    agent = agent_class()
    result = agent.analyse(indexed)

    elapsed = time.monotonic() - start
    print(f" {GREEN}✓{RESET} ({elapsed:.1f}s)")

    return result


def run_analysis(indexed, agents: list[str] | None = None) -> dict:
    """Run selected agents (or all), in parallel when multiple."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    output = {}
    agent_map = {
        "profile": (ProfileAgent, "ProfileAgent"),
        "knowledge": (KnowledgeAgent, "KnowledgeAgent"),
        "style": (StyleAgent, "StyleAgent"),
    }

    targets = [n for n in (agents or list(agent_map.keys())) if n in agent_map]
    for name in (agents or []):
        if name not in agent_map:
            print(f"  {RED}Agent inconnu: {name}{RESET}")

    if len(targets) == 1:
        # Single agent — run directly
        cls, display = agent_map[targets[0]]
        output[targets[0]] = run_agent(cls, indexed, display)
    else:
        # Multiple agents — run in parallel
        print(f"\n  {DIM}▶ Lancement de {len(targets)} agents en parallèle...{RESET}", flush=True)

        with ThreadPoolExecutor(max_workers=len(targets)) as pool:
            futures = {}
            for name in targets:
                cls, display = agent_map[name]
                futures[pool.submit(run_agent, cls, indexed, display)] = name

            for future in as_completed(futures):
                name = futures[future]
                output[name] = future.result()

    return output


def evaluate(output: dict, ground_truth: dict, use_llm_judge: bool) -> EvaluationResult:
    """Evaluate output against ground truth."""
    agent = EvaluationAgent()

    if use_llm_judge:
        return agent.evaluate(output, ground_truth)
    else:
        return agent.evaluate_without_llm(output, ground_truth)


def print_evaluation(result: EvaluationResult, use_llm_judge: bool):
    """Print formatted evaluation report."""
    method = "LLM-as-judge" if use_llm_judge else "Heuristique"
    print_section(f"Scores ({method})")

    categories = [
        ("Profile", result.profile_score),
        ("Knowledge", result.knowledge_score),
        ("Rules", result.rules_score),
    ]

    for name, score in categories:
        print(f"\n  {BOLD}{name}{RESET}")
        print_score_line("Complétude", score.completeness)
        print_score_line("Précision", score.precision)
        print_score_line("Utilité", score.usefulness)
        print_score_line("OVERALL", score.overall)

        if score.details:
            print(f"  {DIM}  → {score.details}{RESET}")

        print_list("Manquants", score.missing, RED)
        print_list("Incorrects", score.incorrect, YELLOW)

    print_section("Score global")
    print_score_line("TOTAL", result.overall_score)


def print_output_summary(output: dict):
    """Print a quick summary of what the agents produced."""
    print_section("Résumé des outputs")

    if "profile" in output:
        p = output["profile"]
        sig = p.get('signature') or {}
        print(f"  Profile: {p.get('user_name', '?')} | {sig.get('title', '?')}")
        print(f"           Langues: {p.get('languages', [])}")
        print(f"           Ton: {p.get('tone', {}).get('default_tone', '?')}")

    if "knowledge" in output:
        k = output["knowledge"]
        contacts = k.get("contacts", [])
        projects = k.get("projects", [])
        terms = k.get("terminology", {})
        print(f"  Knowledge: {len(contacts)} contacts, {len(projects)} projets, {len(terms)} termes")

    # StyleAgent output is stored under "style" key (renamed from "rules" in #151)
    style_output = output.get("style") or output.get("rules") or {}
    if style_output:
        contact_rules = style_output.get("contact_rules", [])
        general_rules = style_output.get("general_rules", [])
        print(f"  Style: {len(contact_rules)} règles contact, {len(general_rules)} règles générales")


# ── Save / Compare ─────────────────────────────────────────────────────────

def _score_to_dict(score) -> dict:
    """Convert an EvaluationScore to a serialisable dict."""
    return {
        "completeness": score.completeness,
        "precision": score.precision,
        "usefulness": score.usefulness,
        "overall": score.overall,
        "missing": score.missing,
        "incorrect": score.incorrect,
        "details": score.details,
    }


def save_run(
    output: dict,
    result: EvaluationResult,
    args,
    analysis_time: float = 0,
    eval_time: float = 0,
    total_time: float = 0,
) -> Path:
    """Save run results as a directory with config, scores, and per-agent outputs."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RESULTS_DIR / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    agents_list = args.agent or ["profile", "knowledge", "style"]

    # Determine LLM mode
    if not args.api:
        llm_mode = "claude-cli"
        llm_model = args.model or "sonnet"
    elif args.model:
        llm_mode = "model-override"
        llm_model = args.model
    else:
        llm_provider = os.environ.get("LLM_PROVIDER", "ollama")
        llm_mode = f"api:{llm_provider}"
        llm_model = os.environ.get("OLLAMA_MODEL", os.environ.get("ANTHROPIC_MODEL", "default"))

    # 1. config.json — run configuration
    config = {
        "timestamp": timestamp,
        "agents": agents_list,
        "llm_mode": llm_mode,
        "llm_model": llm_model,
        "llm_judge": not args.no_llm_judge,
        "timing": {
            "analysis_s": round(analysis_time, 1),
            "evaluation_s": round(eval_time, 1),
            "total_s": round(total_time, 1),
        },
    }
    _write_json(run_dir / "config.json", config)

    # 2. scores.json — evaluation results
    scores = {
        "profile": _score_to_dict(result.profile_score),
        "knowledge": _score_to_dict(result.knowledge_score),
        "rules": _score_to_dict(result.rules_score),
        "overall": result.overall_score,
    }
    _write_json(run_dir / "scores.json", scores)

    # 3. Per-agent output files
    for agent_name in ["profile", "knowledge", "style"]:
        agent_output = output.get(agent_name)
        if agent_output is not None:
            _write_json(run_dir / f"{agent_name}.json", agent_output)

    print(f"\n  {GREEN}Run sauvegardé:{RESET} {run_dir.relative_to(ROOT)}/")
    print(f"    {DIM}config.json   — {llm_mode} ({llm_model}), {len(agents_list)} agents{RESET}")
    print(f"    {DIM}scores.json   — overall {result.overall_score}/100{RESET}")
    for agent_name in agents_list:
        if agent_name in output:
            print(f"    {DIM}{agent_name}.json{RESET}")

    return run_dir


def _write_json(path: Path, data: dict):
    """Write a dict to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_previous_scores(previous_path: str) -> tuple[dict, str]:
    """Load scores from a previous run (directory or legacy single-file format)."""
    prev = Path(previous_path)
    if not prev.exists():
        prev = RESULTS_DIR / previous_path

    # New format: directory with scores.json
    if prev.is_dir():
        scores_file = prev / "scores.json"
        if not scores_file.exists():
            raise FileNotFoundError(f"scores.json non trouvé dans {prev}")
        with open(scores_file) as f:
            return json.load(f), prev.name

    # Legacy format: single JSON file with "scores" key
    if prev.is_file():
        with open(prev) as f:
            data = json.load(f)
        return data.get("scores", data), prev.name

    raise FileNotFoundError(f"Run non trouvé: {previous_path}")


def compare_runs(current: EvaluationResult, previous_path: str):
    """Compare current run with a previous saved run."""
    try:
        prev_scores, prev_label = _load_previous_scores(previous_path)
    except FileNotFoundError as e:
        print(f"  {RED}{e}{RESET}")
        return

    print_section("Comparaison avec le run précédent")
    print(f"  {DIM}Précédent: {prev_label}{RESET}")

    categories = [
        ("Profile", current.profile_score, prev_scores["profile"]),
        ("Knowledge", current.knowledge_score, prev_scores["knowledge"]),
        ("Rules", current.rules_score, prev_scores["rules"]),
    ]

    for name, cur_score, prev_score in categories:
        cur_val = cur_score.overall
        prev_val = prev_score["overall"]
        diff = cur_val - prev_val

        if diff > 0:
            arrow = f"{GREEN}▲ +{diff}{RESET}"
        elif diff < 0:
            arrow = f"{RED}▼ {diff}{RESET}"
        else:
            arrow = f"{DIM}= 0{RESET}"

        print(f"  {name:<12} {prev_val:>3} → {cur_val:>3}  {arrow}")

    cur_total = current.overall_score
    prev_total = prev_scores["overall"]
    diff = cur_total - prev_total
    if diff > 0:
        arrow = f"{GREEN}▲ +{diff}{RESET}"
    elif diff < 0:
        arrow = f"{RED}▼ {diff}{RESET}"
    else:
        arrow = f"{DIM}= 0{RESET}"
    print(f"  {'TOTAL':<12} {prev_total:>3} → {cur_total:>3}  {arrow}")


# ── All-personas runner ────────────────────────────────────────────────────

def run_all_personas(args):
    """Run evaluation on all available personas and print a comparison table."""
    use_llm = not args.no_llm_judge

    print_header("Onboarding Eval — All Personas")
    print(f"  {DIM}Mode: {'LLM-as-judge' if use_llm else 'Heuristique'}{RESET}")

    results = {}
    total_start = time.monotonic()

    for persona_id, description in PERSONAS.items():
        try:
            fixtures_path, gt_path = resolve_persona_paths(persona_id)
        except FileNotFoundError as e:
            print(f"\n  {YELLOW}⏭ {persona_id}: {e} — skipped{RESET}")
            continue

        print_section(f"{persona_id} — {description}")

        with open(gt_path, encoding="utf-8") as f:
            ground_truth = json.load(f)

        try:
            indexed, metadata = load_and_index(fixtures_path)

            # DomainResearchAgent removed in #151 — no longer used
            output = run_analysis(indexed, args.agent)
            result = evaluate(output, ground_truth, use_llm)

            results[persona_id] = {
                "description": description,
                "profile": result.profile_score.overall,
                "knowledge": result.knowledge_score.overall,
                "rules": result.rules_score.overall,
                "overall": result.overall_score,
            }

            print(f"  → Score: {score_color(result.overall_score)}{result.overall_score}/100{RESET}")

        except Exception as e:
            print(f"  {RED}✗ Erreur: {e}{RESET}")
            results[persona_id] = {
                "description": description,
                "profile": 0, "knowledge": 0, "rules": 0, "overall": 0,
                "error": str(e),
            }

    total_time = time.monotonic() - total_start

    # ── Comparison table ──
    if results:
        print_section("Tableau comparatif")

        # Header
        print(f"\n  {'Persona':<20} {'Profile':>8} {'Knowledge':>10} {'Rules':>8} {'TOTAL':>8}")
        print(f"  {'─' * 20} {'─' * 8} {'─' * 10} {'─' * 8} {'─' * 8}")

        totals = {"profile": 0, "knowledge": 0, "rules": 0, "overall": 0}
        count = 0

        for pid, data in results.items():
            if "error" in data:
                print(f"  {pid:<20} {RED}{'ERREUR':>8}{RESET} {'':>10} {'':>8} {'':>8}")
                continue

            p, k, r, o = data["profile"], data["knowledge"], data["rules"], data["overall"]
            print(
                f"  {pid:<20} "
                f"{score_color(p)}{p:>7}/100{RESET} "
                f"{score_color(k)}{k:>9}/100{RESET} "
                f"{score_color(r)}{r:>7}/100{RESET} "
                f"{score_color(o)}{BOLD}{o:>7}/100{RESET}"
            )
            totals["profile"] += p
            totals["knowledge"] += k
            totals["rules"] += r
            totals["overall"] += o
            count += 1

        if count > 1:
            print(f"  {'─' * 20} {'─' * 8} {'─' * 10} {'─' * 8} {'─' * 8}")
            avg_p = totals["profile"] // count
            avg_k = totals["knowledge"] // count
            avg_r = totals["rules"] // count
            avg_o = totals["overall"] // count
            print(
                f"  {'MOYENNE':<20} "
                f"{score_color(avg_p)}{avg_p:>7}/100{RESET} "
                f"{score_color(avg_k)}{avg_k:>9}/100{RESET} "
                f"{score_color(avg_r)}{avg_r:>7}/100{RESET} "
                f"{score_color(avg_o)}{BOLD}{avg_o:>7}/100{RESET}"
            )

    print_section("Temps total")
    print(f"  {total_time:.1f}s pour {len(results)} persona(s)")
    print()


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Onboarding evaluation runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--agent", nargs="+", choices=["profile", "knowledge", "style"],
        help="Run only specific agents (default: all)",
    )
    parser.add_argument(
        "--no-llm-judge", action="store_true",
        help="Use heuristic evaluation only (no LLM eval call)",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save results to tests/fixtures/eval_runs/",
    )
    parser.add_argument(
        "--compare", metavar="RUN_FILE",
        help="Compare with a previous eval run file",
    )
    parser.add_argument(
        "--dump-output", action="store_true",
        help="Print raw JSON output from agents",
    )
    parser.add_argument(
        "--model", metavar="MODEL",
        help="Override Ollama model (e.g. llama3.3:70b-instruct-q4_K_M)",
    )
    parser.add_argument(
        "--judge-model", metavar="MODEL", dest="judge_model",
        # OB-eval bias (audit 2026-04-24): default the judge to opus when
        # the writer is sonnet, so the judge != generator. Pass the value
        # explicitly to override (or pass empty string to disable). Without
        # this default, EvaluationAgent uses the same llm_onboarding adapter
        # as the writers — a known self-evaluation bias source.
        default="opus",
        help="LLM-as-judge model (default: opus when writer is sonnet, "
             "decouples writer/judge to reduce self-evaluation bias)",
    )
    parser.add_argument(
        "--api", action="store_true",
        help="Use API directly (Ollama/Claude API) instead of the default 'claude -p' pipe mode",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--fixture", metavar="PATH",
        help="Path to custom test emails fixture file",
    )
    parser.add_argument(
        "--ground-truth", metavar="PATH", dest="ground_truth_path",
        help="Path to custom ground truth file",
    )
    parser.add_argument(
        "--persona", metavar="ID",
        choices=[k for k in PERSONAS if k != "default"],
        help=f"Persona shortcut: resolves to test_emails_<ID>.json + ground_truth_<ID>.json. "
             f"Available: {', '.join(k for k in PERSONAS if k != 'default')}",
    )
    parser.add_argument(
        "--all-personas", action="store_true",
        help="Run evaluation on all available personas and produce a comparison table",
    )
    parser.add_argument(
        "--list-personas", action="store_true",
        help="List available personas and exit",
    )
    # --no-domain-research removed: DomainResearchAgent deleted in #151

    args = parser.parse_args()

    # List personas and exit
    if args.list_personas:
        print_header("Personas disponibles")
        for pid, desc in PERSONAS.items():
            tag = " (default)" if pid == "default" else ""
            print(f"  {CYAN}{pid:<20}{RESET} {desc}{tag}")
        print()
        return

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(name)s %(levelname)s: %(message)s")

    # Default: claude -p mode. Use --api to switch to direct API.
    use_claude_cli = not args.api
    if use_claude_cli:
        cli_model = args.model or "sonnet"
        activate_claude_cli(model=cli_model, judge_model=args.judge_model)
    elif args.model:
        # Override model for Ollama/Claude API
        from app.infrastructure.container import get_container
        container = get_container()
        llm = container.llm_sonnet
        if hasattr(llm, '_model'):
            llm._model = args.model  # OllamaAdapter
            # Patch timeout for large models (70B need >120s per call)
            import requests as _req
            _orig_post = _req.post
            def _patched_post(*a, **kw):
                kw['timeout'] = 600
                return _orig_post(*a, **kw)
            _req.post = _patched_post
        elif hasattr(llm, 'model'):
            llm.model = args.model   # ClaudeAdapter
        print(f"  {CYAN}Modèle override: {args.model}{RESET}")

    # ── All-personas mode ──────────────────────────────────────────────────
    if args.all_personas:
        run_all_personas(args)
        return

    # ── Resolve fixture / ground truth paths ──────────────────────────────
    if args.fixture and args.persona:
        print(f"  {RED}Erreur: --fixture et --persona sont mutuellement exclusifs{RESET}")
        sys.exit(1)

    if args.persona:
        fixtures_path, gt_path = resolve_persona_paths(args.persona)
        persona_label = f"{args.persona} ({PERSONAS[args.persona]})"
    elif args.fixture:
        fixtures_path = Path(args.fixture)
        gt_path = Path(args.ground_truth_path) if args.ground_truth_path else DEFAULT_GROUND_TRUTH_PATH
        persona_label = fixtures_path.stem
    else:
        fixtures_path = DEFAULT_FIXTURES_PATH
        gt_path = args.ground_truth_path and Path(args.ground_truth_path) or DEFAULT_GROUND_TRUTH_PATH
        persona_label = "default (Sophie Martin)"

    # Load ground truth (utf-8 explicit — Windows defaults to cp1252 which
    # mangles the French/accented JSON fixtures, audit 2026-05-06).
    with open(gt_path, encoding="utf-8") as f:
        ground_truth = json.load(f)

    print_header(f"Onboarding Eval Runner — {persona_label}")

    # Step 1: Load & index
    print_section("Chargement des fixtures")
    total_start = time.monotonic()
    indexed, metadata = load_and_index(fixtures_path)

    # Step 2: DomainResearchAgent removed in #151 — skipped

    # Step 3: Run agents
    print_section("Exécution des agents (LLM réel)")
    output = run_analysis(indexed, args.agent)

    analysis_time = time.monotonic() - total_start

    # Step 4: Output summary
    print_output_summary(output)

    if args.dump_output:
        print_section("Output brut (JSON)")
        print(json.dumps(output, ensure_ascii=False, indent=2))

    # Step 5: Evaluate
    print_section("Évaluation")
    use_llm = not args.no_llm_judge
    eval_start = time.monotonic()
    result = evaluate(output, ground_truth, use_llm)
    eval_time = time.monotonic() - eval_start

    print_evaluation(result, use_llm)

    # Step 6: Timing
    total_time = time.monotonic() - total_start
    print_section("Temps")
    print(f"  Analyse:    {analysis_time:.1f}s")
    print(f"  Évaluation: {eval_time:.1f}s")
    print(f"  Total:      {total_time:.1f}s")

    # Step 7: Save
    if args.save:
        save_run(output, result, args,
                 analysis_time=analysis_time, eval_time=eval_time, total_time=total_time)

    # Step 8: Compare
    if args.compare:
        compare_runs(result, args.compare)

    print()


if __name__ == "__main__":
    main()
