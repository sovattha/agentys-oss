"""DTOs partagés entre la couche application et l'extérieur.

Les DTOs ici sont des structures de transport — pas d'entités du domaine.
Ils sont utilisés notamment par DraftService (Phase 2 du pipeline unifié)
pour normaliser les inputs (DraftContext) et outputs (DraftServiceResult)
des paths reply et compose.
"""
