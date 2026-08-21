# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Issue #454 P0 — vérifie que les vestiges label-driven ont disparu du prompt.

Avant ce refactor, `get_standard_draft_prompts` (path SmartRouter STANDARD)
injectait dans le user prompt via `_universal_rules.txt:16` :
- `FORMALITY: VERY CASUAL.` (label tri-bucket via `_formality_to_label`)
- `Use VOUS. Do NOT switch to tu even if the contact uses tu.` (anti-mirror rigide)

Ces deux directives contredisent la règle MIROIR DU TON propre au legacy
DrafterAgent (`drafter_system_prompt.txt:11-18`) — sauf que la path SmartRouter
n'embarquait PAS cette règle, donc le user prompt anti-miroir gagnait.

Post-#454 P0 :
- `_universal_rules.txt:16` — placeholders `{formality_label}` + `{pronoun_directive}` retirés
- `_apply_tone_bias`, `_extract_default_tone`, `_formality_to_label` supprimés (`identity.py`)
- `STANDARD_DRAFT_SYSTEM_PROMPT` embarque désormais sa propre règle MIROIR DU TON
  → `TestSystemPromptMirrorDirective` fait office de garantie positive

Ce module fait office de gate de régression : si un futur refactor ré-introduit
un label de formalité, une directive anti-miroir, OU drop la règle de miroir du
system prompt, ces tests échouent immédiatement.
"""

from __future__ import annotations

from app.prompts.builders import get_standard_draft_prompts, _segments_to_text


def _build_prompts(body: str = "Salut, ça va ?", subject: str = "Coucou") -> tuple[str, str]:
    """Helper : invoque le builder STANDARD avec un email casual minimal.

    `account_id=None` force le fallback `load_knowledge_base()` sur le fichier
    `default_knowledge.txt` — chemin réaliste pour un compte en fresh state.

    P0.1 (2026-05-14): le builder retourne désormais `(list[SystemSegment], str)`.
    On aplatit ici pour conserver le contrat string des assertions ci-dessous.
    """
    segments, user_prompt = get_standard_draft_prompts(
        sender="alice@example.com",
        subject=subject,
        body=body,
        account_id=None,
    )
    return _segments_to_text(segments), user_prompt


class TestNoFormalityLabel:
    """Le label tri-bucket `FORMALITY: VERY CASUAL` ne doit plus apparaître."""

    def test_user_prompt_has_no_formality_label_marker(self):
        """Aucune injection `FORMALITY: ...` ne doit subsister dans le user prompt."""
        _, user_prompt = _build_prompts()
        assert "FORMALITY:" not in user_prompt, (
            "Le label `FORMALITY:` injecte une directive caricaturale qui contredit "
            "la règle MIROIR DU TON du system prompt. Voir issue #454 P0."
        )

    def test_user_prompt_has_no_formality_bucket_directive(self):
        """Aucune directive `FORMALITY: <BUCKET>` injectée comme label ne doit subsister.

        Note : les mots `VERY CASUAL` / `FORMAL` / etc. apparaissent légitimement
        dans `_universal_rules.txt` RULE 4 — LENGTH (mapping bucket → longueur de
        réponse). Ce test cible la signature exacte du legacy : `FORMALITY: ` +
        un bucket en MAJUSCULES, qui était l'empreinte de `_formality_to_label`
        injecté dans RULE 3 — TONE.
        """
        _, user_prompt = _build_prompts()
        for bucket in ("VERY CASUAL", "CASUAL", "NEUTRAL", "FORMAL", "VERY FORMAL"):
            legacy_directive = f"FORMALITY: {bucket}"
            assert legacy_directive not in user_prompt, (
                f"L'empreinte legacy `{legacy_directive}` est encore injectée — "
                f"voir issue #454 P0."
            )


class TestNoAntiMirrorDirective:
    """Le `pronoun_directive` rigide qui dit `Do NOT switch to ...` doit disparaître."""

    def test_user_prompt_has_no_anti_mirror_pronoun_directive(self):
        """Aucune phrase `Do NOT switch to (tu|vous)` ne doit subsister."""
        _, user_prompt = _build_prompts()
        assert "Do NOT switch to" not in user_prompt, (
            "Le `pronoun_directive` (`builders.py:1031-1036`) contredit la règle "
            "MIROIR DU TON. La gestion du tu/vous est désormais déléguée à la règle "
            "miroir du system prompt + au `_LEARNING_PRIORITY_HEADER` per-contact. "
            "Voir issue #454 P0."
        )

    def test_user_prompt_does_not_force_pronoun_globally(self):
        """Le couple `Use TU.`/`Use VOUS.` suivi d'une négation est l'empreinte exacte du legacy."""
        _, user_prompt = _build_prompts()
        # On cherche les empreintes exactes du legacy plutôt que `Use TU` ou `Use VOUS`
        # seuls — ces séquences peuvent apparaître dans un futur bloc d'override
        # per-contact (ex: « Cet utilisateur préfère TU avec ce contact »).
        legacy_signatures = (
            "Use TU. Do NOT switch to vous",
            "Use VOUS. Do NOT switch to tu",
        )
        for signature in legacy_signatures:
            assert signature not in user_prompt, (
                f"L'empreinte legacy `{signature}` est encore injectée — voir issue #454 P0."
            )


class TestKBDefaultToneNoLongerBiases:
    """Un KB legacy contenant `**Ton par défaut**: Formel` ne doit plus générer
    de directive anti-miroir, même quand le memoire.md est injecté dans le bloc
    `<CONTEXTE>` du system prompt.

    Path testé : la KB est passée via le paramètre `knowledge_base` (chemin
    réel quand un agent charge un memoire.md legacy). Avant #454 P0,
    `_extract_default_tone` lisait cette chaîne et pilotait `_apply_tone_bias`
    + `pronoun_directive`. Post-P0, ces fonctions n'existent plus — la KB
    devient un simple bloc factuel sans pouvoir directif.
    """

    def test_kb_with_formal_default_does_not_inject_anti_mirror(self):
        """KB stamped Formel + email casual → aucune directive `Do NOT switch to`."""
        kb_legacy = (
            "## Profil\n"
            "- **Nom complet**: Test User\n"
            "- **Ton par défaut**: Formel\n"
            "- **Langue**: Français\n"
        )
        _, user_prompt = get_standard_draft_prompts(
            sender="bob@example.com",
            subject="Coucou",
            body="Salut, t'as 2 min pour me dire si t'es dispo demain ?",
            knowledge_base=kb_legacy,
            account_id=None,
        )
        assert "Do NOT switch to" not in user_prompt
        for bucket in ("VERY CASUAL", "CASUAL", "NEUTRAL", "FORMAL", "VERY FORMAL"):
            assert f"FORMALITY: {bucket}" not in user_prompt


class TestSystemPromptMirrorDirective:
    """Garantie positive : le system prompt DOIT référencer la règle de miroir.

    Sans cette assertion, un futur refactor pourrait drop la règle MIROIR DU TON
    sans qu'aucun test ne le détecte — laissant les paths SmartRouter STANDARD/
    STREAMING sans aucun signal de ton (la règle MIROIR DU TON du
    `drafter_system_prompt.txt` n'est PAS injectée dans `STANDARD_DRAFT_SYSTEM_PROMPT`,
    elle est propre au legacy `DrafterAgent`).
    """

    def test_system_prompt_contains_mirror_directive(self):
        """Le system prompt STANDARD doit contenir une directive de miroir explicite."""
        system_prompt, _ = _build_prompts()
        normalized = system_prompt.lower()
        # On accepte mirror (EN) ou miroir (FR) — la règle peut être phrasée
        # dans l'une ou l'autre langue selon l'évolution du template.
        has_mirror = "mirror" in normalized or "miroir" in normalized
        assert has_mirror, (
            "Le system prompt STANDARD doit inclure une directive de miroir du ton — "
            "sans elle, les paths SmartRouter STANDARD/STREAMING n'ont aucun signal "
            "de ton (la règle MIROIR DU TON de `drafter_system_prompt.txt` n'est pas "
            "injectée dans cette path)."
        )
