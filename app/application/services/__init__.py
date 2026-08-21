"""Services de la couche application — orchestrent les use cases.

Cette couche dépend uniquement du domaine (entities + ports) et des DTOs
de l'application. Les implémentations concrètes (LLM, DB, etc.) sont
injectées par l'extérieur (typiquement résolues depuis le Container côté
API endpoints, pas importées ici).
"""
