import asyncio
import uuid
import time


class TokenBudgetExceeded(Exception):
    pass


class LoopDetected(Exception):
    pass


# Token Budget

class TokenBudget:
    def __init__(self, ceiling: int):
        self.ceiling = ceiling
        self._usage: dict[str, int] = {}

    def consume(self, session_id: str, tokens: int) -> None:
        current = self._usage.get(session_id, 0)
        if current + tokens > self.ceiling:
            raise TokenBudgetExceeded(
                f"Session {session_id} hit ceiling: "
                f"{current + tokens} > {self.ceiling}"
            )
        self._usage[session_id] = current + tokens

    def remaining(self, session_id: str) -> int:
        return self.ceiling - self._usage.get(session_id, 0)
