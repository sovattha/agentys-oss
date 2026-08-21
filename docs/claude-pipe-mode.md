# Claude Code en mode pipe (`claude -p`)

Pour utiliser `claude -p` comme LLM backend (subprocess), isoler complètement l'environnement :

1. **Filtrer `CLAUDE*` env vars** : évite le check de session imbriquée
2. **Filtrer `ANTHROPIC_API_KEY`** : force l'auth OAuth subscription
3. **`--tools ""`** : désactive tous les outils internes
4. **`--strict-mcp-config`** : ignore la config MCP utilisateur
5. **`--max-turns 1`** : un seul aller-retour API
6. **`cwd="/tmp"`** : répertoire neutre pour éviter le chargement de CLAUDE.md

```python
cmd = [
    self._claude_path, "-p",
    "--output-format", "json",
    "--model", self._model,
    "--max-turns", "1",
    "--tools", "",
    "--strict-mcp-config",
    "--system-prompt", system,
]
env = {
    k: v for k, v in os.environ.items()
    if not k.startswith("CLAUDE") and k != "ANTHROPIC_API_KEY"
}
```

## Flags utiles complémentaires

- `--max-budget-usd <N>` : cap dépense (PAS `--max-tokens` qui n'existe pas)
- `--bare` : output sans formatage
- `--model sonnet` : 5x moins cher qu'Opus pour tâches UX/test

## Multi-compte — Résolution des IDs

- Le frontend envoie des **hash IDs** (ex: `f9057edfed0d4574`), pas des IDs numériques DB
- `_resolve_db_account_id` dans `app/api/onboarding.py` résout : email → int ID → hash ID (via AccountManager)
- Toujours tester avec les vrais hash IDs du frontend, pas les IDs DB bruts
