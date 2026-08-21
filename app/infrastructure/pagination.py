# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Pagination pour les grandes boîtes mail et listes de données.

Permet de traiter les emails par pages pour éviter les problèmes
de mémoire avec de grandes boîtes mail.

Usage:
    from app.infrastructure.pagination import Paginator, PageResult

    # Paginer une liste
    paginator = Paginator(items, page_size=50)
    for page in paginator:
        process(page.items)

    # Accéder à une page spécifique
    page = paginator.get_page(2)
"""

import math
from typing import TypeVar, Generic, List, Iterator, Callable, Optional, Any
from dataclasses import dataclass

T = TypeVar('T')


# ============================================================================
# RÉSULTAT DE PAGE
# ============================================================================

@dataclass
class PageResult(Generic[T]):
    """Résultat d'une page de données."""
    items: List[T]
    page_number: int
    page_size: int
    total_items: int
    total_pages: int

    @property
    def has_next(self) -> bool:
        """Vérifie s'il y a une page suivante."""
        return self.page_number < self.total_pages

    @property
    def has_previous(self) -> bool:
        """Vérifie s'il y a une page précédente."""
        return self.page_number > 1

    @property
    def start_index(self) -> int:
        """Index du premier élément de la page."""
        return (self.page_number - 1) * self.page_size

    @property
    def end_index(self) -> int:
        """Index du dernier élément de la page."""
        return min(self.start_index + self.page_size, self.total_items)

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour sérialisation."""
        return {
            "items": self.items,
            "page_number": self.page_number,
            "page_size": self.page_size,
            "total_items": self.total_items,
            "total_pages": self.total_pages,
            "has_next": self.has_next,
            "has_previous": self.has_previous,
        }


# ============================================================================
# PAGINATOR
# ============================================================================

class Paginator(Generic[T]):
    """
    Paginateur pour listes de données.

    Attributes:
        items: Liste complète des éléments
        page_size: Nombre d'éléments par page
    """

    def __init__(self, items: List[T], page_size: int = 50):
        self._items = items
        self.page_size = max(1, page_size)
        self._current_page = 1

    @property
    def total_items(self) -> int:
        """Nombre total d'éléments."""
        return len(self._items)

    @property
    def total_pages(self) -> int:
        """Nombre total de pages."""
        return max(1, math.ceil(self.total_items / self.page_size))

    def get_page(self, page_number: int) -> PageResult[T]:
        """
        Récupère une page spécifique.

        Args:
            page_number: Numéro de page (1-indexed)

        Returns:
            PageResult avec les éléments de la page
        """
        # Valider le numéro de page
        page_number = max(1, min(page_number, self.total_pages))

        start = (page_number - 1) * self.page_size
        end = start + self.page_size
        items = self._items[start:end]

        return PageResult(
            items=items,
            page_number=page_number,
            page_size=self.page_size,
            total_items=self.total_items,
            total_pages=self.total_pages,
        )

    def __iter__(self) -> Iterator[PageResult[T]]:
        """Itère sur toutes les pages."""
        for page_num in range(1, self.total_pages + 1):
            yield self.get_page(page_num)

    def __len__(self) -> int:
        """Retourne le nombre de pages."""
        return self.total_pages


# ============================================================================
# CURSOR PAGINATOR
# ============================================================================

@dataclass
class CursorPageResult(Generic[T]):
    """Résultat de pagination par curseur."""
    items: List[T]
    next_cursor: Optional[str]
    previous_cursor: Optional[str]
    has_more: bool

    def to_dict(self) -> dict:
        """Convertit en dictionnaire."""
        return {
            "items": self.items,
            "next_cursor": self.next_cursor,
            "previous_cursor": self.previous_cursor,
            "has_more": self.has_more,
        }


class CursorPaginator(Generic[T]):
    """
    Paginateur basé sur curseur pour les APIs.

    Utile pour la pagination des emails depuis Gmail/Outlook API
    qui utilisent des tokens de pagination.
    """

    def __init__(
        self,
        fetch_func: Callable[[Optional[str], int], tuple],
        page_size: int = 50
    ):
        """
        Args:
            fetch_func: Fonction (cursor, limit) -> (items, next_cursor)
            page_size: Nombre d'éléments par page
        """
        self._fetch_func = fetch_func
        self.page_size = page_size

    def get_page(self, cursor: Optional[str] = None) -> CursorPageResult[T]:
        """
        Récupère une page à partir du curseur.

        Args:
            cursor: Curseur de pagination (None pour la première page)

        Returns:
            CursorPageResult avec les éléments
        """
        items, next_cursor = self._fetch_func(cursor, self.page_size)

        return CursorPageResult(
            items=items,
            next_cursor=next_cursor,
            previous_cursor=cursor,
            has_more=next_cursor is not None,
        )

    def __iter__(self) -> Iterator[CursorPageResult[T]]:
        """Itère sur toutes les pages."""
        cursor = None
        while True:
            result = self.get_page(cursor)
            yield result
            if not result.has_more:
                break
            cursor = result.next_cursor


# ============================================================================
# EMAIL PAGINATOR
# ============================================================================

class EmailPaginator:
    """
    Paginateur spécialisé pour les emails.

    Gère la pagination des emails depuis les providers
    avec support pour les filtres et le tri.
    """

    def __init__(
        self,
        provider,
        page_size: int = 50,
        filter_func: Optional[Callable[[Any], bool]] = None
    ):
        """
        Args:
            provider: EmailProvider instance
            page_size: Nombre d'emails par page
            filter_func: Fonction de filtrage optionnelle
        """
        self.provider = provider
        self.page_size = page_size
        self.filter_func = filter_func
        self._page_token: Optional[str] = None
        self._current_page = 0

    def fetch_page(self, page_token: Optional[str] = None) -> CursorPageResult:
        """Récupère une page d'emails."""
        # Cette méthode doit être implémentée par les providers
        # Pour l'instant, on retourne une page vide
        emails, next_token = self.provider.fetch_emails_page(
            page_token=page_token,
            max_results=self.page_size
        )

        # Appliquer le filtre si présent
        if self.filter_func:
            emails = [e for e in emails if self.filter_func(e)]

        return CursorPageResult(
            items=emails,
            next_cursor=next_token,
            previous_cursor=page_token,
            has_more=next_token is not None,
        )

    def __iter__(self):
        """Itère sur toutes les pages d'emails."""
        page_token = None
        while True:
            result = self.fetch_page(page_token)
            yield result
            if not result.has_more:
                break
            page_token = result.next_cursor


# ============================================================================
# HELPERS
# ============================================================================

def paginate(items: List[T], page: int = 1, page_size: int = 50) -> PageResult[T]:
    """
    Helper pour paginer rapidement une liste.

    Args:
        items: Liste à paginer
        page: Numéro de page (1-indexed)
        page_size: Taille de page

    Returns:
        PageResult
    """
    paginator = Paginator(items, page_size)
    return paginator.get_page(page)


def chunked(items: List[T], chunk_size: int) -> Iterator[List[T]]:
    """
    Divise une liste en chunks.

    Args:
        items: Liste à diviser
        chunk_size: Taille des chunks

    Yields:
        Chunks de la liste
    """
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]
