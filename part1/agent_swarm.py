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


# Cycle Guard

class CycleGuard:
    def __init__(self):
        self._chain: dict[str, set] = {}

    def register(self, caller: str, callee: str) -> None:
        if self._can_reach(callee, caller):
            raise LoopDetected(
                f"Cycle detected: {callee} already leads back to {caller}"
            )
        if caller not in self._chain:
            self._chain[caller] = set()
        self._chain[caller].add(callee)

    def _can_reach(self, start: str, target: str) -> bool:
        visited = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node == target:
                return True
            if node in visited:
                continue
            visited.add(node)
            stack.extend(self._chain.get(node, set()))
        return False
