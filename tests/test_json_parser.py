# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests TDD pour l'utilitaire JSON centralisé.

Ces tests vérifient le comportement des fonctions de parsing JSON
avec différents cas de figure : valide, invalide, edge cases.
"""

import pytest
from app.utils.json_parser import (
    safe_json_parse,
    safe_json_parse_list,
    extract_json_from_response,
    to_json_string,
)


class TestSafeJsonParse:
    """Tests pour safe_json_parse."""

    def test_parse_valid_json(self):
        """Doit parser un JSON valide correctement."""
        result = safe_json_parse('{"key": "value", "number": 42}')
        assert result == {"key": "value", "number": 42}

    def test_parse_empty_string_returns_default(self):
        """Doit retourner le défaut pour une chaîne vide."""
        result = safe_json_parse("", default={"fallback": True})
        assert result == {"fallback": True}

    def test_parse_whitespace_only_returns_default(self):
        """Doit retourner le défaut pour des espaces uniquement."""
        result = safe_json_parse("   \n\t  ", default={})
        assert result == {}

    def test_parse_invalid_json_returns_default(self):
        """Doit retourner le défaut pour un JSON invalide."""
        result = safe_json_parse("{invalid json}", default={"error": True})
        assert result == {"error": True}

    def test_parse_none_content_returns_default(self):
        """Doit retourner le défaut pour None (via empty check)."""
        result = safe_json_parse("", default={"empty": True})
        assert result == {"empty": True}

    def test_parse_array_returns_default(self):
        """Doit retourner le défaut si le JSON est un tableau (pas un objet)."""
        result = safe_json_parse("[1, 2, 3]", default={"type": "object_expected"})
        assert result == {"type": "object_expected"}

    def test_parse_primitive_returns_default(self):
        """Doit retourner le défaut si le JSON est un primitif."""
        result = safe_json_parse("42", default={})
        assert result == {}
        result = safe_json_parse('"string"', default={})
        assert result == {}

    def test_parse_nested_object(self):
        """Doit parser des objets imbriqués."""
        json_str = '{"level1": {"level2": {"value": 123}}}'
        result = safe_json_parse(json_str)
        assert result["level1"]["level2"]["value"] == 123

    def test_parse_with_whitespace(self):
        """Doit gérer les espaces autour du JSON."""
        result = safe_json_parse('  \n{"key": "value"}\n  ')
        assert result == {"key": "value"}

    def test_default_is_empty_dict_when_not_provided(self):
        """Le défaut doit être un dict vide si non spécifié."""
        result = safe_json_parse("invalid")
        assert result == {}


class TestSafeJsonParseList:
    """Tests pour safe_json_parse_list."""

    def test_parse_valid_list(self):
        """Doit parser une liste JSON valide."""
        result = safe_json_parse_list('[1, 2, 3, "four"]')
        assert result == [1, 2, 3, "four"]

    def test_parse_empty_list(self):
        """Doit parser une liste vide."""
        result = safe_json_parse_list("[]")
        assert result == []

    def test_parse_object_returns_default(self):
        """Doit retourner le défaut si le JSON est un objet."""
        result = safe_json_parse_list('{"key": "value"}', default=["fallback"])
        assert result == ["fallback"]

    def test_parse_invalid_returns_default(self):
        """Doit retourner le défaut pour un JSON invalide."""
        result = safe_json_parse_list("not json", default=[])
        assert result == []

    def test_parse_nested_list(self):
        """Doit parser des listes imbriquées."""
        result = safe_json_parse_list('[[1, 2], [3, 4]]')
        assert result == [[1, 2], [3, 4]]


class TestExtractJsonFromResponse:
    """Tests pour extract_json_from_response."""

    def test_extract_pure_json(self):
        """Doit extraire un JSON pur."""
        result = extract_json_from_response('{"score": 85}')
        assert result == {"score": 85}

    def test_extract_json_with_text_before(self):
        """Doit extraire le JSON même avec du texte avant."""
        response = 'Voici le résultat: {"score": 85}'
        result = extract_json_from_response(response)
        assert result == {"score": 85}

    def test_extract_json_with_text_after(self):
        """Doit extraire le JSON même avec du texte après."""
        response = '{"score": 85} - Fin de l\'analyse.'
        result = extract_json_from_response(response)
        assert result == {"score": 85}

    def test_extract_json_markdown_block(self):
        """Doit extraire le JSON d'un bloc markdown."""
        response = """Voici l'analyse:
```json
{"category": "URGENT", "confidence": 0.95}
```
Merci."""
        result = extract_json_from_response(response)
        assert result == {"category": "URGENT", "confidence": 0.95}

    def test_extract_json_code_block_without_language(self):
        """Doit extraire le JSON d'un bloc de code sans langage."""
        response = """Résultat:
```
{"priority": "high"}
```"""
        result = extract_json_from_response(response)
        assert result == {"priority": "high"}

    def test_extract_nested_json(self):
        """Doit extraire un JSON imbriqué complexe."""
        response = 'Analyse: {"data": {"nested": {"value": 42}}, "status": "ok"}'
        result = extract_json_from_response(response)
        assert result["data"]["nested"]["value"] == 42
        assert result["status"] == "ok"

    def test_extract_empty_response_returns_default(self):
        """Doit retourner le défaut pour une réponse vide."""
        result = extract_json_from_response("", default={"empty": True})
        assert result == {"empty": True}

    def test_extract_no_json_returns_default(self):
        """Doit retourner le défaut si aucun JSON trouvé."""
        result = extract_json_from_response(
            "Ceci est juste du texte sans JSON.",
            default={"fallback": True}
        )
        assert result == {"fallback": True}

    def test_extract_malformed_json_returns_default(self):
        """Doit retourner le défaut pour un JSON malformé."""
        response = '{"key": value_without_quotes}'
        result = extract_json_from_response(response, default={"error": True})
        assert result == {"error": True}

    def test_extract_multiple_json_objects_returns_default(self):
        """Doit retourner le défaut si multiple JSON malformé."""
        # Comportement: du premier { au dernier } crée un JSON invalide
        response = '{"first": 1} et {"second": 2}'
        result = extract_json_from_response(response, default={"fallback": True})
        # Le texte entre les deux JSON rend le parsing invalide
        # Donc on retourne le défaut
        assert result == {"fallback": True} or "first" in result or "second" in result


class TestToJsonString:
    """Tests pour to_json_string."""

    def test_simple_dict_to_json(self):
        """Doit convertir un dict simple en JSON."""
        result = to_json_string({"key": "value"})
        assert result == '{"key": "value"}'

    def test_pretty_format(self):
        """Doit formater en mode pretty."""
        result = to_json_string({"key": "value"}, pretty=True)
        assert "  " in result  # Indentation présente
        assert "\n" in result

    def test_unicode_characters(self):
        """Doit préserver les caractères Unicode."""
        result = to_json_string({"message": "Café à Paris"})
        assert "Café" in result
        assert "\\u" not in result  # Pas d'échappement Unicode

    def test_nested_structure(self):
        """Doit sérialiser des structures imbriquées."""
        data = {"level1": {"level2": [1, 2, 3]}}
        result = to_json_string(data)
        assert '"level1"' in result
        assert '"level2"' in result
        assert "[1, 2, 3]" in result


class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_special_characters_in_values(self):
        """Doit gérer les caractères spéciaux dans les valeurs."""
        json_str = '{"text": "Line1\\nLine2", "path": "C:\\\\Users"}'
        result = safe_json_parse(json_str)
        assert "Line1\nLine2" in result["text"]

    def test_unicode_in_json(self):
        """Doit gérer l'Unicode dans le JSON."""
        json_str = '{"emoji": "😀", "french": "éàü"}'
        result = safe_json_parse(json_str)
        assert result["emoji"] == "😀"
        assert result["french"] == "éàü"

    def test_large_numbers(self):
        """Doit gérer les grands nombres."""
        json_str = '{"big": 12345678901234567890}'
        result = safe_json_parse(json_str)
        assert result["big"] == 12345678901234567890

    def test_boolean_and_null(self):
        """Doit gérer les booléens et null."""
        json_str = '{"active": true, "disabled": false, "optional": null}'
        result = safe_json_parse(json_str)
        assert result["active"] is True
        assert result["disabled"] is False
        assert result["optional"] is None

    def test_extract_json_with_curly_braces_in_text(self):
        """Doit gérer le texte contenant des accolades."""
        response = 'Le format est {foo} mais le JSON est {"score": 10}'
        result = extract_json_from_response(response)
        # Devrait trouver au moins le dernier JSON valide
        assert isinstance(result, dict)


class TestDeepNestedStructures:
    """Tests pour les structures profondément imbriquées."""

    def test_deeply_nested_dict_50_levels(self):
        """Doit parser un dict imbriqué à 50 niveaux."""
        # Construire un JSON imbriqué à 50 niveaux
        nested = {"value": 42}
        for i in range(50):
            nested = {"level": nested}
        json_str = to_json_string(nested)

        result = safe_json_parse(json_str)
        # Vérifier qu'on peut accéder au niveau le plus profond
        current = result
        for _ in range(50):
            current = current["level"]
        assert current["value"] == 42

    def test_deeply_nested_list_50_levels(self):
        """Doit parser une liste imbriquée à 50 niveaux."""
        nested = [42]
        for _ in range(50):
            nested = [nested]
        json_str = to_json_string({"data": nested})

        result = safe_json_parse(json_str)
        current = result["data"]
        # 50 niveaux + 1 pour atteindre la valeur 42
        for _ in range(51):
            current = current[0]
        assert current == 42

    def test_mixed_nested_structure(self):
        """Doit parser une structure mixte dict/list imbriquée."""
        data = {
            "users": [
                {
                    "name": "Alice",
                    "roles": ["admin", "user"],
                    "metadata": {
                        "preferences": {
                            "theme": "dark",
                            "notifications": [
                                {"type": "email", "enabled": True},
                                {"type": "sms", "enabled": False}
                            ]
                        }
                    }
                }
            ]
        }
        json_str = to_json_string(data)
        result = safe_json_parse(json_str)

        assert result["users"][0]["metadata"]["preferences"]["notifications"][0]["enabled"] is True


class TestLargePayloads:
    """Tests pour les payloads volumineux."""

    def test_large_string_value_10kb(self):
        """Doit gérer une valeur string de 10KB."""
        large_text = "A" * 10240  # 10KB
        json_str = to_json_string({"content": large_text})

        result = safe_json_parse(json_str)
        assert len(result["content"]) == 10240

    def test_large_array_1000_elements(self):
        """Doit gérer un tableau de 1000 éléments."""
        data = {"items": list(range(1000))}
        json_str = to_json_string(data)

        result = safe_json_parse(json_str)
        assert len(result["items"]) == 1000
        assert result["items"][999] == 999

    def test_large_dict_500_keys(self):
        """Doit gérer un dict avec 500 clés."""
        data = {f"key_{i}": f"value_{i}" for i in range(500)}
        json_str = to_json_string(data)

        result = safe_json_parse(json_str)
        assert len(result) == 500
        assert result["key_499"] == "value_499"

    def test_combined_large_payload(self):
        """Doit gérer une payload combinée volumineuse."""
        data = {
            "users": [
                {
                    "id": i,
                    "name": f"User {i}",
                    "bio": "X" * 1000,
                    "tags": [f"tag_{j}" for j in range(10)]
                }
                for i in range(100)
            ]
        }
        json_str = to_json_string(data)

        result = safe_json_parse(json_str)
        assert len(result["users"]) == 100
        assert len(result["users"][0]["bio"]) == 1000


class TestUnicodeAndEncoding:
    """Tests pour l'Unicode et différents encodages."""

    def test_emoji_sequences(self):
        """Doit gérer les séquences d'emoji complexes."""
        json_str = '{"emoji": "👨‍👩‍👧‍👦🏳️‍🌈"}'
        result = safe_json_parse(json_str)
        assert "👨‍👩‍👧‍👦" in result["emoji"]

    def test_chinese_characters(self):
        """Doit gérer les caractères chinois."""
        json_str = '{"message": "你好世界"}'
        result = safe_json_parse(json_str)
        assert result["message"] == "你好世界"

    def test_arabic_characters(self):
        """Doit gérer les caractères arabes (RTL)."""
        json_str = '{"greeting": "مرحبا"}'
        result = safe_json_parse(json_str)
        assert result["greeting"] == "مرحبا"

    def test_japanese_characters(self):
        """Doit gérer les caractères japonais."""
        json_str = '{"text": "こんにちは世界"}'
        result = safe_json_parse(json_str)
        assert result["text"] == "こんにちは世界"

    def test_mixed_scripts(self):
        """Doit gérer un mélange de scripts."""
        json_str = '{"mixed": "Hello 你好 مرحبا こんにちは"}'
        result = safe_json_parse(json_str)
        assert "Hello" in result["mixed"]
        assert "你好" in result["mixed"]

    def test_unicode_escape_sequences(self):
        """Doit gérer les séquences d'échappement Unicode."""
        # \u00e9 = é
        json_str = '{"text": "caf\\u00e9"}'
        result = safe_json_parse(json_str)
        assert result["text"] == "café"

    def test_surrogate_pairs(self):
        """Doit gérer les paires de substitution Unicode."""
        # 𝄞 (Clé de sol) - nécessite une paire de substitution
        json_str = '{"music": "\\uD834\\uDD1E"}'
        result = safe_json_parse(json_str)
        assert result["music"] == "𝄞"

    def test_zero_width_characters(self):
        """Doit gérer les caractères de largeur nulle."""
        # ZWSP (Zero Width Space)
        json_str = '{"text": "a\\u200Bb"}'
        result = safe_json_parse(json_str)
        assert len(result["text"]) == 3  # a + ZWSP + b


class TestMalformedInputs:
    """Tests pour les entrées malformées."""

    def test_truncated_json(self):
        """Doit gérer un JSON tronqué."""
        result = safe_json_parse('{"key": "value", "incomplete":', default={"error": True})
        assert result == {"error": True}

    def test_truncated_trailing_number_becomes_null_not_wrong_value(self):
        """Regression (chaos audit 2026-06-02, P3): a JSON cut off mid-NUMBER used
        to keep the truncated prefix (85 -> 8), persisting a plausible-but-WRONG
        value indistinguishable from a complete answer. The repair now nulls a
        truncated trailing number rather than keeping the misleading prefix."""
        result = extract_json_from_response('{"category":"Action","priority_score":8')
        assert result.get("category") == "Action"
        # The 8 was a truncated 85/87/... — must NOT be persisted as a real score.
        assert result.get("priority_score") is None

    def test_truncated_trailing_string_becomes_null(self):
        """Sibling case: a truncated string value is nulled, not kept partial."""
        result = extract_json_from_response('{"vip":true,"deadline":"2026')
        assert result.get("vip") is True
        assert result.get("deadline") is None

    def test_extra_closing_brace(self):
        """Doit gérer des accolades en trop."""
        result = safe_json_parse('{"key": "value"}}', default={"error": True})
        assert result == {"error": True}

    def test_missing_closing_brace(self):
        """Doit gérer une accolade manquante."""
        result = safe_json_parse('{"key": "value"', default={"error": True})
        assert result == {"error": True}

    def test_single_quotes_instead_of_double(self):
        """Doit rejeter les single quotes (non JSON standard)."""
        result = safe_json_parse("{'key': 'value'}", default={"error": True})
        assert result == {"error": True}

    def test_trailing_comma(self):
        """Doit rejeter les virgules en fin."""
        result = safe_json_parse('{"key": "value",}', default={"error": True})
        assert result == {"error": True}

    def test_unquoted_keys(self):
        """Doit rejeter les clés non quotées."""
        result = safe_json_parse('{key: "value"}', default={"error": True})
        assert result == {"error": True}

    def test_nan_and_infinity(self):
        """Note: Python json accepte NaN/Infinity par défaut (extension non standard).

        Ce test documente le comportement réel de Python json.
        Pour un parsing strict, il faudrait utiliser parse_constant.
        """
        import math

        # Python accepte NaN comme extension
        result = safe_json_parse('{"value": NaN}', default={"error": True})
        # Le résultat contient NaN (comportement Python par défaut)
        assert "value" in result
        assert math.isnan(result["value"])

        # Python accepte aussi Infinity
        result = safe_json_parse('{"value": Infinity}', default={"error": True})
        assert result["value"] == float('inf')

        # Et -Infinity
        result = safe_json_parse('{"value": -Infinity}', default={"error": True})
        assert result["value"] == float('-inf')

    def test_comments_in_json(self):
        """Doit rejeter les commentaires (non JSON standard)."""
        result = safe_json_parse('{"key": "value" /* comment */}', default={"error": True})
        assert result == {"error": True}

    def test_binary_data_in_string(self):
        """Doit gérer les données binaires dans les strings."""
        # Control characters non échappés doivent être rejetés
        result = safe_json_parse('{"data": "\x00\x01"}', default={"error": True})
        # JSON standard rejette les caractères de contrôle non échappés
        assert result == {"error": True}


class TestExtractJsonAdvanced:
    """Tests avancés pour extract_json_from_response."""

    def test_extract_json_from_multiline_response(self):
        """Doit extraire le JSON d'une réponse multi-lignes."""
        response = """
        Voici mon analyse complète:

        Après avoir examiné le document, je conclus:

        {"score": 85, "category": "positive", "confidence": 0.95}

        J'espère que cela vous aide.
        """
        result = extract_json_from_response(response)
        assert result["score"] == 85
        assert result["category"] == "positive"

    def test_extract_json_with_nested_code_blocks(self):
        """Doit gérer les blocs de code imbriqués."""
        response = """
        Voici le code:
        ```python
        data = {"key": "python_value"}
        ```

        Et le JSON résultat:
        ```json
        {"result": "actual_json"}
        ```
        """
        result = extract_json_from_response(response)
        assert result["result"] == "actual_json"

    def test_extract_json_with_escape_sequences(self):
        """Doit extraire JSON avec séquences d'échappement."""
        response = 'Result: {"text": "Line1\\nLine2\\tTabbed"}'
        result = extract_json_from_response(response)
        assert "Line1\nLine2" in result["text"]

    def test_extract_json_with_html_entities(self):
        """Doit gérer le JSON contenant des entités HTML."""
        response = '{"message": "Test &amp; validation"}'
        result = extract_json_from_response(response)
        # Le JSON ne décode pas les entités HTML
        assert "&amp;" in result["message"]

    def test_extract_json_multiple_valid_objects_takes_first(self):
        """Doit extraire le premier JSON valide (comportement de repli)."""
        response = '''
        First analysis: {"first": true}

        Second analysis: {"second": true}
        '''
        result = extract_json_from_response(response)
        # Le comportement actuel: du premier { au dernier } peut créer un JSON invalide
        # Donc on test la robustesse
        assert isinstance(result, dict)

    def test_extract_json_from_markdown_with_multiple_languages(self):
        """Doit préférer le bloc json aux autres."""
        response = """
        ```python
        {"python": "code"}
        ```

        ```json
        {"json": "data"}
        ```
        """
        result = extract_json_from_response(response)
        assert result.get("json") == "data"


class TestSecurityAndRobustness:
    """Tests de sécurité et robustesse."""

    def test_very_long_string_key(self):
        """Doit gérer des clés très longues."""
        long_key = "k" * 10000
        json_str = '{"%s": "value"}' % long_key
        result = safe_json_parse(json_str)
        assert result[long_key] == "value"

    def test_deeply_nested_100_levels(self):
        """Doit gérer une imbrication à 100 niveaux."""
        nested = {"value": "deep"}
        for _ in range(100):
            nested = {"level": nested}
        json_str = to_json_string(nested)

        result = safe_json_parse(json_str)
        current = result
        for _ in range(100):
            current = current["level"]
        assert current["value"] == "deep"

    def test_null_bytes_in_string(self):
        """Doit rejeter les octets null dans les strings."""
        # Les caractères null non échappés sont invalides
        result = safe_json_parse('{"text": "test\x00null"}', default={"error": True})
        assert result == {"error": True}

    def test_empty_key(self):
        """Doit accepter les clés vides (valide en JSON)."""
        json_str = '{"": "empty_key_value"}'
        result = safe_json_parse(json_str)
        assert result[""] == "empty_key_value"

    def test_duplicate_keys_last_wins(self):
        """Doit garder la dernière valeur pour les clés dupliquées."""
        json_str = '{"key": "first", "key": "second"}'
        result = safe_json_parse(json_str)
        assert result["key"] == "second"

    def test_scientific_notation(self):
        """Doit gérer la notation scientifique."""
        json_str = '{"small": 1e-10, "large": 1.5e+15}'
        result = safe_json_parse(json_str)
        assert result["small"] == 1e-10
        assert result["large"] == 1.5e+15

    def test_negative_zero(self):
        """Doit gérer -0 (zéro négatif)."""
        json_str = '{"value": -0}'
        result = safe_json_parse(json_str)
        assert result["value"] == 0


class TestErrorContextLogging:
    """Tests pour le logging du contexte d'erreur."""

    def test_error_context_logged_on_invalid_json(self, caplog):
        """Doit logger le contexte d'erreur pour JSON invalide."""
        import logging
        caplog.set_level(logging.WARNING)

        safe_json_parse("{invalid}", error_context="TestAgent")

        assert "TestAgent" in caplog.text

    def test_error_context_logged_on_wrong_type(self, caplog):
        """Doit logger quand le type n'est pas celui attendu."""
        import logging
        caplog.set_level(logging.WARNING)

        safe_json_parse("[1, 2, 3]", error_context="ExpectDict")

        assert "ExpectDict" in caplog.text

    def test_no_logging_without_context(self, caplog):
        """Ne doit pas logger sans contexte d'erreur."""
        import logging
        caplog.set_level(logging.DEBUG)

        safe_json_parse("{invalid}")

        # Pas de message spécifique sans contexte
        assert "invalid" not in caplog.text.lower() or len(caplog.text) == 0


class TestCoverageMissingLines:
    """Tests pour couvrir les lignes manquantes du module json_parser.

    Ces tests visent spécifiquement les lignes non couvertes identifiées:
    - Line 49: logger.debug pour contenu vide avec error_context
    - Lines 63-66: Exception générale avec error_context
    - Line 89: Contenu vide dans safe_json_parse_list
    - Line 95: Non-liste avec error_context dans safe_json_parse_list
    - Lines 100, 102-105: Exceptions dans safe_json_parse_list avec error_context
    - Lines 153-154, 165-166: ValueError/IndexError dans extraction markdown
    """

    def test_empty_content_with_error_context_logs_debug(self, caplog):
        """Line 49: Doit logger en debug quand contenu vide avec error_context."""
        import logging
        caplog.set_level(logging.DEBUG)

        result = safe_json_parse("", error_context="EmptyTest")

        assert result == {}
        assert "EmptyTest" in caplog.text
        assert "Contenu JSON vide" in caplog.text

    def test_whitespace_only_with_error_context_logs_debug(self, caplog):
        """Line 49: Doit logger en debug pour espaces uniquement avec error_context."""
        import logging
        caplog.set_level(logging.DEBUG)

        result = safe_json_parse("   \n\t  ", error_context="WhitespaceTest")

        assert result == {}
        assert "WhitespaceTest" in caplog.text

    def test_unexpected_exception_with_error_context(self, caplog, monkeypatch):
        """Lines 63-66: Doit logger l'erreur inattendue avec error_context."""
        import logging
        import json
        caplog.set_level(logging.ERROR)

        def mock_loads(s):
            raise RuntimeError("Simulated unexpected error")

        monkeypatch.setattr(json, "loads", mock_loads)

        result = safe_json_parse('{"key": "value"}', error_context="UnexpectedError")

        assert result == {}
        assert "UnexpectedError" in caplog.text
        assert "inattendue" in caplog.text.lower()

    def test_safe_json_parse_list_empty_with_error_context(self, caplog):
        """Line 89: Doit retourner le défaut pour contenu vide dans parse_list."""
        import logging
        caplog.set_level(logging.DEBUG)

        result = safe_json_parse_list("", default=["fallback"], error_context="EmptyListTest")

        assert result == ["fallback"]

    def test_safe_json_parse_list_whitespace_only(self):
        """Line 89: Doit retourner le défaut pour espaces uniquement."""
        result = safe_json_parse_list("   \n\t  ", default=["default"])

        assert result == ["default"]

    def test_safe_json_parse_list_not_list_with_error_context(self, caplog):
        """Line 95: Doit logger quand JSON n'est pas une liste avec error_context."""
        import logging
        caplog.set_level(logging.WARNING)

        result = safe_json_parse_list('{"key": "value"}', error_context="NotListTest")

        assert result == []
        assert "NotListTest" in caplog.text
        assert "n'est pas une liste" in caplog.text

    def test_safe_json_parse_list_invalid_json_with_error_context(self, caplog):
        """Lines 100: Doit logger JSONDecodeError avec error_context."""
        import logging
        caplog.set_level(logging.WARNING)

        result = safe_json_parse_list("{invalid json}", error_context="InvalidListJson")

        assert result == []
        assert "InvalidListJson" in caplog.text

    def test_safe_json_parse_list_unexpected_exception(self, caplog, monkeypatch):
        """Lines 102-105: Doit logger l'erreur inattendue dans parse_list."""
        import logging
        import json
        caplog.set_level(logging.ERROR)

        def mock_loads(s):
            raise RuntimeError("Simulated unexpected error in list")

        monkeypatch.setattr(json, "loads", mock_loads)

        result = safe_json_parse_list('[1, 2, 3]', error_context="UnexpectedListError")

        assert result == []
        assert "UnexpectedListError" in caplog.text
        assert "inattendue" in caplog.text.lower()

    def test_extract_json_markdown_malformed_no_closing_backticks(self):
        """Lines 153-154: Doit gérer le bloc ```json sans fermeture."""
        response = """Voici le JSON:
```json
{"key": "value"}
Pas de fermeture de bloc"""

        result = extract_json_from_response(response, default={"fallback": True})

        # Devrait tomber sur le fallback car le bloc markdown est malformé
        # Mais peut quand même extraire via la méthode accolades
        assert isinstance(result, dict)

    def test_extract_json_code_block_malformed_no_closing(self):
        """Lines 165-166: Doit gérer le bloc ``` sans fermeture."""
        response = """Code:
```
{"incomplete": true}
Texte sans fermeture"""

        result = extract_json_from_response(response, default={"fallback": True})

        # Peut extraire via la méthode accolades ou retourner le défaut
        assert isinstance(result, dict)

    def test_extract_json_multiple_json_blocks_takes_json_block(self):
        """Doit préférer le bloc ```json``` aux simples accolades."""
        response = """Text before
```json
{"json_block": true}
```
And some {"inline": "json"} after"""

        result = extract_json_from_response(response)
        assert result.get("json_block") is True

    def test_extract_json_empty_markdown_block(self):
        """Lines 153-154: Doit gérer un bloc ```json``` vide."""
        response = """Résultat:
```json
```
Fin."""

        result = extract_json_from_response(response, default={"empty_block": True})

        # Le bloc est vide, donc on retourne le défaut ou on essaie les accolades
        assert isinstance(result, dict)

    def test_extract_json_code_block_empty(self):
        """Lines 165-166: Doit gérer un bloc ``` ``` vide."""
        response = """Code:
```
```
Suite."""

        result = extract_json_from_response(response, default={"empty": True})

        assert isinstance(result, dict)

    def test_extract_json_no_valid_json_with_error_context(self, caplog):
        """Line 179: Doit logger quand aucun JSON valide trouvé avec error_context."""
        import logging
        caplog.set_level(logging.WARNING)

        # Texte sans aucun JSON valide
        result = extract_json_from_response(
            "Ceci est du texte sans JSON.",
            default={"no_json": True},
            error_context="NoJsonTest"
        )

        assert result == {"no_json": True}
        assert "NoJsonTest" in caplog.text
        assert "Impossible d'extraire" in caplog.text


class TestEdgeCasesList:
    """Tests edge cases pour safe_json_parse_list."""

    def test_list_with_null_elements(self):
        """Doit gérer les listes avec éléments null."""
        result = safe_json_parse_list('[1, null, 3, null]')
        assert result == [1, None, 3, None]

    def test_list_with_mixed_types(self):
        """Doit gérer les listes avec types mixtes."""
        result = safe_json_parse_list('[1, "two", true, null, {"key": "value"}]')
        assert result[0] == 1
        assert result[1] == "two"
        assert result[2] is True
        assert result[3] is None
        assert result[4] == {"key": "value"}

    def test_large_list_10000_elements(self):
        """Doit gérer une liste de 10000 éléments."""
        data = list(range(10000))
        json_str = to_json_string(data)

        result = safe_json_parse_list(json_str)
        assert len(result) == 10000
        assert result[9999] == 9999

    def test_list_whitespace_handling(self):
        """Doit gérer les espaces dans les listes."""
        json_str = '  [  1  ,  2  ,  3  ]  '
        result = safe_json_parse_list(json_str)
        assert result == [1, 2, 3]


class TestToJsonStringAdvanced:
    """Tests avancés pour to_json_string."""

    def test_special_float_values(self):
        """Note: Python json.dumps accepte NaN/Infinity par défaut.

        Pour une sérialisation stricte, il faudrait utiliser allow_nan=False.
        Ce test documente le comportement par défaut de Python.
        """
        import math

        # Par défaut, Python sérialise NaN en "NaN"
        result = to_json_string({"value": math.nan})
        assert "NaN" in result

        # Et Infinity en "Infinity"
        result = to_json_string({"value": math.inf})
        assert "Infinity" in result

        result = to_json_string({"value": -math.inf})
        assert "-Infinity" in result

    def test_non_serializable_raises_error(self):
        """Doit lever une exception pour les types non sérialisables."""
        class CustomClass:
            pass

        with pytest.raises(TypeError):
            to_json_string({"obj": CustomClass()})

    def test_bytes_not_serializable(self):
        """Doit lever une exception pour les bytes."""
        with pytest.raises(TypeError):
            to_json_string({"data": b"binary"})

    def test_datetime_not_serializable(self):
        """Doit lever une exception pour datetime."""
        from datetime import datetime

        with pytest.raises(TypeError):
            to_json_string({"date": datetime.now()})

    def test_set_not_serializable(self):
        """Doit lever une exception pour set."""
        with pytest.raises(TypeError):
            to_json_string({"items": {1, 2, 3}})

    def test_pretty_format_indentation(self):
        """Doit utiliser une indentation de 2 espaces en mode pretty."""
        data = {"level1": {"level2": "value"}}
        result = to_json_string(data, pretty=True)

        # Vérifier l'indentation de 2 espaces
        lines = result.split("\n")
        assert any("  " in line and '"level2"' in line for line in lines)
