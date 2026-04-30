import asyncio
import uuid
import time


# custom exceptions so we can catch these specificaly in the orchestrator
class TokenBudgetExceeded(Exception):
    pass


class LoopDetected(Exception):
    pass


# Token Budget
class TokenBudget:
    def __init__(self, ceiling: int):
        self.ceiling = ceiling
        self._usage: dict[str, int] = {}  # tracks usage per session

    def consume(self, session_id: str, tokens: int) -> None:
        current = self._usage.get(session_id, 0)
        # check BEFORE spending, not after
        if current + tokens > self.ceiling:
            raise TokenBudgetExceeded(
                f"Session {session_id} hit ceiling: "
                f"{current + tokens} > {self.ceiling}"
            )
        self._usage[session_id] = current + tokens

    def remaining(self, session_id: str) -> int:
        return self.ceiling - self._usage.get(session_id, 0)


# Cycle Guard
# uses DFS to check if adding a new edge would close a loop
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
        # iterative DFS - if we can get from callee back to caller, its a cycle
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
# channels are created on the fly based on intent, not predefined
class ChannelContext:
    def __init__(self):
        self._channels: dict[str, dict[tuple, dict]] = {}

    def write(self, channel: str, agent_id: str, session_id: str, data: dict) -> None:
        if channel not in self._channels:
            self._channels[channel] = {}  # create channel on first write
        key = (agent_id, session_id, time.time_ns())  # composite key for full history
        self._channels[channel][key] = data

    def read_channel(self, channel: str, session_id: str) -> list[dict]:
        entries = [
            {"key": k, "data": v}
            for k, v in self._channels.get(channel, {}).items()
            if k[1] == session_id
        ]
        return sorted(entries, key=lambda e: e["key"][2])  # sort chronologicaly

    def read_session(self, session_id: str) -> dict[str, list]:
        return {
            ch: self.read_channel(ch, session_id)
            for ch in self._channels
        }

    @property
    def active_channels(self) -> list[str]:
        return list(self._channels.keys())


# Intent Classifier
# asks a lightweight model to route the query directly to a specialist by name
class IntentClassifier:

    async def _llm_classify(self, query: str) -> list[str]:
        # stub, in production a fast lightweight model would read the prompt
        # and return specialist names directly
        _prompt = f"""You are a routing assistant for a global investment office.
                        Given a user query, return the relevant research specialist(s) from the list below.

                        Specialists:
                        - macro: global markets, interest rates, inflation, geopolitical risk, central banks
                        - equities: public markets, stock research, sector analysis, earnings, valuation
                        - alternatives: hedge funds, private equity, real assets, co-investments, illiquid
                        # add risk, allocation, esg etc as needed

                        Query: {query}

                        Return only a comma separated list of specialist names. If nothing fits return: general"""

        await asyncio.sleep(0.05)  # simulates the routing model inference

        # stub - real model would return something like "macro, equities"
        return ["macro"]

    async def assign(self, query: str, agents: list) -> dict[str, list]:
        intents = await self._llm_classify(query)
        assignments: dict[str, list] = {}

        for intent in intents:
            matched_agents = [a for a in agents if a.specialty == intent]
            if matched_agents:
                assignments[intent] = matched_agents

        # fallback if nothing matched
        if not assignments:
            fallback = [a for a in agents if a.specialty == "general"] or agents
            assignments["general"] = fallback

        return assignments


# Research Agent
class ResearchAgent:
    def __init__(self, agent_id: str, specialty: str, confidence_weight: float):
        self.agent_id = agent_id
        self.specialty = specialty
        self.confidence_weight = confidence_weight

    # deterministic stub conclusions so voting actually groups properly
    _SPECIALTY_CONCLUSIONS = {
        "macro":        "approach_A",
        "equities":     "approach_A",
        "alternatives": "approach_B",
        # add risk, allocation, esg etc as needed
        "general":      "needs_more_info",
    }

    async def research(
        self,
        query: str,
        channels: list[str],
        session_id: str,
        budget: TokenBudget,
        channel_ctx: ChannelContext,
    ) -> dict:
        estimated_tokens = len(query.split()) * 10
        budget.consume(session_id, estimated_tokens)

        await asyncio.sleep(0.1)  # stub - would be a real LLM call in production

        result = {
            "agent_id":    self.agent_id,
            "session_id":  session_id,
            "channels":    channels,
            "timestamp":   time.time_ns(),
            "conclusion":  self._SPECIALTY_CONCLUSIONS.get(self.specialty, "needs_more_info"),
            "confidence":  self.confidence_weight,
            "reasoning":   f"Agent {self.agent_id} analysed: {query}",
            "tokens_used": estimated_tokens,
        }

        # write to every channel this agent belongs to
        for channel in channels:
            channel_ctx.write(channel, self.agent_id, session_id, result)
        return result


# Orchestrator
class AgentSwarm:
    def __init__(self, agents: list, token_ceiling: int = 10_000):
        self.agents = agents
        self.token_ceiling = token_ceiling
        self._classifier = IntentClassifier()
        self._channel_ctx = ChannelContext()

    async def run(self, query: str) -> dict:
        session_id = str(uuid.uuid4())  # fresh session per query, no shared state
        budget = TokenBudget(self.token_ceiling)
        guard = CycleGuard()
        return await self._run_session(query, session_id, budget, guard)

    async def _run_session(
        self,
        query: str,
        session_id: str,
        budget: TokenBudget,
        guard: CycleGuard,
    ) -> dict:
        assignments = await self._classifier.assign(query, self.agents)

        # build a map of agent_id -> all channels it appears in
        agent_channels: dict[str, list[str]] = {}
        for channel, agents in assignments.items():
            for agent in agents:
                if agent.agent_id not in agent_channels:
                    agent_channels[agent.agent_id] = []
                agent_channels[agent.agent_id].append(channel)

        # dispatch each agent once with its full list of channels
        seen = set()
        tasks = []
        for agents in assignments.values():
            for agent in agents:
                if agent.agent_id in seen:
                    continue
                seen.add(agent.agent_id)
                guard.register("orchestrator", agent.agent_id)
                tasks.append(
                    agent.research(query, agent_channels[agent.agent_id], session_id, budget, self._channel_ctx)
                )

        await asyncio.gather(*tasks, return_exceptions=True)

        # vote reads from channel context, not agent returns directly
        return self._majority_vote(session_id)

    def _majority_vote(self, session_id: str) -> dict:
        # read all results written to channels during this session
        channel_history = self._channel_ctx.read_session(session_id)

        # flatten across all channels into one list
        all_results = [
            entry["data"]
            for entries in channel_history.values()
            for entry in entries
        ]

        if not all_results:
            return {"error": "No valid results", "session_id": session_id}

        score_tally:  dict[str, float] = {}
        evidence_log: dict[str, list]  = {}

        for result in all_results:
            conclusion = result.get("conclusion")
            weight     = result.get("confidence", 1.0)

            if conclusion not in score_tally:
                score_tally[conclusion]  = 0.0
                evidence_log[conclusion] = []

            # stack weights so high confidence agents can outvote multiple weaker ones
            score_tally[conclusion] += weight
            evidence_log[conclusion].append({
                "agent_id":         result.get("agent_id"),
                "channel":          result.get("channel"),
                "confidence_given": weight,
                "reasoning":        result.get("reasoning"),
            })

        winner = max(score_tally, key=score_tally.get)

        return {
            "session_id":          session_id,
            "final_conclusion":    winner,
            "total_confidence":    score_tally[winner],
            "all_scores":          score_tally,
            "supporting_evidence": evidence_log[winner],
            "channel_history":     channel_history,
            "channels_used":       self._channel_ctx.active_channels,
        }

    async def run_pipeline(self, queries: list[str]) -> list[dict]:
        return await asyncio.gather(*[self.run(q) for q in queries])
