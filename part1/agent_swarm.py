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


# Channel Context

class ChannelContext:
    def __init__(self):
        self._channels: dict[str, dict[tuple, dict]] = {}

    def write(self, channel: str, agent_id: str, session_id: str, data: dict) -> None:
        if channel not in self._channels:
            self._channels[channel] = {}
        key = (agent_id, session_id, time.time_ns())
        self._channels[channel][key] = data

    def read_channel(self, channel: str, session_id: str) -> list[dict]:
        entries = [
            {"key": k, "data": v}
            for k, v in self._channels.get(channel, {}).items()
            if k[1] == session_id
        ]
        return sorted(entries, key=lambda e: e["key"][2])

    def read_session(self, session_id: str) -> dict[str, list]:
        return {
            ch: self.read_channel(ch, session_id)
            for ch in self._channels
        }

    @property
    def active_channels(self) -> list[str]:
        return list(self._channels.keys())


# Intent Classifier

class IntentClassifier:
    _KEYWORDS: dict[str, list[str]] = {
        "security":  ["auth", "token", "permission", "encrypt", "xss", "sql", "vulnerability"],
        "frontend":  ["ui", "css", "html", "react", "component", "layout", "design"],
        "backend":   ["api", "server", "database", "endpoint", "rest", "graphql"],
        "data":      ["query", "analytics", "pipeline", "etl", "schema", "transform"],
        "general":   [],
    }

    def classify(self, query: str) -> list[str]:
        q = query.lower()
        matched = [
            intent for intent, kws in self._KEYWORDS.items()
            if kws and any(kw in q for kw in kws)
        ]
        return matched if matched else ["general"]

    def assign(self, query: str, agents: list) -> dict[str, list]:
        intents = self.classify(query)
        assignments: dict[str, list] = {}

        for intent in intents:
            matched_agents = [a for a in agents if a.specialty == intent]
            if matched_agents:
                assignments[intent] = matched_agents

        if not assignments:
            fallback = [a for a in agents if a.specialty == "general"] or agents
            assignments["general"] = fallback

        return assignments
