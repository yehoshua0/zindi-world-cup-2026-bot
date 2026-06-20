import logging
from typing import Protocol

from wc2026bot.state import MatchResult

log = logging.getLogger(__name__)


class FeedClient(Protocol):
    async def fetch(self) -> list[MatchResult]: ...


async def fetch_with_fallback(clients: list[FeedClient]) -> list[MatchResult]:
    for c in clients:
        try:
            res = await c.fetch()
            if res:
                return res
        except Exception as e:  # noqa: BLE001
            log.warning("feed %s failed: %s", type(c).__name__, e)
    return []
