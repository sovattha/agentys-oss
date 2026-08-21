from __future__ import annotations

from itertools import count


class AccountPool:
    def __init__(self, *, pool_size: int, start: int = 1):
        self.pool_size = max(0, pool_size)
        self.start = start
        self._counter = count()

    def next_account_id(self) -> str | None:
        if self.pool_size <= 0:
            return None
        return account_id_for_index(next(self._counter), self.pool_size, self.start)


def account_id_for_index(index: int, pool_size: int, start: int = 1) -> str:
    return str(start + (index % pool_size))
