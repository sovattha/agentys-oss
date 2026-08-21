# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour le module pagination."""

from app.infrastructure.pagination import (
    PageResult,
    Paginator,
    CursorPageResult,
    CursorPaginator,
    EmailPaginator,
    paginate,
    chunked,
)


# ============================================================================
# TESTS — PageResult
# ============================================================================

class TestPageResult:
    def test_has_next_true(self):
        pr = PageResult(items=[1, 2], page_number=1, page_size=2, total_items=5, total_pages=3)
        assert pr.has_next is True

    def test_has_next_false_on_last_page(self):
        pr = PageResult(items=[5], page_number=3, page_size=2, total_items=5, total_pages=3)
        assert pr.has_next is False

    def test_has_previous_false_on_first_page(self):
        pr = PageResult(items=[1, 2], page_number=1, page_size=2, total_items=5, total_pages=3)
        assert pr.has_previous is False

    def test_has_previous_true(self):
        pr = PageResult(items=[3, 4], page_number=2, page_size=2, total_items=5, total_pages=3)
        assert pr.has_previous is True

    def test_start_index(self):
        pr = PageResult(items=[], page_number=3, page_size=10, total_items=25, total_pages=3)
        assert pr.start_index == 20

    def test_end_index(self):
        pr = PageResult(items=[], page_number=3, page_size=10, total_items=25, total_pages=3)
        assert pr.end_index == 25

    def test_end_index_last_page_partial(self):
        pr = PageResult(items=[], page_number=2, page_size=10, total_items=15, total_pages=2)
        assert pr.end_index == 15

    def test_to_dict(self):
        pr = PageResult(items=[1, 2], page_number=1, page_size=2, total_items=4, total_pages=2)
        d = pr.to_dict()
        assert d["page_number"] == 1
        assert d["has_next"] is True
        assert d["has_previous"] is False
        assert d["items"] == [1, 2]


# ============================================================================
# TESTS — Paginator
# ============================================================================

class TestPaginator:
    def test_total_items(self):
        p = Paginator(list(range(25)), page_size=10)
        assert p.total_items == 25

    def test_total_pages(self):
        p = Paginator(list(range(25)), page_size=10)
        assert p.total_pages == 3

    def test_total_pages_exact_division(self):
        p = Paginator(list(range(20)), page_size=10)
        assert p.total_pages == 2

    def test_total_pages_empty(self):
        p = Paginator([], page_size=10)
        assert p.total_pages == 1  # max(1, ceil(0/10))

    def test_page_size_minimum_is_1(self):
        p = Paginator([1, 2, 3], page_size=0)
        assert p.page_size == 1

    def test_page_size_negative_clamped(self):
        p = Paginator([1, 2, 3], page_size=-5)
        assert p.page_size == 1

    def test_get_page_first(self):
        p = Paginator(list(range(10)), page_size=3)
        page = p.get_page(1)
        assert page.items == [0, 1, 2]
        assert page.page_number == 1

    def test_get_page_last(self):
        p = Paginator(list(range(10)), page_size=3)
        page = p.get_page(4)  # items 9
        assert page.items == [9]
        assert page.page_number == 4

    def test_get_page_out_of_range_high(self):
        p = Paginator(list(range(10)), page_size=3)
        page = p.get_page(100)
        # Devrait être clampé à la dernière page
        assert page.page_number == 4

    def test_get_page_out_of_range_low(self):
        p = Paginator(list(range(10)), page_size=3)
        page = p.get_page(0)
        assert page.page_number == 1

    def test_iteration(self):
        p = Paginator(list(range(7)), page_size=3)
        pages = list(p)
        assert len(pages) == 3
        assert pages[0].items == [0, 1, 2]
        assert pages[1].items == [3, 4, 5]
        assert pages[2].items == [6]

    def test_len(self):
        p = Paginator(list(range(7)), page_size=3)
        assert len(p) == 3


# ============================================================================
# TESTS — CursorPageResult
# ============================================================================

class TestCursorPageResult:
    def test_to_dict(self):
        cr = CursorPageResult(items=["a", "b"], next_cursor="abc123", previous_cursor=None, has_more=True)
        d = cr.to_dict()
        assert d["items"] == ["a", "b"]
        assert d["next_cursor"] == "abc123"
        assert d["has_more"] is True

    def test_no_more(self):
        cr = CursorPageResult(items=["z"], next_cursor=None, previous_cursor="xyz", has_more=False)
        assert cr.has_more is False


# ============================================================================
# TESTS — CursorPaginator
# ============================================================================

class TestCursorPaginator:
    def test_first_page(self):
        def fetch(cursor, limit):
            if cursor is None:
                return (["a", "b"], "cursor1")
            return (["c"], None)

        cp = CursorPaginator(fetch_func=fetch, page_size=2)
        page = cp.get_page()
        assert page.items == ["a", "b"]
        assert page.next_cursor == "cursor1"
        assert page.has_more is True

    def test_iteration_exhausts_pages(self):
        call_count = 0

        def fetch(cursor, limit):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ([1, 2], "c1")
            elif call_count == 2:
                return ([3, 4], "c2")
            else:
                return ([5], None)

        cp = CursorPaginator(fetch_func=fetch, page_size=2)
        all_items = []
        for page in cp:
            all_items.extend(page.items)
        assert all_items == [1, 2, 3, 4, 5]

    def test_single_page(self):
        def fetch(cursor, limit):
            return (["only"], None)

        cp = CursorPaginator(fetch_func=fetch, page_size=10)
        pages = list(cp)
        assert len(pages) == 1
        assert pages[0].has_more is False


# ============================================================================
# TESTS — EmailPaginator
# ============================================================================

class TestEmailPaginator:
    def test_fetch_page(self):
        provider = type("MockProvider", (), {
            "fetch_emails_page": lambda self, page_token=None, max_results=50: (
                [{"id": "1"}, {"id": "2"}], "next_token"
            )
        })()
        ep = EmailPaginator(provider=provider, page_size=10)
        page = ep.fetch_page()
        assert len(page.items) == 2
        assert page.has_more is True

    def test_filter_func(self):
        provider = type("MockProvider", (), {
            "fetch_emails_page": lambda self, page_token=None, max_results=50: (
                [{"id": "1", "spam": True}, {"id": "2", "spam": False}], None
            )
        })()
        ep = EmailPaginator(
            provider=provider, page_size=10,
            filter_func=lambda e: not e.get("spam"),
        )
        page = ep.fetch_page()
        assert len(page.items) == 1
        assert page.items[0]["id"] == "2"

    def test_iteration(self):
        call_count = 0

        class MockProvider:
            def fetch_emails_page(self, page_token=None, max_results=50):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return ([{"id": "a"}], "tok")
                return ([{"id": "b"}], None)

        ep = EmailPaginator(provider=MockProvider(), page_size=5)
        pages = list(ep)
        assert len(pages) == 2


# ============================================================================
# TESTS — Helper paginate()
# ============================================================================

class TestPaginateHelper:
    def test_basic(self):
        result = paginate(list(range(20)), page=2, page_size=5)
        assert result.items == [5, 6, 7, 8, 9]
        assert result.page_number == 2

    def test_first_page_default(self):
        result = paginate(list(range(10)))
        assert result.page_number == 1


# ============================================================================
# TESTS — Helper chunked()
# ============================================================================

class TestChunked:
    def test_even_split(self):
        chunks = list(chunked([1, 2, 3, 4], 2))
        assert chunks == [[1, 2], [3, 4]]

    def test_uneven_split(self):
        chunks = list(chunked([1, 2, 3, 4, 5], 2))
        assert chunks == [[1, 2], [3, 4], [5]]

    def test_empty_list(self):
        chunks = list(chunked([], 5))
        assert chunks == []

    def test_chunk_size_larger_than_list(self):
        chunks = list(chunked([1, 2], 10))
        assert chunks == [[1, 2]]
