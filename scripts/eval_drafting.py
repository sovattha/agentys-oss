#!/usr/bin/env python3
"""
Drafting evaluation runner — iterative testing for DrafterAgent.

Pipeline:
  1. Extract "cases" from persona fixtures: each RECEIVED email whose thread
     contains a user SENT reply afterwards. The real sent reply becomes the
     reference_reply (proxy for a gold answer).
  2. Run DrafterAgent.draft() on each case.
  3. Score the draft with two independent signals:
     - CriticAgent (the in-prod heuristic critic, free via Haiku)
     - LLM-as-judge (rubric: faithfulness / completeness / tone / conciseness)
  4. Aggregate per persona, display, optionally save & compare.

Usage:
    python scripts/eval_drafting.py                           # default persona, claude -p
    python scripts/eval_drafting.py --persona lawyer_paris
    python scripts/eval_drafting.py --all-personas
    python scripts/eval_drafting.py --no-llm-judge            # CriticAgent only
    python scripts/eval_drafting.py --save
    python scripts/eval_drafting.py --compare RUN_DIR
    python scripts/eval_drafting.py --max-cases 3
    python scripts/eval_drafting.py --dump-drafts             # print generated drafts
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# eval_onboarding import triggers dotenv loading + sets up app module imports
from eval_onboarding import (  # noqa: E402
    ClaudeCLIAdapter,
    activate_claude_cli,
    score_color,
    print_header,
    print_section,
    print_score_line,
    print_list,
    RESET,
    BOLD,
    DIM,
    GREEN,
    YELLOW,
    RED,
    CYAN,
)

from app.agents import DrafterAgent, CriticAgent  # noqa: E402
from app.domain.entities.critique import CritiqueRequest  # noqa: E402
from app.utils.json_parser import extract_json_from_response  # noqa: E402

# Run1 — Issue #468 Phase 1 : helpers purs pour le mode v1 (--repeat / --with-gold).
# Le mode v1 reste opt-in : sans ces flags, le harness se comporte comme avant.
from eval_drafting_helpers import (  # noqa: E402
    DraftingGold,
    RunV1,
    Verdict,
    apply_explicit_max_cases,
    compare_runs as compare_runs_v1,
    compute_latency_stats,
    load_golds,
    load_run as load_run_v1,
    resolve_persona_max_cases,
    write_run as write_run_v1,
)

FIXTURES_DIR = ROOT / "tests" / "fixtures"
DEFAULT_FIXTURES_PATH = FIXTURES_DIR / "test_emails.json"
RESULTS_DIR = FIXTURES_DIR / "drafting_eval_runs"

PERSONAS = {
    "default": "Sophie Martin — PM tech bilingue FR/EN",
    "lawyer_paris": "Marc-Antoine Barreau — Avocat d'affaires Paris",
    "sales_director": "Karim Mandat — Directeur commercial immobilier Lyon",
    "startup_ceo": "Priya Pivot — CEO startup SaaS bilingue",
    "hr_director": "Catherine Carrière — DRH banque",
    "consultant_intl": "James Conseil — Consultant stratégie international",
}


def resolve_persona_path(persona_id: str) -> Path:
    if persona_id == "default":
        return DEFAULT_FIXTURES_PATH
    p = FIXTURES_DIR / f"test_emails_{persona_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"Fixture non trouvée: {p}")
    return p


# ── Case extraction ────────────────────────────────────────────────────────


@dataclass
class DraftingCase:
    """A single drafting test case extracted from persona fixtures."""

    case_id: str
    user_email: str
    user_name: str
    incoming_email: dict  # { from, from_name, subject, body, date }
    conversation_history: list[dict]  # prior thread messages, oldest first
    reference_reply: str | None  # real sent reply (proxy gold)
    thread_id: str
    user_signature: str | None = None  # signature auto-appended by prod system
    # Reply Composer keywords typed by the user. In prod, routes_helpers.py:2856
    # passes these to drafter.draft(instructions=...). Default "" matches the
    # default in agents.py:253 — empty means "auto-draft, no user guidance".
    # Run2 fixtures should populate this for cases meant to test guided drafting.
    instructions: str = ""


def load_cases_file(cases_path: Path) -> list[DraftingCase]:
    """Load a curated cases.json (output of curate_drafting_cases.py).

    The format is a list of dicts (DraftingFixtureCase shape). Used to feed
    the harness with cases stratified across personas in a single run,
    bypassing the per-persona ``extract_cases()`` path.

    Raises:
        FileNotFoundError: if cases_path does not exist.
        KeyError: if a case is missing case_id or incoming_email.
    """
    raw = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"load_cases_file: expected list at {cases_path}, got {type(raw).__name__}")

    cases: list[DraftingCase] = []
    for entry in raw:
        if "case_id" not in entry:
            raise KeyError(f"load_cases_file: entry missing 'case_id' in {cases_path}")
        if "incoming_email" not in entry:
            raise KeyError(f"load_cases_file: entry {entry['case_id']!r} missing 'incoming_email'")
        cases.append(
            DraftingCase(
                case_id=str(entry["case_id"]),
                user_email=str(entry.get("user_email", "")),
                user_name=str(entry.get("user_name", "")),
                incoming_email=entry["incoming_email"],
                conversation_history=entry.get("conversation_history") or [],
                reference_reply=entry.get("reference_reply"),
                thread_id=str(entry.get("thread_id", entry["case_id"])),
                user_signature=entry.get("user_signature"),
                instructions=str(entry.get("instructions", "") or ""),
            )
        )
    return cases


def extract_cases(
    fixtures_path: Path, max_cases: int | None = None
) -> tuple[list[DraftingCase], dict]:
    """
    Extract drafting cases from a persona fixture.

    A case = one RECEIVED email that has a user SENT reply afterwards in the
    same thread. The user's actual reply becomes ``reference_reply``.
    """
    with open(fixtures_path, encoding="utf-8") as f:
        data = json.load(f)
    metadata = data["metadata"]
    emails = data["emails"]

    # Extract user signature once (mimics prod's append_signature behavior).
    user_signature: str | None = None
    for em in emails:
        if em.get("direction") == "sent" and em.get("signature"):
            user_signature = em["signature"]
            break

    threads: dict[str, list[dict]] = {}
    for em in emails:
        threads.setdefault(em.get("thread_id") or em["id"], []).append(em)
    for tid in threads:
        threads[tid].sort(key=lambda e: e.get("date", ""))

    cases: list[DraftingCase] = []
    for tid, msgs in threads.items():
        for i, em in enumerate(msgs):
            if em.get("direction") != "received":
                continue

            reference = None
            for later in msgs[i + 1 :]:
                if later.get("direction") == "sent":
                    reference = later.get("body")
                    break
            if not reference:
                continue  # no real reply to learn from

            history = [
                {
                    "sender": (m.get("from") or {}).get("email", ""),
                    "subject": m.get("subject", ""),
                    "body": m.get("body", ""),
                    "date": m.get("date", ""),
                }
                for m in msgs[:i]
            ]
            cases.append(
                DraftingCase(
                    case_id=em["id"],
                    user_email=metadata["user_email"].lower(),
                    user_name=metadata.get("user_name", ""),
                    incoming_email={
                        "from": (em.get("from") or {}).get("email", ""),
                        "from_name": (em.get("from") or {}).get("name", ""),
                        "subject": em.get("subject", ""),
                        "body": em.get("body", ""),
                        "date": em.get("date", ""),
                    },
                    conversation_history=history,
                    reference_reply=reference,
                    thread_id=tid,
                    user_signature=user_signature,
                    # Optional Reply Composer keywords. Persona fixtures historiques
                    # n'ont pas ce champ → default "" (auto-draft). Run2 fixtures
                    # peuvent l'inclure pour tester le path guidé.
                    instructions=str(em.get("instructions", "") or ""),
                )
            )

    if max_cases:
        cases = cases[:max_cases]
    return cases, metadata


# ── Drafter runner ─────────────────────────────────────────────────────────


def _format_incoming(em: dict) -> str:
    """Format incoming email as raw text for DrafterAgent."""
    return (
        f"De: {em.get('from_name', '')} <{em.get('from', '')}>\n"
        f"Sujet: {em.get('subject', '')}\n\n"
        f"{em.get('body', '')}"
    )


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(aucune conversation antérieure)"
    return "\n\n".join(
        f"[{h.get('date', '')}] {h.get('sender', '')}\n{h.get('body', '')}"
        for h in history
    )


def run_drafter(case: DraftingCase) -> tuple[str, float]:
    """Run DrafterAgent.draft() → returns (draft, elapsed_s).

    Passes ``instructions`` so the harness mirrors prod (`routes_helpers.py:2856`).
    Without this, we'd test auto-draft only — a degenerate case that hides
    latency regressions on the guided-draft path used most in Reply Composer.
    """
    agent = DrafterAgent()
    start = time.monotonic()
    draft = agent.draft(
        email_content=_format_incoming(case.incoming_email),
        conversation_history=case.conversation_history,
        instructions=case.instructions,
        user_email=case.user_email,
    )
    return draft, time.monotonic() - start


def run_drafter_via_orchestrator(case: DraftingCase) -> tuple[str, float, dict]:
    """Run DraftOrchestrator (full pipeline Drafter→Critic→Revise).

    B2 — Issue #468 : mesurer l'impact du gate self-critique
    (``AGENTYS_SELF_CRITIQUE_GATE`` env var, lue à chaque iteration). Sans ce
    path, le harness mesurait Drafter solo et l'effet du gate était invisible.

    Returns ``(draft, elapsed_s, pipeline_info)`` où ``pipeline_info`` contient :
    - iterations : nombre d'iterations effectuées (drafter → critic → revise)
    - status : OrchestrationStatus.value (completed / timeout / failed)
    - gate_mode : env var au moment du run (lu via _read_gate_mode pour cohérence)
    - critique_decisions : list des decisions Critic par iteration
    - critique_scores : list des scores Critic par iteration
    """
    from app.services.draft_orchestrator import DraftOrchestrator
    from app.domain.entities.orchestration import OrchestrationRequest

    # Gate SelfCritique supprimé sur main 2026-05-04 (Critic refonte rend
    # le gate redondant). Fallback "off" si la fonction n'existe plus.
    try:
        from app.services.draft_orchestrator import _read_gate_mode  # type: ignore
    except ImportError:
        def _read_gate_mode() -> str:
            return "off"

    request = OrchestrationRequest(
        email_content=_format_incoming(case.incoming_email),
        instructions=case.instructions or None,
        conversation_history=case.conversation_history,
        subject=case.incoming_email.get("subject"),
        recipient_email=case.user_email,
    )
    orchestrator = DraftOrchestrator()

    start = time.monotonic()
    result = orchestrator.orchestrate(request)
    elapsed = time.monotonic() - start

    pipeline_info = {
        "iterations": len(result.iterations),
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "gate_mode": _read_gate_mode(),
        "critique_decisions": [
            it.critique_result.decision.value
            for it in result.iterations
            if it.critique_result is not None
        ],
        "critique_scores": [
            it.critique_result.get_overall_score()
            for it in result.iterations
            if it.critique_result is not None
        ],
    }
    return result.final_draft.content, elapsed, pipeline_info


# ── Heuristic scoring (CriticAgent) ────────────────────────────────────────


def score_with_critic(case: DraftingCase, draft: str) -> dict:
    """Use in-prod CriticAgent to score the draft."""
    critic = CriticAgent()
    req = CritiqueRequest(
        email_id=case.case_id,
        original_email=_format_incoming(case.incoming_email),
        draft_content=draft,
        context="",
    )
    result = critic.evaluate_draft(req)
    s = result.scores
    return {
        "coherence": s.coherence,
        "tone": s.tone,
        "completeness": s.completeness,
        "errors": s.errors,
        "conciseness": s.conciseness,
        "over_commitment": s.over_commitment,
        "emotional_intelligence": s.emotional_intelligence,
        "overall": s.calculate_overall(),
        "decision": result.decision.value,
        "suggestions": result.suggestions[:5] if result.suggestions else [],
    }


# ── LLM-as-judge (rubric) ──────────────────────────────────────────────────

# NOTE: Tunable zone #1 — rubrique du juge. Ajuste les critères et poids ici.
JUDGE_SYSTEM_PROMPT = """Tu es un évaluateur expert de brouillons de réponses email professionnelles.

Ta mission : noter un brouillon sur 4 critères, de 0 à 100 chacun.

ARCHITECTURE PRODUIT À CONNAÎTRE (ne pénalise pas ces éléments) :
- Le système ajoute automatiquement la signature (nom, titre, cabinet, coordonnées) en aval — elle peut apparaître ou non à la fin du brouillon. Ne pénalise JAMAIS l'absence de signature.
- Les formules d'appel (« Bonjour X, », « Monsieur le Directeur, », « Cher Maître, ») et les formules de politesse finales (« Cordialement, », « Bien à vous, », « Veuillez agréer... ») sont ajoutées par l'utilisateur au moment de l'envoi, ou par le système. Le drafter produit UNIQUEMENT le corps du message. Ne pénalise JAMAIS leur absence dans le brouillon.
- Concentre-toi sur la substance : informations, complétude, ton lexical, structure du corps.

CRITÈRES :

1. **faithfulness** (30 %) — Le brouillon n'invente AUCUNE information absente de l'email entrant, de l'historique de conversation, ou évidente par le contexte. Pas de faits hallucinés, de prix inventés, de dates fabriquées, de noms non fournis, de délais juridiques/techniques approximatifs présentés comme certains. Une hallucination détectée = score ≤ 40.

2. **completeness** (25 %) — Toutes les questions explicites et demandes actionnables de l'email entrant sont adressées. Une question ignorée, esquivée, ou laissée en placeholder « [À confirmer] » = pénalité forte (≤ 50).

3. **tone_match** (25 %) — Le ton LEXICAL du brouillon reflète celui du contact (miroir de formalité). Choix du vocabulaire, registre (tu/vous, familier/soutenu), pronoms (« Je » personnel vs « Nous » collectif selon ce que l'utilisateur emploie dans l'historique). Ne juge PAS les formules d'appel/clôture/signature (voir ci-dessus).

4. **conciseness** (20 %) — Longueur proportionnée à la demande. Pas de remplissage, pas de répétition, pas d'auto-référence inutile, pas de placeholders « [À confirmer] » laissés dans le texte final.

FORMAT DE SORTIE — JSON UNIQUEMENT, rien avant ni après :

{
  "faithfulness": 0-100,
  "completeness": 0-100,
  "tone_match": 0-100,
  "conciseness": 0-100,
  "overall": 0-100,
  "strengths": ["point fort 1", "..."],
  "weaknesses": ["faiblesse 1", "..."],
  "hallucinations": ["info inventée si applicable", "..."]
}

`overall` = arrondi(0.30*faithfulness + 0.25*completeness + 0.25*tone_match + 0.20*conciseness).
"""


def _draft_with_auto_signature(draft: str, signature: str | None) -> str:
    """Mimic prod's append_signature() behavior for the judge's view."""
    if not signature:
        return draft
    if signature.strip() in draft:
        return draft
    return f"{draft.rstrip()}\n\n{signature}"


def _format_instructions_section(instructions: str) -> str:
    """Section judge prompt pour les mots-clés Reply Composer.

    Vide si pas d'instructions (auto-draft). Le juge doit savoir ce que
    l'utilisateur a explicitement demandé pour ne pas pénaliser des choix
    qui étaient guidés (ex. "décliner poliment" → pas de fait inventé,
    juste une instruction respectée).
    """
    if not instructions or not instructions.strip():
        return ""
    return (
        f"=== MOTS-CLÉS UTILISATEUR (Reply Composer — guidage explicite) ===\n"
        f"{instructions.strip()}\n"
        f"Le drafter doit refléter ces directives. Ne pénalise pas un choix qui\n"
        f"découle directement d'une instruction utilisateur (ex. ton, longueur,\n"
        f"décision). Pénalise uniquement les hallucinations, omissions, ou\n"
        f"contradictions non guidées.\n\n"
    )


def score_with_llm_judge(case: DraftingCase, draft: str, judge_llm) -> dict:
    """Run LLM-as-judge on a single draft."""
    draft_for_judge = _draft_with_auto_signature(draft, case.user_signature)
    user_msg = (
        f"=== EMAIL ENTRANT ===\n"
        f"De: {case.incoming_email.get('from_name')} <{case.incoming_email.get('from')}>\n"
        f"Sujet: {case.incoming_email.get('subject')}\n\n"
        f"{case.incoming_email.get('body')}\n\n"
        f"=== HISTORIQUE DE CONVERSATION ===\n"
        f"{_format_history(case.conversation_history)}\n\n"
        f"{_format_instructions_section(case.instructions)}"
        f"=== BROUILLON À ÉVALUER (signature auto-ajoutée comme en prod) ===\n"
        f"{draft_for_judge}\n\n"
        f"=== RÉPONSE RÉELLE DE RÉFÉRENCE (indicative seulement, pas une vérité absolue) ===\n"
        f"{case.reference_reply or '(aucune)'}\n\n"
        f"Note le brouillon. Renvoie uniquement le JSON."
    )
    response = judge_llm.complete(
        system=JUDGE_SYSTEM_PROMPT,
        user=user_msg,
        max_tokens=1024,
    )
    data = extract_json_from_response(response.content) or {}
    return {
        "faithfulness": _clamp(data.get("faithfulness", 50)),
        "completeness": _clamp(data.get("completeness", 50)),
        "tone_match": _clamp(data.get("tone_match", 50)),
        "conciseness": _clamp(data.get("conciseness", 50)),
        "overall": _clamp(data.get("overall", 50)),
        "strengths": data.get("strengths", []) or [],
        "weaknesses": data.get("weaknesses", []) or [],
        "hallucinations": data.get("hallucinations", []) or [],
    }


def _clamp(v, lo: int = 0, hi: int = 100) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (ValueError, TypeError):
        return 50


# ── Per-case orchestration ─────────────────────────────────────────────────


@dataclass
class CaseResult:
    case_id: str
    subject: str
    draft: str
    elapsed_draft_s: float
    critic: dict
    judge: dict | None


def evaluate_case(case: DraftingCase, judge_llm, use_llm_judge: bool) -> CaseResult:
    draft, t_draft = run_drafter(case)
    critic = score_with_critic(case, draft)
    judge = score_with_llm_judge(case, draft, judge_llm) if use_llm_judge else None
    return CaseResult(
        case_id=case.case_id,
        subject=case.incoming_email.get("subject", ""),
        draft=draft,
        elapsed_draft_s=t_draft,
        critic=critic,
        judge=judge,
    )


# ── Aggregation & display ──────────────────────────────────────────────────


def aggregate(results: list[CaseResult]) -> dict:
    def avg(key: str, from_judge: bool = False) -> int:
        vals = []
        for r in results:
            container = r.judge if from_judge else r.critic
            if container is None:
                continue
            v = container.get(key)
            if isinstance(v, (int, float)):
                vals.append(v)
        return round(sum(vals) / len(vals)) if vals else 0

    agg = {
        "critic": {
            "coherence": avg("coherence"),
            "tone": avg("tone"),
            "completeness": avg("completeness"),
            "errors": avg("errors"),
            "conciseness": avg("conciseness"),
            "emotional_intelligence": avg("emotional_intelligence"),
            "overall": avg("overall"),
        },
        "judge": None,
    }
    if any(r.judge for r in results):
        agg["judge"] = {
            "faithfulness": avg("faithfulness", from_judge=True),
            "completeness": avg("completeness", from_judge=True),
            "tone_match": avg("tone_match", from_judge=True),
            "conciseness": avg("conciseness", from_judge=True),
            "overall": avg("overall", from_judge=True),
        }
    return agg


# ── V1 mode (Run1 Issue #468) — repeat + gold ──────────────────────────────


def score_with_llm_judge_v1(
    case: DraftingCase,
    draft: str,
    judge_llm,
    gold: DraftingGold | None,
) -> dict:
    """Variante du judge : passe un gold éditable si disponible.

    Sans gold, fallback sur le comportement existant (reference_reply du fil).
    Le prompt système et la rubrique restent identiques — on substitue juste
    la réponse de référence pour donner au juge un repère plus précis.
    """
    if gold is None:
        return score_with_llm_judge(case, draft, judge_llm)

    draft_for_judge = _draft_with_auto_signature(draft, case.user_signature)
    user_msg = (
        f"=== EMAIL ENTRANT ===\n"
        f"De: {case.incoming_email.get('from_name')} <{case.incoming_email.get('from')}>\n"
        f"Sujet: {case.incoming_email.get('subject')}\n\n"
        f"{case.incoming_email.get('body')}\n\n"
        f"=== HISTORIQUE DE CONVERSATION ===\n"
        f"{_format_history(case.conversation_history)}\n\n"
        f"{_format_instructions_section(case.instructions)}"
        f"=== BROUILLON À ÉVALUER (signature auto-ajoutée comme en prod) ===\n"
        f"{draft_for_judge}\n\n"
        f"=== RÉPONSE GOLD CIBLE (édition humaine, plus fiable que le reference_reply) ===\n"
        f"{gold.gold_body}\n\n"
        f"Note le brouillon. Renvoie uniquement le JSON."
    )
    response = judge_llm.complete(
        system=JUDGE_SYSTEM_PROMPT,
        user=user_msg,
        max_tokens=1024,
    )
    data = extract_json_from_response(response.content) or {}
    return {
        "faithfulness": _clamp(data.get("faithfulness", 50)),
        "completeness": _clamp(data.get("completeness", 50)),
        "tone_match": _clamp(data.get("tone_match", 50)),
        "conciseness": _clamp(data.get("conciseness", 50)),
        "overall": _clamp(data.get("overall", 50)),
        "strengths": data.get("strengths", []) or [],
        "weaknesses": data.get("weaknesses", []) or [],
        "hallucinations": data.get("hallucinations", []) or [],
    }


def evaluate_case_v1(
    case: DraftingCase,
    judge_llm,
    *,
    use_llm_judge: bool,
    gold: DraftingGold | None,
    repeat: int,
    warmup: bool = True,
    use_orchestrator: bool = False,
) -> dict:
    """Mode v1 : run le drafter ``repeat`` fois, mesure latence par run.

    Retourne un dict structuré pour ``RunV1.cases[]`` :
    - ``runs`` : list[{latency_ms, judge_overall, draft}]
    - ``stats`` : LatencyStats.to_dict()
    - ``critic`` : critic du dernier draft (heuristique, peu coûteux)

    Si ``warmup=True``, un run préalable est exécuté et jeté pour éviter de
    biaiser p50 avec un cold-cache Anthropic prompt cache.

    Si ``use_orchestrator=True``, mesure le full pipeline (Drafter→Critic→Revise)
    via DraftOrchestrator. Sinon, mesure DrafterAgent.draft() seul.
    """
    if repeat < 1:
        raise ValueError(f"evaluate_case_v1: repeat must be >= 1, got {repeat}")

    # Resolve drafter once per case to avoid repeated branching in the hot loop.
    drafter_fn = run_drafter_via_orchestrator if use_orchestrator else run_drafter

    if warmup and repeat >= 2:
        # Discarded run, sole purpose: warm Anthropic prompt cache.
        # Skipped when repeat==1 (statistically meaningless to warmup once).
        try:
            drafter_fn(case)
        except Exception:
            # Warmup failure must not abort the eval — propagate the error
            # only if the actual measured runs fail.
            pass

    runs: list[dict] = []
    last_draft = ""
    last_pipeline_info: dict = {}
    for i in range(repeat):
        if use_orchestrator:
            draft, elapsed_s, pipeline_info = drafter_fn(case)
            last_pipeline_info = pipeline_info
        else:
            draft, elapsed_s = drafter_fn(case)
        last_draft = draft
        latency_ms = int(elapsed_s * 1000)
        judge_score = None
        if use_llm_judge:
            judge_data = score_with_llm_judge_v1(case, draft, judge_llm, gold)
            judge_score = int(judge_data["overall"])
        run_entry: dict = {
            "run_idx": i,
            "latency_ms": latency_ms,
            "judge_overall": judge_score,
        }
        if use_orchestrator:
            # Capture per-run pipeline info for analyzing iteration count drift.
            run_entry["iterations"] = pipeline_info["iterations"]
            run_entry["critique_decisions"] = pipeline_info["critique_decisions"]
        runs.append(run_entry)

    durations = [float(r["latency_ms"]) for r in runs]
    stats = compute_latency_stats(durations)

    critic_scores = score_with_critic(case, last_draft)

    judge_overalls = [r["judge_overall"] for r in runs if r["judge_overall"] is not None]
    judge_mean = round(sum(judge_overalls) / len(judge_overalls)) if judge_overalls else None

    out: dict = {
        "case_id": case.case_id,
        "subject": case.incoming_email.get("subject", ""),
        # Captured so run.json shows whether the case used Reply Composer
        # guidance. Useful in --compare to spot baseline drift caused by
        # a Run2 fixture refresh that flipped guided/auto distribution.
        "has_instructions": bool(case.instructions and case.instructions.strip()),
        "runs": runs,
        "stats": stats.to_dict(),
        "critic_overall": critic_scores["overall"],
        "judge_overall_mean": judge_mean,
        "last_draft": last_draft,
    }
    if use_orchestrator and last_pipeline_info:
        # Pipeline info captured from the LAST measured run — gate_mode is
        # constant across runs, iterations/decisions vary with self-critique.
        out["pipeline_info"] = last_pipeline_info
    return out


def _instructions_coverage(case_results: list[dict]) -> float:
    """% de cas avec ``instructions`` non-vide. Sentinelle drift Reply Composer."""
    if not case_results:
        return 0.0
    n_with = sum(1 for c in case_results if c.get("has_instructions"))
    return round(100.0 * n_with / len(case_results), 1)


def aggregate_v1(case_results: list[dict]) -> dict:
    """Aggregate sur les case_results du mode v1.

    Calcule p50/p95 sur l'ensemble des latences (tous runs, tous cas) et la
    moyenne / quartile inférieur des judge_overall_mean par cas.
    """
    all_durations = [
        float(r["latency_ms"])
        for case in case_results
        for r in case["runs"]
    ]
    overall_stats = compute_latency_stats(all_durations) if all_durations else None

    judge_means = [c["judge_overall_mean"] for c in case_results if c["judge_overall_mean"] is not None]
    if judge_means:
        judge_overall_mean = sum(judge_means) / len(judge_means)
        # p25 = lower quartile of per-case judge means → highlights the tail
        # of weak cases (more useful than min for spotting systemic issues).
        sorted_means = sorted(judge_means)
        p25_idx = max(0, len(sorted_means) // 4 - 1)
        judge_overall_p25 = float(sorted_means[p25_idx])
    else:
        judge_overall_mean = 0.0
        judge_overall_p25 = 0.0

    return {
        "p50_ms": overall_stats.p50_ms if overall_stats else 0.0,
        "p95_ms": overall_stats.p95_ms if overall_stats else 0.0,
        "mean_ms": overall_stats.mean_ms if overall_stats else 0.0,
        "n_total_runs": overall_stats.n if overall_stats else 0,
        "judge_overall_mean": round(judge_overall_mean, 1),
        "judge_overall_p25": round(judge_overall_p25, 1),
        # % cas Reply Composer guidé. Drift d'une baseline doit lever une
        # alerte : changer ce ratio fausse la comparaison latence/qualité.
        "instructions_coverage_pct": _instructions_coverage(case_results),
    }


def build_run_v1(
    *,
    persona: str,
    case_results: list[dict],
    args,
) -> RunV1:
    """Assemble un RunV1 complet à partir des résultats v1."""
    from datetime import datetime, timezone

    config = {
        "persona": persona,
        "drafter_model": "claude-haiku-4-5",  # current default per app/config.py:161
        "judge_model": (args.model or "sonnet") if not args.api else "container.llm_sonnet",
        "use_claude_cli": not args.api,
        "with_gold": bool(getattr(args, "with_gold", False)),
        "gold_dir": str(getattr(args, "gold_dir", "")) or None,
        "repeat": int(getattr(args, "repeat", 1)),
        "warmup": True,  # always on in v1 path
        "no_llm_judge": bool(args.no_llm_judge),
        # B2 — captured so --compare can flag baseline/current path mismatch
        # ("orchestrator" run is incomparable to "drafter" run by design).
        "use_orchestrator": bool(getattr(args, "use_orchestrator", False)),
        "gate_mode": (
            os.environ.get("AGENTYS_SELF_CRITIQUE_GATE", "off")
            if getattr(args, "use_orchestrator", False)
            else None
        ),
    }

    return RunV1(
        schema_version=1,
        timestamp_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        config=config,
        cases=case_results,
        aggregate=aggregate_v1(case_results),
    )


def print_aggregate_v1(run: RunV1):
    """Affichage humain du RunV1 — focus sur latence + qualité."""
    agg = run.aggregate
    print_section("Latence (tous cas, tous runs)")
    print(f"  n_runs:   {agg['n_total_runs']}")
    print(f"  p50:      {agg['p50_ms']:.0f}ms")
    print(f"  p95:      {agg['p95_ms']:.0f}ms")
    print(f"  mean:     {agg['mean_ms']:.0f}ms")
    print_section("Qualité (LLM-as-judge)")
    print(f"  overall mean: {agg['judge_overall_mean']:.1f}")
    print(f"  overall p25:  {agg['judge_overall_p25']:.1f} (quartile inférieur)")


def print_aggregate(agg: dict, use_llm_judge: bool):
    print_section("Scores agrégés — CriticAgent (heuristique, gratuit)")
    c = agg["critic"]
    print_score_line("Cohérence", c["coherence"])
    print_score_line("Ton", c["tone"])
    print_score_line("Complétude", c["completeness"])
    print_score_line("Erreurs", c["errors"])
    print_score_line("Concision", c["conciseness"])
    print_score_line("Intelligence émotionnelle", c["emotional_intelligence"])
    print_score_line(f"{BOLD}OVERALL{RESET}", c["overall"])

    if use_llm_judge and agg["judge"]:
        print_section("Scores agrégés — LLM-as-judge (rubrique)")
        j = agg["judge"]
        print_score_line("Faithfulness", j["faithfulness"])
        print_score_line("Completeness", j["completeness"])
        print_score_line("Tone match", j["tone_match"])
        print_score_line("Conciseness", j["conciseness"])
        print_score_line(f"{BOLD}OVERALL{RESET}", j["overall"])


def print_case_details(res: CaseResult, use_llm_judge: bool):
    print(f"\n  {BOLD}{res.case_id}{RESET} — {DIM}{res.subject[:70]}{RESET}")
    c = res.critic
    critic_line = f"Critic {score_color(c['overall'])}{c['overall']}/100{RESET}"
    print(f"    {critic_line} ({res.elapsed_draft_s:.1f}s)")
    if use_llm_judge and res.judge:
        j = res.judge
        print(f"    Judge  {score_color(j['overall'])}{j['overall']}/100{RESET}")
        if j.get("hallucinations"):
            print_list("    Hallucinations", j["hallucinations"], RED)
        if j.get("weaknesses"):
            print_list("    Faiblesses", j["weaknesses"], YELLOW)


# ── All-personas mode ──────────────────────────────────────────────────────


def run_all_personas(args, judge_llm) -> dict:
    use_llm = not args.no_llm_judge
    print_header("Drafting Eval — All Personas")
    results_by_persona: dict[str, dict] = {}

    for pid, desc in PERSONAS.items():
        try:
            fx = resolve_persona_path(pid)
        except FileNotFoundError as e:
            print(f"\n  {YELLOW}⏭ {pid}: {e} — skipped{RESET}")
            continue

        print_section(f"{pid} — {desc}")
        try:
            cases, _meta = extract_cases(
                fx, max_cases=resolve_persona_max_cases(args.max_cases)
            )
            if not cases:
                print(f"  {YELLOW}Aucun cas (pas de thread received+sent){RESET}")
                continue
            print(f"  {len(cases)} cas extraits")
            results: list[CaseResult] = []
            for c in cases:
                try:
                    results.append(evaluate_case(c, judge_llm, use_llm))
                except Exception as e:
                    print(f"  {RED}✗ {c.case_id}: {e}{RESET}")
            if not results:
                continue
            agg = aggregate(results)
            results_by_persona[pid] = {"aggregate": agg, "cases": results}
            co = agg["critic"]["overall"]
            if agg["judge"]:
                jo = agg["judge"]["overall"]
                print(
                    f"  → Critic {score_color(co)}{co}/100{RESET}  "
                    f"Judge {score_color(jo)}{jo}/100{RESET}"
                )
            else:
                print(f"  → Critic {score_color(co)}{co}/100{RESET}")
        except Exception as e:
            print(f"  {RED}✗ Erreur: {e}{RESET}")

    if results_by_persona:
        _print_comparison_table(results_by_persona, use_llm)
    return results_by_persona


def _print_comparison_table(results_by_persona: dict, use_llm: bool):
    print_section("Tableau comparatif")
    header = f"\n  {'Persona':<20} {'Critic':>10}"
    if use_llm:
        header += f" {'Judge':>10}"
    print(header)
    sep = f"  {'─' * 20} {'─' * 10}" + (f" {'─' * 10}" if use_llm else "")
    print(sep)

    totals = {"critic": 0, "judge": 0}
    count = {"critic": 0, "judge": 0}

    for pid, data in results_by_persona.items():
        co = data["aggregate"]["critic"]["overall"]
        line = f"  {pid:<20} {score_color(co)}{co:>7}/100{RESET}"
        totals["critic"] += co
        count["critic"] += 1
        if use_llm and data["aggregate"]["judge"]:
            jo = data["aggregate"]["judge"]["overall"]
            line += f" {score_color(jo)}{jo:>7}/100{RESET}"
            totals["judge"] += jo
            count["judge"] += 1
        print(line)

    if count["critic"] > 1:
        print(sep)
        avg_c = totals["critic"] // count["critic"]
        line = f"  {'MOYENNE':<20} {score_color(avg_c)}{BOLD}{avg_c:>7}/100{RESET}"
        if use_llm and count["judge"]:
            avg_j = totals["judge"] // count["judge"]
            line += f" {score_color(avg_j)}{BOLD}{avg_j:>7}/100{RESET}"
        print(line)


# ── Save / compare ─────────────────────────────────────────────────────────


def save_run(results_by_persona: dict, args) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RESULTS_DIR / f"run_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "timestamp": ts,
        "llm_mode": "api" if args.api else "claude-cli",
        "llm_model": args.model or "sonnet",
        "llm_judge": not args.no_llm_judge,
        "max_cases": resolve_persona_max_cases(args.max_cases),
        "personas": list(results_by_persona.keys()),
    }
    (run_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary = {
        pid: {
            "critic_overall": data["aggregate"]["critic"]["overall"],
            "judge_overall": (
                data["aggregate"]["judge"]["overall"]
                if data["aggregate"]["judge"]
                else None
            ),
            "num_cases": len(data["cases"]),
        }
        for pid, data in results_by_persona.items()
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for pid, data in results_by_persona.items():
        payload = {
            "aggregate": data["aggregate"],
            "cases": [
                {
                    "case_id": r.case_id,
                    "subject": r.subject,
                    "draft": r.draft,
                    "elapsed_draft_s": round(r.elapsed_draft_s, 2),
                    "critic": r.critic,
                    "judge": r.judge,
                }
                for r in data["cases"]
            ],
        }
        (run_dir / f"{pid}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(f"\n  {GREEN}Run sauvegardé:{RESET} {run_dir.relative_to(ROOT)}/")
    print(f"    {DIM}config.json  — {config['llm_mode']} ({config['llm_model']}){RESET}")
    print(f"    {DIM}summary.json — {len(results_by_persona)} persona(s){RESET}")
    return run_dir


def compare_runs(current: dict, previous_path: str):
    prev = Path(previous_path)
    if not prev.exists():
        prev = RESULTS_DIR / previous_path
    if not prev.exists():
        print(f"  {RED}Run précédent introuvable: {previous_path}{RESET}")
        return
    if prev.is_dir():
        summary_file = prev / "summary.json"
        if not summary_file.exists():
            print(f"  {RED}summary.json absent dans {prev}{RESET}")
            return
        prev_summary = json.loads(summary_file.read_text(encoding="utf-8"))
    else:
        prev_summary = json.loads(prev.read_text(encoding="utf-8"))

    print_section("Comparaison avec run précédent")
    print(f"  {DIM}Précédent: {prev.name}{RESET}\n")

    for pid, data in current.items():
        if pid not in prev_summary:
            print(f"  {pid:<20} {DIM}(absent du précédent){RESET}")
            continue
        cur_c = data["aggregate"]["critic"]["overall"]
        prv_c = prev_summary[pid]["critic_overall"]
        diff_c = cur_c - prv_c
        arrow_c = (
            f"{GREEN}▲ +{diff_c}{RESET}"
            if diff_c > 0
            else (f"{RED}▼ {diff_c}{RESET}" if diff_c < 0 else f"{DIM}= 0{RESET}")
        )
        line = f"  {pid:<20} critic {prv_c:>3} → {cur_c:>3}  {arrow_c}"
        if data["aggregate"]["judge"] and prev_summary[pid].get("judge_overall") is not None:
            cur_j = data["aggregate"]["judge"]["overall"]
            prv_j = prev_summary[pid]["judge_overall"]
            diff_j = cur_j - prv_j
            arrow_j = (
                f"{GREEN}▲ +{diff_j}{RESET}"
                if diff_j > 0
                else (f"{RED}▼ {diff_j}{RESET}" if diff_j < 0 else f"{DIM}= 0{RESET}")
            )
            line += f"   judge {prv_j:>3} → {cur_j:>3}  {arrow_j}"
        print(line)


# ── V1 single-persona runner (Run1 — Issue #468) ──────────────────────────


def _resolve_v1_save_path(persona: str, args) -> Path:
    """Where to write run.json under the v1 schema."""
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return RESULTS_DIR / f"v1_{persona}_{timestamp}" / "run.json"


def _run_v1_single_persona(args, judge_llm) -> None:
    """V1 mode: single persona, repeat>=1 runs per case, optional gold judge.

    Output : RunV1 schema_version=1, written to drafting_eval_runs/v1_<persona>_<ts>/.
    """
    persona = args.persona or "default"
    fixture = resolve_persona_path(persona)
    print_header(f"Drafting Eval V1 — {persona} ({PERSONAS[persona]})")

    cases, _meta = extract_cases(
        fixture, max_cases=resolve_persona_max_cases(args.max_cases)
    )
    print(f"  {len(cases)} cas extraits depuis {fixture.relative_to(ROOT)}")
    if not cases:
        print(f"  {RED}Aucun cas — il faut des threads avec un received suivi d'un sent{RESET}")
        sys.exit(1)

    golds: dict[str, DraftingGold] = {}
    if args.with_gold:
        gold_dir = Path(args.gold_dir)
        gold_path = gold_dir / "golds.json"
        golds = load_golds(gold_path)
        print(f"  {len(golds)} golds chargés depuis {gold_path}")
        missing = [c.case_id for c in cases if c.case_id not in golds]
        if missing:
            print(
                f"  {YELLOW}Avertissement : {len(missing)} cas sans gold "
                f"(judge utilisera reference_reply){RESET}"
            )

    use_llm = not args.no_llm_judge
    repeat = max(1, args.repeat)
    use_orchestrator = bool(args.use_orchestrator)
    total_start = time.monotonic()
    case_results: list[dict] = []
    for c in cases:
        label = f"{c.case_id} — {c.incoming_email.get('subject', '')[:50]}"
        path_tag = "[orchestrator]" if use_orchestrator else "[drafter]"
        print(f"\n  {DIM}▶ {label} {path_tag} (×{repeat}){RESET}", end="", flush=True)
        try:
            res = evaluate_case_v1(
                c,
                judge_llm,
                use_llm_judge=use_llm,
                gold=golds.get(c.case_id),
                repeat=repeat,
                use_orchestrator=use_orchestrator,
            )
            case_results.append(res)
            stats = res["stats"]
            tail = f" p50={stats['p50_ms']:.0f}ms"
            if res["judge_overall_mean"] is not None:
                tail += f" judge={res['judge_overall_mean']}"
            if "pipeline_info" in res:
                tail += f" iter={res['pipeline_info']['iterations']}"
            print(f" {GREEN}✓{RESET}{tail}")
        except Exception as e:
            print(f" {RED}✗ {e}{RESET}")
    total_time = time.monotonic() - total_start

    if not case_results:
        print(f"\n  {RED}Aucun cas évalué avec succès{RESET}")
        sys.exit(1)

    run = build_run_v1(persona=persona, case_results=case_results, args=args)
    print_aggregate_v1(run)
    print_section("Temps")
    print(
        f"  Total: {total_time:.1f}s "
        f"({total_time / max(1, len(case_results)):.1f}s/cas, repeat={repeat})"
    )

    if args.save:
        save_path = _resolve_v1_save_path(persona, args)
        write_run_v1(run, save_path)
        print(f"  {GREEN}✓ Sauvegardé : {save_path.relative_to(ROOT)}{RESET}")

    if args.compare:
        baseline_path = Path(args.compare)
        # Allow --compare RUN_DIR (looks for run.json) or --compare PATH/run.json directly.
        if baseline_path.is_dir():
            baseline_path = baseline_path / "run.json"
        try:
            baseline = load_run_v1(baseline_path)
        except (ValueError, KeyError, FileNotFoundError) as e:
            print(f"  {RED}--compare failed: {e}{RESET}")
            print(f"  {DIM}(compare with --with-gold/--repeat requires a v1 run.json){RESET}")
            sys.exit(1)
        verdict = compare_runs_v1(baseline=baseline, current=run)
        print_section(f"Comparaison vs baseline ({baseline_path.relative_to(ROOT) if baseline_path.is_relative_to(ROOT) else baseline_path})")
        color = {Verdict.PASS: GREEN, Verdict.WARN: YELLOW, Verdict.FAIL: RED}[verdict.status]
        print(f"  {color}{verdict.status.value.upper()}{RESET}")
        print(f"  judge_delta:  {verdict.judge_delta:+.1f}")
        print(f"  p50_delta:    {verdict.p50_delta_pct:+.1f}%")
        for reason in verdict.reasons:
            print(f"  - {reason}")
        if verdict.status == Verdict.FAIL:
            sys.exit(1)


# ── V1 cases-file runner (multi-personas) ─────────────────────────────────


def _run_v1_cases_file(args, judge_llm) -> None:
    """V1 mode loading cases directly from a curated cases.json.

    Bypasses persona-by-persona extract_cases. Uses the stratified output of
    scripts/curate_drafting_cases.py. Supports the same flags as the single-
    persona runner (--with-gold, --repeat, --use-orchestrator, --gate-mode,
    --drafter-temperature, --save, --compare).
    """
    cases_path = Path(args.cases_file)
    if not cases_path.exists():
        print(f"  {RED}--cases-file not found: {cases_path}{RESET}")
        sys.exit(1)

    cases = load_cases_file(cases_path)
    n_total = len(cases)
    cases, truncated = apply_explicit_max_cases(cases, args.max_cases)
    print_header(f"Drafting Eval V1 — multi-personas via {cases_path.name}")
    print(f"  {len(cases)} cas chargés")
    if truncated:
        print(
            f"  {YELLOW}⚠ --max-cases {args.max_cases} : troncature explicite"
            f" ({len(cases)}/{n_total} cas du fichier) — les agrégats ne sont"
            f" pas comparables à une baseline complète{RESET}"
        )

    golds: dict[str, DraftingGold] = {}
    if args.with_gold:
        gold_dir = Path(args.gold_dir)
        gold_path = gold_dir / "golds.json"
        golds = load_golds(gold_path)
        print(f"  {len(golds)} golds chargés depuis {gold_path}")
        missing = [c.case_id for c in cases if c.case_id not in golds]
        if missing:
            print(
                f"  {YELLOW}Avertissement : {len(missing)} cas sans gold{RESET}"
            )

    use_llm = not args.no_llm_judge
    repeat = max(1, args.repeat)
    use_orchestrator = bool(args.use_orchestrator)
    total_start = time.monotonic()
    case_results: list[dict] = []
    for c in cases:
        label = f"{c.case_id} — {c.incoming_email.get('subject', '')[:50]}"
        path_tag = "[orchestrator]" if use_orchestrator else "[drafter]"
        print(f"\n  {DIM}▶ {label} {path_tag} (×{repeat}){RESET}", end="", flush=True)
        try:
            res = evaluate_case_v1(
                c,
                judge_llm,
                use_llm_judge=use_llm,
                gold=golds.get(c.case_id),
                repeat=repeat,
                use_orchestrator=use_orchestrator,
            )
            case_results.append(res)
            stats = res["stats"]
            tail = f" p50={stats['p50_ms']:.0f}ms"
            if res["judge_overall_mean"] is not None:
                tail += f" judge={res['judge_overall_mean']}"
            if "pipeline_info" in res:
                tail += f" iter={res['pipeline_info']['iterations']}"
            print(f" {GREEN}✓{RESET}{tail}")
        except Exception as e:
            print(f" {RED}✗ {e}{RESET}")
    total_time = time.monotonic() - total_start

    if not case_results:
        print(f"\n  {RED}Aucun cas évalué avec succès{RESET}")
        sys.exit(1)

    # Use a synthetic "multi" persona label for run.json config
    run = build_run_v1(persona="multi", case_results=case_results, args=args)
    print_aggregate_v1(run)
    print_section("Temps")
    print(
        f"  Total: {total_time:.1f}s "
        f"({total_time / max(1, len(case_results)):.1f}s/cas, repeat={repeat})"
    )

    if args.save:
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        save_path = RESULTS_DIR / f"v1_multi_{timestamp}" / "run.json"
        write_run_v1(run, save_path)
        print(f"  {GREEN}✓ Sauvegardé : {save_path.relative_to(ROOT)}{RESET}")

    if args.compare:
        baseline_path = Path(args.compare)
        if baseline_path.is_dir():
            baseline_path = baseline_path / "run.json"
        try:
            baseline = load_run_v1(baseline_path)
        except (ValueError, KeyError, FileNotFoundError) as e:
            print(f"  {RED}--compare failed: {e}{RESET}")
            sys.exit(1)
        verdict = compare_runs_v1(baseline=baseline, current=run)
        rel = baseline_path.relative_to(ROOT) if baseline_path.is_relative_to(ROOT) else baseline_path
        print_section(f"Comparaison vs baseline ({rel})")
        color = {Verdict.PASS: GREEN, Verdict.WARN: YELLOW, Verdict.FAIL: RED}[verdict.status]
        print(f"  {color}{verdict.status.value.upper()}{RESET}")
        print(f"  judge_delta:  {verdict.judge_delta:+.1f}")
        print(f"  p50_delta:    {verdict.p50_delta_pct:+.1f}%")
        for reason in verdict.reasons:
            print(f"  - {reason}")
        if verdict.status == Verdict.FAIL:
            sys.exit(1)


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Drafting evaluation runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--persona",
        choices=[k for k in PERSONAS if k != "default"],
        help=f"Persona shortcut. Available: {', '.join(k for k in PERSONAS if k != 'default')}",
    )
    parser.add_argument("--all-personas", action="store_true")
    parser.add_argument("--list-personas", action="store_true")
    parser.add_argument(
        "--no-llm-judge",
        action="store_true",
        help="Skip LLM-as-judge (use CriticAgent only)",
    )
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--compare", metavar="RUN_DIR")
    parser.add_argument(
        "--api",
        action="store_true",
        help="Use direct API instead of claude -p (default: claude -p)",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        help="Override model (default: sonnet via claude-cli)",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Max cases per persona (default: 5). En mode --cases-file :"
        " aucun défaut — tous les cas du fichier sont évalués ; ne tronque"
        " que si fourni explicitement (la troncature est alors affichée).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--dump-drafts", action="store_true", help="Print each generated draft"
    )
    # Run1 — Issue #468 Phase 1 : flags v1 (latence + gold).
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="Run drafter N times per case for p50/p95 latency stats (default: 1)."
        " Triggers v1 mode when N >= 2.",
    )
    parser.add_argument(
        "--with-gold",
        action="store_true",
        help="Use editable golds from --gold-dir as judge reference."
        " Triggers v1 mode and writes run.json schema_version=1 on --save.",
    )
    parser.add_argument(
        "--gold-dir",
        metavar="PATH",
        default=str(FIXTURES_DIR / "drafting_eval"),
        help="Directory containing golds.json (default: tests/fixtures/drafting_eval/).",
    )
    # B2 — measure DraftOrchestrator (full pipeline Drafter→Critic→Revise)
    # rather than DrafterAgent.draft() alone. Required to evaluate the impact
    # of --gate-mode (self-critique skip).
    parser.add_argument(
        "--use-orchestrator",
        action="store_true",
        help="Mesure le full pipeline (DraftOrchestrator) au lieu du Drafter solo."
        " Capture iterations + gate verdict dans run.json par cas. Triggers v1 mode.",
    )
    parser.add_argument(
        "--gate-mode",
        choices=["off", "shadow", "active"],
        default=None,
        help="Patch local AGENTYS_SELF_CRITIQUE_GATE pour la session."
        " off = Critic toujours run. shadow = telemetry only. active = skip Critic"
        " si self_score >= 85 + confidence high.",
    )
    # Run3 — test si la non-determinisme du drafter (msg-001 judge 38..85 sur
    # 3 runs identiques en baseline) provient de la temperature dynamique
    # (formality_to_temperature: 0.25..0.45). --drafter-temperature 0.0 force
    # une valeur fixe pour la session (monkey-patch).
    parser.add_argument(
        "--drafter-temperature",
        type=float,
        default=None,
        metavar="T",
        help="Force a fixed drafter temperature (0.0-1.0) by monkey-patching"
        " formality_to_temperature for the session. Useful to test variance"
        " reduction. None = production default (adaptive 0.25-0.45).",
    )
    # Run3 — load curated multi-personas cases.json directly (bypasses --persona).
    # Output of scripts/curate_drafting_cases.py. Stratification cross-personas
    # for a more representative baseline than single-persona runs.
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Load curated cases.json (output of curate_drafting_cases.py)."
        " Bypasses --persona / --all-personas. Triggers v1 mode.",
    )
    args = parser.parse_args()

    if args.list_personas:
        print_header("Personas disponibles")
        for pid, desc in PERSONAS.items():
            tag = " (default)" if pid == "default" else ""
            print(f"  {CYAN}{pid:<20}{RESET} {desc}{tag}")
        print()
        return

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(name)s %(levelname)s: %(message)s",
    )

    # ── V1 mode detection + arg validation ──
    # Doit etre AVANT activate_claude_cli pour que les erreurs argparse-style
    # (exit 2) s'observent meme sur runner ou claude CLI est absent (sinon
    # exit 1 "claude not found" avant d'atteindre la validation -> test
    # tests/test_eval_drafting_helpers.py::test_v1_with_all_personas_exits_2
    # casse en CI Hetzner).
    # Triggered by --with-gold, --repeat>=2, --use-orchestrator, or --cases-file.
    # --cases-file makes single-persona constraint moot (cases are pre-stratified).
    v1_mode = (
        bool(args.with_gold)
        or args.repeat > 1
        or bool(args.use_orchestrator)
        or bool(args.cases_file)
    )

    # --cases-file makes --all-personas redundant (cases are already cross-persona).
    if v1_mode and args.all_personas and not args.cases_file:
        print(
            f"{RED}Error: v1 mode (--with-gold or --repeat>=2) currently requires "
            f"--persona X or --cases-file PATH.{RESET}"
        )
        print("  --cases-file <path> charge un cases.json curé (multi-personas).")
        sys.exit(2)

    if args.drafter_temperature is not None and not 0.0 <= args.drafter_temperature <= 1.0:
        print(f"  {RED}--drafter-temperature must be in [0.0, 1.0]{RESET}")
        sys.exit(2)

    # Default: claude -p mode for both internals AND judge
    use_claude_cli = not args.api
    if use_claude_cli:
        model = args.model or "sonnet"
        activate_claude_cli(model=model)
        judge_llm = ClaudeCLIAdapter(model=model)
    else:
        from app.infrastructure.container import get_container

        judge_llm = get_container().llm_sonnet

    # B2 — patch local AGENTYS_SELF_CRITIQUE_GATE for the session if requested.
    # Done BEFORE any DraftOrchestrator import / instantiation so _read_gate_mode
    # picks it up. Original value restored at exit via try/finally is
    # unnecessary here (process-local; harness is one-shot).
    if args.gate_mode is not None:
        os.environ["AGENTYS_SELF_CRITIQUE_GATE"] = args.gate_mode
        print(f"  {CYAN}AGENTYS_SELF_CRITIQUE_GATE={args.gate_mode}{RESET} (session-local)")

    # Run3 — patch drafter temperature for the session if requested. Tests
    # whether the variance observed in baseline (msg-001 judge 38..85) comes
    # from the adaptive 0.25-0.45 mapping vs a deeper drafter issue.
    if args.drafter_temperature is not None:
        from app.prompts import helpers as _prompt_helpers
        _fixed_temp = float(args.drafter_temperature)
        _prompt_helpers.formality_to_temperature = lambda formality: _fixed_temp
        # Also patch the symbol already imported into agents (caching).
        import app.agents as _agents_mod
        _agents_mod.formality_to_temperature = lambda formality: _fixed_temp
        print(f"  {CYAN}drafter temperature forcée à {_fixed_temp}{RESET} (session-local monkey-patch)")

    if v1_mode:
        if args.cases_file:
            _run_v1_cases_file(args, judge_llm)
        else:
            _run_v1_single_persona(args, judge_llm)
        return

    # ── All-personas mode ──
    if args.all_personas:
        total_start = time.monotonic()
        results_by_persona = run_all_personas(args, judge_llm)
        total_time = time.monotonic() - total_start
        print_section("Temps total")
        total_cases = sum(len(d["cases"]) for d in results_by_persona.values())
        print(f"  {total_time:.1f}s pour {total_cases} cas sur {len(results_by_persona)} personas")
        if args.save and results_by_persona:
            save_run(results_by_persona, args)
        if args.compare and results_by_persona:
            compare_runs(results_by_persona, args.compare)
        print()
        return

    # ── Single persona mode ──
    pid = args.persona or "default"
    fixture = resolve_persona_path(pid)
    print_header(f"Drafting Eval — {pid} ({PERSONAS[pid]})")

    cases, _meta = extract_cases(
        fixture, max_cases=resolve_persona_max_cases(args.max_cases)
    )
    print(f"  {len(cases)} cas extraits depuis {fixture.relative_to(ROOT)}")
    if not cases:
        print(
            f"  {RED}Aucun cas — il faut des threads avec un received suivi d'un sent{RESET}"
        )
        return

    use_llm = not args.no_llm_judge
    total_start = time.monotonic()
    results: list[CaseResult] = []
    for c in cases:
        label = f"{c.case_id} — {c.incoming_email.get('subject', '')[:50]}"
        print(f"\n  {DIM}▶ {label}{RESET}", end="", flush=True)
        try:
            res = evaluate_case(c, judge_llm, use_llm)
            results.append(res)
            tail = f" critic={res.critic['overall']}"
            if res.judge:
                tail += f" judge={res.judge['overall']}"
            print(f" {GREEN}✓{RESET}{tail}")
        except Exception as e:
            print(f" {RED}✗ {e}{RESET}")
    total_time = time.monotonic() - total_start

    if not results:
        print(f"\n  {RED}Aucun cas évalué avec succès{RESET}")
        return

    agg = aggregate(results)
    print_aggregate(agg, use_llm)

    print_section("Détail par cas")
    for res in results:
        print_case_details(res, use_llm)
        if args.dump_drafts:
            print(f"\n{DIM}--- DRAFT ---{RESET}\n{res.draft}\n{DIM}--- END ---{RESET}\n")

    print_section("Temps")
    print(f"  Total: {total_time:.1f}s ({total_time / len(results):.1f}s/cas)")

    all_results = {pid: {"aggregate": agg, "cases": results}}
    if args.save:
        save_run(all_results, args)
    if args.compare:
        compare_runs(all_results, args.compare)
    print()


if __name__ == "__main__":
    main()
