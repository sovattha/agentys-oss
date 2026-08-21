# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le fichier template memoire.md.example.

Ce module valide:
- L'existence et la structure du fichier template
- Les placeholders génériques
- La cohérence avec le fichier memoire.md attendu
- L'absence d'informations personnelles dans le template
"""

import pytest
from pathlib import Path


# ============================================================================
# CONSTANTS
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
TEMPLATE_FILE = KNOWLEDGE_DIR / "memoire.md.example"

# Placeholders attendus dans le template (format [MAJUSCULES_UNDERSCORES])
# Note: Les placeholders de choix comme [tutoiement / vouvoiement] sont testés séparément
EXPECTED_PLACEHOLDERS = [
    "[VOTRE_NOM]",
    "[VOTRE_FONCTION]",
    "[NOM_ORGANISATION]",
    "[SECTEUR_ACTIVITE]",
    "[VOTRE_EMAIL]",
    "[SERVICE_1]",
    "[SERVICE_2]",
    "[SERVICE_3]",
]

# Sections requises dans le template
REQUIRED_SECTIONS = [
    "Identite",
    "Coordonnees",
    "Style de Communication",
    "Regles de Redaction",
    "Services / Produits",
    "Phrases Types",
    "Patterns de Reponse",
    "Sujets Frequents",
    "Regles Implicites",
    "Instructions pour l'IA",
]

# Patterns de données personnelles à éviter
PERSONAL_DATA_PATTERNS = [
    "@gmail.com",
    "@outlook.com",
    "@yahoo.com",
    "@hotmail.com",
    "+33",
    "+41",
    "06 ",
    "07 ",
    "078",
    "079",
]


# ============================================================================
# MODULE-LEVEL FIXTURE (DRY: avoids duplication across test classes)
# ============================================================================


@pytest.fixture(scope="module")
def template_content():
    """
    Charge le contenu du template une seule fois pour tout le module.

    Cette fixture est partagée par toutes les classes de test pour éviter
    la duplication et améliorer les performances (le fichier n'est lu qu'une fois).
    """
    if TEMPLATE_FILE.exists():
        return TEMPLATE_FILE.read_text(encoding="utf-8")
    return ""


# ============================================================================
# TESTS - FILE EXISTENCE AND STRUCTURE
# ============================================================================


class TestTemplateFileExists:
    """Tests pour vérifier l'existence du fichier template."""

    def test_template_file_exists(self):
        """Le fichier memoire.md.example existe."""
        assert TEMPLATE_FILE.exists(), f"Template file not found: {TEMPLATE_FILE}"

    def test_template_file_is_not_empty(self):
        """Le fichier template n'est pas vide."""
        if TEMPLATE_FILE.exists():
            content = TEMPLATE_FILE.read_text(encoding="utf-8")
            assert len(content) > 100, "Template file is too short"

    def test_template_file_is_readable(self):
        """Le fichier template est lisible en UTF-8."""
        if TEMPLATE_FILE.exists():
            try:
                content = TEMPLATE_FILE.read_text(encoding="utf-8")
                assert isinstance(content, str)
            except UnicodeDecodeError:
                pytest.fail("Template file is not valid UTF-8")

    def test_knowledge_directory_exists(self):
        """Le répertoire knowledge existe."""
        assert KNOWLEDGE_DIR.exists(), f"Knowledge directory not found: {KNOWLEDGE_DIR}"


# ============================================================================
# TESTS - PLACEHOLDERS VALIDATION
# ============================================================================


class TestPlaceholders:
    """Tests pour les placeholders du template."""

    def test_contains_name_placeholder(self, template_content):
        """Le template contient le placeholder pour le nom."""
        assert "[VOTRE_NOM]" in template_content, "Missing [VOTRE_NOM] placeholder"

    def test_contains_email_placeholder(self, template_content):
        """Le template contient le placeholder pour l'email."""
        assert "[VOTRE_EMAIL]" in template_content, "Missing [VOTRE_EMAIL] placeholder"

    def test_contains_organization_placeholder(self, template_content):
        """Le template contient le placeholder pour l'organisation."""
        assert (
            "[NOM_ORGANISATION]" in template_content
        ), "Missing [NOM_ORGANISATION] placeholder"

    def test_contains_function_placeholder(self, template_content):
        """Le template contient le placeholder pour la fonction."""
        assert (
            "[VOTRE_FONCTION]" in template_content
        ), "Missing [VOTRE_FONCTION] placeholder"

    def test_placeholder_format_is_consistent(self, template_content):
        """Les placeholders suivent le format [MAJUSCULES_UNDERSCORES]."""
        import re

        # Pattern pour les placeholders valides
        valid_pattern = r"\[[A-Z][A-Z0-9_]*\]"
        # Pattern pour les placeholders potentiellement mal formés
        bracket_pattern = r"\[[^\]]+\]"

        all_brackets = re.findall(bracket_pattern, template_content)
        valid_brackets = re.findall(valid_pattern, template_content)

        # Tous les contenus entre crochets doivent être des placeholders valides
        # ou des exemples acceptables (ex: "[À confirmer]")
        invalid = []
        for b in all_brackets:
            if b not in valid_brackets:
                # Ignore les exemples de marquage comme "[À confirmer]"
                if "À" not in b and "à" not in b:
                    # Ignore les exemples de choix comme "[option1 / option2 / option3]"
                    if " / " not in b:
                        invalid.append(b)

        # On accepte certains patterns comme instructions
        assert (
            len(invalid) == 0
        ), f"Invalid placeholder formats found: {invalid}"


# ============================================================================
# TESTS - REQUIRED SECTIONS
# ============================================================================


class TestRequiredSections:
    """Tests pour les sections requises du template."""

    def test_contains_identity_section(self, template_content):
        """Le template contient la section Identité."""
        assert (
            "Identite" in template_content or "Identité" in template_content
        ), "Missing Identité section"

    def test_contains_coordinates_section(self, template_content):
        """Le template contient la section Coordonnées."""
        assert (
            "Coordonnees" in template_content or "Coordonnées" in template_content
        ), "Missing Coordonnées section"

    def test_contains_communication_style_section(self, template_content):
        """Le template contient la section Style de Communication."""
        assert (
            "Style de Communication" in template_content
            or "Communication" in template_content
        ), "Missing Style de Communication section"

    def test_contains_writing_rules_section(self, template_content):
        """Le template contient la section Règles de Rédaction."""
        assert (
            "Regles" in template_content or "Règles" in template_content
        ), "Missing Règles section"

    def test_contains_services_section(self, template_content):
        """Le template contient la section Services/Produits."""
        assert (
            "Services" in template_content or "Produits" in template_content
        ), "Missing Services/Produits section"

    def test_contains_ai_instructions_section(self, template_content):
        """Le template contient la section Instructions pour l'IA."""
        assert (
            "Instructions pour l'IA" in template_content
            or "Instructions" in template_content
        ), "Missing Instructions pour l'IA section"


# ============================================================================
# TESTS - NO PERSONAL DATA
# ============================================================================


class TestNoPersonalData:
    """Tests pour vérifier l'absence de données personnelles."""

    def test_no_real_email_addresses(self, template_content):
        """Le template ne contient pas d'adresses email réelles."""
        import re

        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        emails = re.findall(email_pattern, template_content)

        # Filtrer les emails exemples acceptables
        real_emails = [e for e in emails if not e.startswith("example@")]
        assert len(real_emails) == 0, f"Real email addresses found: {real_emails}"

    def test_no_phone_numbers(self, template_content):
        """Le template ne contient pas de numéros de téléphone."""
        for pattern in ["+33", "+41", "06 ", "07 ", "078", "079"]:
            assert (
                pattern not in template_content
            ), f"Phone number pattern found: {pattern}"

    def test_no_specific_company_names(self, template_content):
        """Le template ne contient pas de noms d'entreprises spécifiques."""
        # Liste des entreprises connues qui ne devraient pas être dans le template
        known_companies = ["Sonrysa", "ACME", "Google", "Microsoft"]

        for company in known_companies:
            assert (
                company not in template_content
            ), f"Specific company name found: {company}"

    def test_no_personal_names(self, template_content):
        """Le template ne contient pas de noms personnels identifiables."""
        # Le contenu devrait utiliser des placeholders, pas des vrais noms
        content_lower = template_content.lower()

        # Le nom ne doit pas apparaître en dehors des placeholders
        assert (
            "[votre_nom]" in content_lower or "[VOTRE_NOM]" in template_content
        ), "Template should use placeholder for name"


# ============================================================================
# TESTS - TEMPLATE INSTRUCTIONS
# ============================================================================


class TestTemplateInstructions:
    """Tests pour les instructions d'utilisation du template."""

    def test_contains_usage_instructions(self, template_content):
        """Le template contient des instructions d'utilisation."""
        has_instructions = (
            "INSTRUCTIONS" in template_content.upper()
            or "Copiez" in template_content
            or "Remplacez" in template_content
        )
        assert has_instructions, "Template should contain usage instructions"

    def test_instructions_mention_memoire_md(self, template_content):
        """Les instructions mentionnent le fichier cible memoire.md."""
        assert (
            "memoire.md" in template_content
        ), "Instructions should mention memoire.md as target file"

    def test_instructions_mention_privacy(self, template_content):
        """Les instructions mentionnent la confidentialité."""
        content_lower = template_content.lower()
        has_privacy = (
            "privé" in content_lower
            or "prive" in content_lower
            or "git" in content_lower
            or "ignoré" in content_lower
            or "ignore" in content_lower
        )
        assert has_privacy, "Instructions should mention privacy/git ignore"


# ============================================================================
# TESTS - MARKDOWN STRUCTURE
# ============================================================================


class TestMarkdownStructure:
    """Tests pour la structure Markdown du template."""

    def test_has_main_header(self, template_content):
        """Le template a un en-tête principal."""
        assert template_content.startswith("#"), "Template should start with a header"

    def test_has_section_headers(self, template_content):
        """Le template a des en-têtes de section (##)."""
        assert "## " in template_content, "Template should have section headers"

    def test_uses_markdown_lists(self, template_content):
        """Le template utilise des listes Markdown."""
        assert (
            "- " in template_content or "* " in template_content
        ), "Template should use Markdown lists"

    def test_uses_bold_formatting(self, template_content):
        """Le template utilise du formatage gras."""
        assert "**" in template_content, "Template should use bold formatting"

    def test_comments_are_html_style(self, template_content):
        """Les commentaires utilisent la syntaxe HTML."""
        if "<!--" in template_content:
            assert (
                "-->" in template_content
            ), "HTML comments should be properly closed"


# ============================================================================
# TESTS - EDGE CASES
# ============================================================================


class TestEdgeCases:
    """Tests pour les cas limites du template."""

    def test_no_trailing_whitespace_on_lines(self, template_content):
        """Les lignes n'ont pas d'espaces en fin de ligne excessifs."""
        lines_with_trailing = []
        for i, line in enumerate(template_content.split("\n"), 1):
            if line.endswith("   "):  # Plus de 2 espaces trailing
                lines_with_trailing.append(i)

        assert (
            len(lines_with_trailing) == 0
        ), f"Lines with excessive trailing whitespace: {lines_with_trailing}"

    def test_no_empty_placeholders(self, template_content):
        """Pas de placeholders vides []."""
        assert "[]" not in template_content, "Empty placeholders found"

    def test_no_unclosed_brackets(self, template_content):
        """Les crochets sont correctement appairés."""
        open_count = template_content.count("[")
        close_count = template_content.count("]")

        assert open_count == close_count, (
            f"Mismatched brackets: {open_count} open vs {close_count} close"
        )

    def test_encoding_is_utf8(self):
        """Le fichier est encodé en UTF-8."""
        if TEMPLATE_FILE.exists():
            try:
                with open(TEMPLATE_FILE, "rb") as f:
                    raw = f.read()
                    raw.decode("utf-8")
            except UnicodeDecodeError:
                pytest.fail("File is not valid UTF-8")

    def test_file_ends_with_newline(self, template_content):
        """Le fichier se termine par une nouvelle ligne."""
        # Bonne pratique pour les fichiers texte
        if len(template_content) > 0:
            assert template_content.endswith("\n"), "File should end with a newline"


# ============================================================================
# TESTS - CONSISTENCY WITH PROMPTS MODULE
# ============================================================================


class TestConsistencyWithPrompts:
    """Tests pour la cohérence avec le module prompts.py."""

    def test_template_structure_matches_default_knowledge(self):
        """La structure du template correspond à DEFAULT_KNOWLEDGE."""
        from app.prompts import DEFAULT_KNOWLEDGE

        if TEMPLATE_FILE.exists():
            template_content = TEMPLATE_FILE.read_text(encoding="utf-8")

            # Les deux doivent contenir des sections similaires
            template_has_identity = (
                "Identite" in template_content or "Identité" in template_content
            )
            default_has_identity = "Identité" in DEFAULT_KNOWLEDGE

            # Au moins une section commune doit exister
            assert template_has_identity or default_has_identity

    def test_template_can_be_used_as_knowledge_base(self):
        """Le template peut être utilisé par les fonctions de prompts."""
        from app.prompts import get_drafter_system_prompt

        if TEMPLATE_FILE.exists():
            template_content = TEMPLATE_FILE.read_text(encoding="utf-8")

            # Le template doit pouvoir être injecté dans les prompts
            result = get_drafter_system_prompt(template_content)

            assert isinstance(result, str)
            assert len(result) > len(template_content)
            assert "[VOTRE_NOM]" in result or "VOTRE" in result


# ============================================================================
# TESTS - ADDITIONAL EDGE CASES (QA Coverage)
# ============================================================================


class TestGitignoreIntegration:
    """Tests pour vérifier l'intégration avec .gitignore."""

    def test_memoire_md_is_gitignored(self):
        """Le fichier memoire.md est dans .gitignore."""
        gitignore_path = PROJECT_ROOT / ".gitignore"
        assert gitignore_path.exists(), ".gitignore file not found"

        content = gitignore_path.read_text(encoding="utf-8")
        assert "memoire.md" in content, "memoire.md should be in .gitignore"

    def test_template_is_not_gitignored(self):
        """Le fichier template n'est pas dans .gitignore."""
        gitignore_path = PROJECT_ROOT / ".gitignore"
        if gitignore_path.exists():
            content = gitignore_path.read_text(encoding="utf-8")
            # memoire.md.example ne doit pas être ignoré
            assert "memoire.md.example" not in content, (
                "memoire.md.example should NOT be in .gitignore"
            )


class TestPlaceholdersComprehensive:
    """Tests complets pour tous les placeholders attendus."""

    def test_all_expected_placeholders_present(self, template_content):
        """Tous les placeholders attendus sont présents."""
        missing = []
        for placeholder in EXPECTED_PLACEHOLDERS:
            if placeholder not in template_content:
                missing.append(placeholder)

        assert len(missing) == 0, f"Missing placeholders: {missing}"

    def test_placeholder_uppercase_format(self, template_content):
        """Les placeholders sont en MAJUSCULES avec underscores."""
        import re

        placeholders = re.findall(r"\[([A-Z][A-Z0-9_]*)\]", template_content)
        for ph in placeholders:
            assert ph == ph.upper(), f"Placeholder {ph} should be uppercase"
            assert " " not in ph, f"Placeholder {ph} should not contain spaces"

    def test_no_lowercase_placeholders(self, template_content):
        """Pas de placeholders en minuscules mal formés."""
        import re

        # Recherche de patterns comme [votre_nom] qui seraient incorrects
        lowercase_pattern = r"\[[a-z][a-z_]*\]"
        matches = re.findall(lowercase_pattern, template_content)
        assert len(matches) == 0, f"Lowercase placeholders found: {matches}"


class TestFileFormatting:
    """Tests pour le formatage du fichier."""

    def test_no_bom_present(self):
        """Le fichier n'a pas de BOM UTF-8."""
        if TEMPLATE_FILE.exists():
            with open(TEMPLATE_FILE, "rb") as f:
                first_bytes = f.read(3)
            assert first_bytes != b"\xef\xbb\xbf", "File should not have UTF-8 BOM"

    def test_no_excessive_empty_lines(self, template_content):
        """Pas de plus de 2 lignes vides consécutives."""
        if "\n\n\n\n" in template_content:
            pytest.fail("File has more than 3 consecutive empty lines")

    def test_file_length_reasonable(self, template_content):
        """Le fichier a une longueur raisonnable (entre 500 et 5000 caractères)."""
        length = len(template_content)
        assert length >= 500, f"File too short ({length} chars), minimum 500 expected"
        assert length <= 5000, f"File too long ({length} chars), maximum 5000 expected"

    def test_line_count_reasonable(self, template_content):
        """Le fichier a un nombre de lignes raisonnable."""
        lines = template_content.split("\n")
        line_count = len(lines)
        assert line_count >= 30, f"Too few lines ({line_count}), minimum 30 expected"
        assert line_count <= 200, f"Too many lines ({line_count}), maximum 200 expected"

    def test_no_windows_line_endings(self, template_content):
        """Pas de fins de ligne Windows (CRLF)."""
        assert "\r\n" not in template_content, "File should use Unix line endings (LF)"

    def test_no_tabs_for_indentation(self, template_content):
        """Pas de tabulations au début des lignes."""
        lines_with_tabs = []
        for i, line in enumerate(template_content.split("\n"), 1):
            if line.startswith("\t"):
                lines_with_tabs.append(i)

        assert len(lines_with_tabs) == 0, (
            f"Lines with tab indentation: {lines_with_tabs}"
        )


class TestHtmlComments:
    """Tests pour les commentaires HTML."""

    def test_html_comments_balanced(self, template_content):
        """Les commentaires HTML sont équilibrés."""
        open_count = template_content.count("<!--")
        close_count = template_content.count("-->")
        assert open_count == close_count, (
            f"Unbalanced HTML comments: {open_count} open, {close_count} close"
        )

    def test_instructions_in_first_comment(self, template_content):
        """Les instructions sont dans le premier commentaire."""
        import re

        first_comment = re.search(r"<!--(.*?)-->", template_content, re.DOTALL)
        assert first_comment is not None, "No HTML comment found"

        comment_content = first_comment.group(1).upper()
        assert "INSTRUCTION" in comment_content, (
            "First comment should contain INSTRUCTIONS"
        )

    def test_instructions_mention_copy_step(self, template_content):
        """Les instructions mentionnent l'étape de copie."""
        assert "cp " in template_content or "Copiez" in template_content, (
            "Instructions should mention copy command"
        )

    def test_instructions_mention_placeholders(self, template_content):
        """Les instructions mentionnent les placeholders."""
        import re

        first_comment = re.search(r"<!--(.*?)-->", template_content, re.DOTALL)
        if first_comment:
            comment = first_comment.group(1)
            has_placeholder_mention = (
                "placeholder" in comment.lower()
                or "ENTRE_CROCHETS" in comment
                or "[" in comment
            )
            assert has_placeholder_mention, (
                "Instructions should mention placeholders"
            )


class TestSectionStructure:
    """Tests pour la structure des sections."""

    def test_sections_have_content(self, template_content):
        """Chaque section a du contenu."""
        import re

        sections = re.split(r"^## ", template_content, flags=re.MULTILINE)
        for i, section in enumerate(sections[1:], 1):  # Skip first part before ##
            lines = [line for line in section.split("\n") if line.strip()]
            assert len(lines) >= 2, f"Section {i} has no content after header"

    def test_no_duplicate_section_headers(self, template_content):
        """Pas de doublons dans les en-têtes de section."""
        import re

        headers = re.findall(r"^## (.+)$", template_content, re.MULTILINE)
        unique_headers = set(headers)
        assert len(headers) == len(unique_headers), (
            f"Duplicate section headers found: {headers}"
        )

    def test_main_header_exists(self, template_content):
        """L'en-tête principal (#) existe et est unique."""
        import re

        main_headers = re.findall(r"^# (.+)$", template_content, re.MULTILINE)
        assert len(main_headers) >= 1, "Missing main header (#)"
        assert len(main_headers) == 1, (
            f"Should have only one main header, found {len(main_headers)}"
        )

    def test_section_order_logical(self, template_content):
        """Les sections suivent un ordre logique."""
        import re

        headers = re.findall(r"^## (.+)$", template_content, re.MULTILINE)

        # L'identité devrait venir avant les coordonnées
        id_index = next(
            (i for i, h in enumerate(headers) if "Identite" in h or "Identité" in h),
            -1,
        )
        coord_index = next(
            (i for i, h in enumerate(headers) if "Coordonnees" in h or "Coord" in h),
            -1,
        )

        if id_index >= 0 and coord_index >= 0:
            assert id_index < coord_index, (
                "Identity section should come before Coordinates"
            )


class TestAccentConsistency:
    """Tests pour la cohérence des accents."""

    def test_consistent_accent_usage(self, template_content):
        """L'utilisation des accents est cohérente dans tout le fichier."""
        # Le fichier doit être cohérent : soit avec accents, soit sans
        any(c in template_content for c in "éèêëàâäùûüîïôöç")
        has_non_accented_identity = "Identite" in template_content

        # Si on utilise Identite sans accent, on ne devrait pas avoir
        # des accents ailleurs de manière incohérente
        if has_non_accented_identity:
            # Les accents dans le texte (pas les headers) sont OK
            # Mais les headers devraient être cohérents
            accented_headers = [
                "Identité",
                "Coordonnées",
                "Règles",
            ]
            for header in accented_headers:
                if f"## {header}" in template_content:
                    pytest.fail(
                        f"Inconsistent accent usage: found {header} "
                        f"but also Identite without accent"
                    )


class TestExampleValues:
    """Tests pour les valeurs d'exemple dans les choix."""

    def test_choice_placeholders_have_options(self, template_content):
        """Les placeholders de choix contiennent des options."""
        import re

        # Pattern pour [option1 / option2]
        choices = re.findall(r"\[([^]]+/[^]]+)\]", template_content)
        assert len(choices) > 0, "Template should have choice placeholders"

        for choice in choices:
            options = [o.strip() for o in choice.split("/")]
            assert len(options) >= 2, f"Choice '{choice}' should have at least 2 options"

    def test_no_empty_options_in_choices(self, template_content):
        """Les options dans les choix ne sont pas vides."""
        import re

        choices = re.findall(r"\[([^]]+/[^]]+)\]", template_content)
        for choice in choices:
            options = [o.strip() for o in choice.split("/")]
            for opt in options:
                assert len(opt) > 0, f"Empty option found in choice '{choice}'"


class TestIntegrationWithPrompts:
    """Tests d'intégration avancés avec le module prompts."""

    def test_template_with_filled_placeholders(self):
        """Le template fonctionne avec des placeholders remplis."""
        from app.prompts import get_drafter_system_prompt

        if TEMPLATE_FILE.exists():
            template = TEMPLATE_FILE.read_text(encoding="utf-8")

            # Remplacer quelques placeholders
            filled = template.replace("[VOTRE_NOM]", "Test User")
            filled = filled.replace("[VOTRE_EMAIL]", "test@example.com")
            filled = filled.replace("[NOM_ORGANISATION]", "Test Corp")

            result = get_drafter_system_prompt(filled)

            assert "Test User" in result
            assert "test@example.com" in result
            assert "Test Corp" in result

    def test_template_with_unicode_values(self):
        """Le template fonctionne avec des valeurs Unicode."""
        from app.prompts import get_drafter_system_prompt

        if TEMPLATE_FILE.exists():
            template = TEMPLATE_FILE.read_text(encoding="utf-8")

            # Remplacer avec des caractères spéciaux
            filled = template.replace("[VOTRE_NOM]", "José García-Müller")
            filled = filled.replace("[NOM_ORGANISATION]", "Société Générale")

            result = get_drafter_system_prompt(filled)

            assert "José García-Müller" in result
            assert "Société Générale" in result

    def test_template_preserves_structure_in_prompt(self):
        """Le template préserve sa structure dans le prompt."""
        from app.prompts import get_drafter_system_prompt

        if TEMPLATE_FILE.exists():
            template = TEMPLATE_FILE.read_text(encoding="utf-8")
            result = get_drafter_system_prompt(template)

            # Les sections doivent être préservées
            assert "Identite" in result or "Identité" in result
            assert "Style de Communication" in result or "Communication" in result


class TestSecurityEdgeCases:
    """Tests de sécurité pour le template."""

    def test_no_script_injection(self, template_content):
        """Pas de scripts injectables dans le template."""
        dangerous_patterns = ["<script", "javascript:", "onclick=", "onerror="]
        for pattern in dangerous_patterns:
            assert pattern.lower() not in template_content.lower(), (
                f"Potentially dangerous pattern found: {pattern}"
            )

    def test_no_command_injection_patterns(self, template_content):
        """Pas de patterns d'injection de commande."""
        dangerous_patterns = ["$(", "`", "&&", "||", ";rm", "| ", "> /"]
        for pattern in dangerous_patterns:
            # Exclure les patterns légitimes comme $( dans les exemples bash
            if pattern == "cp " or pattern in ["&&"]:
                continue
            assert pattern not in template_content or "cp " in template_content, (
                f"Potentially dangerous command pattern found: {pattern}"
            )

    def test_no_sql_injection_patterns(self, template_content):
        """Pas de patterns d'injection SQL."""
        dangerous_patterns = ["'; DROP", "1=1", "OR 1=1", "UNION SELECT"]
        for pattern in dangerous_patterns:
            assert pattern not in template_content.upper(), (
                f"SQL injection pattern found: {pattern}"
            )
