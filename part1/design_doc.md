# AgentSwarm Design Doc

## Architecture Diagram

```
╔══════════════════════════════════════════════════════════════════════════════════════════╗
║                                    AgentSwarm                                            ║
║                                                                                          ║
║  query: "what is our rate exposure given current credit risk and system health"          ║
║    │                                                                                     ║
║    ▼                                                                                     ║
║  ┌─────────────────────────────────────────────────────────────────────────────────┐     ║
║  │                              run()                                              │     ║
║  │   generate session_id (uuid) · create TokenBudget(ceiling) · create CycleGuard │     ║
║  └──────────────────────────────────────┬────────────────────────────────────────-┘     ║
║                                         │                                                ║
║                                         ▼                                                ║
║  ┌─────────────────────────────────────────────────────────────────────────────────┐     ║
║  │                           IntentClassifier                                      │     ║
║  │                                                                                 │     ║
║  │   prompt → lightweight model (stub: haiku, gpt-4o-mini, gemini flash etc)       │     ║
║  │   "which specialists should handle this query?"                                 │     ║
║  │                                                                                 │     ║
║  │   Specialists:                                                                  │     ║
║  │   markets channel         → equities, fixed_income, macro, alternatives         │     ║
║  │   risk_compliance channel → risk, regulatory, legal, compliance                 │     ║
║  │   technology channel      → infrastructure, data, security                      │     ║
║  │   operations channel      → fund_admin, reporting, client_services              │     ║
║  │                                                                                 │     ║
║  │   returns ["fixed_income", "data", "risk"]                                      │     ║
║  │   assign() maps each name → matching ResearchAgent by specialty                 │     ║
║  └──────────────────────────────────────┬────────────────────────────────────────-┘     ║
║                                         │                                                ║
║              ┌──────────────────────────┼────────────────────────┐                       ║
║              │                          │                         │                       ║
║              ▼                          ▼                         ▼                       ║
║                                                                                          ║
║   AGENTS                                              CHANNELS                           ║
║   ─────────────────────────────────────────────────────────────────────────────────      ║
║                                                                                          ║
║   ┌──────────────────────┐                                                               ║
║   │  fixed_income agent  │                                                               ║
║   │  specialty:          ├──── writes ──────────────►  ╔══════════════════════════╗     ║
║   │  fixed_income        │                              ║   markets channel        ║     ║
║   │  confidence: 0.9     │                              ║                          ║     ║
║   └──────────────────────┘                              ║  (fixed_income,sess,ts)  ║     ║
║                                                         ║  (data,        sess,ts)  ║     ║
║   ┌──────────────────────┐                              ║  (risk,        sess,ts)  ║     ║
║   │  data agent          ├──── writes ──────────────►   ║                          ║     ║
║   │  specialty: data     │                              ║  shared — all 3 agents   ║     ║
║   │  confidence: 0.7     │                              ║  can read each other     ║     ║
║   └──────────────────────┘                              ╚══════════════════════════╝     ║
║                                                                    │                     ║
║   ┌──────────────────────┐                                         │                     ║
║   │  risk agent          ├──── writes ──────────────►  ╔══════════════════════════╗     ║
║   │  specialty: risk     │                              ║  risk_compliance channel ║     ║
║   │  confidence: 0.95    ├──── writes ──────────────►  ╚══════════════════════════╝     ║
║   │                      │                                         │                     ║
║   │  cross-cutting agent │                                         │                     ║
║   │  writes to 3         ├──── writes ──────────────►  ╔══════════════════════════╗     ║
║   │  channels            │                              ║   technology channel     ║     ║
║   └──────────────────────┘                              ╚══════════════════════════╝     ║
║                                                                    │                     ║
║                                                      all channels read by vote           ║
║                                                                    │                     ║
║                                                                    ▼                     ║
║  ┌──────────────────────────────────────────────────────────────────────────────────┐    ║
║  │                      _majority_vote(session_id)                                  │    ║
║  │                                                                                  │    ║
║  │   reads ChannelContext.read_session(session_id)                                  │    ║
║  │   flattens all results across all channels into one list                         │    ║
║  │                                                                                  │    ║
║  │   score_tally:                                                                   │    ║
║  │   "approach_A" → 0.9 (fixed_income) + 0.95 (risk) = 1.85                        │    ║
║  │   "approach_B" → 0.7 (data)                        = 0.7                         │    ║
║  │                                                                                  │    ║
║  │   winner = max(score_tally) → "approach_A"  (1.85 vs 0.7)                        │    ║
║  └──────────────────────────────────────────────────────────────────────────────────┘    ║
║                                         │                                                ║
║                                         ▼                                                ║
║  ┌──────────────────────────────────────────────────────────────────────────────────┐    ║
║  │                               result                                             │    ║
║  │                                                                                  │    ║
║  │  session_id          →  "abc-123"                                                │    ║
║  │  final_conclusion    →  "approach_A"                                             │    ║
║  │  total_confidence    →  1.85                                                     │    ║
║  │  supporting_evidence →  [fixed_income agent, risk agent]                         │    ║
║  │  channel_history     →  {markets: [...], risk_compliance: [...],                 │    ║
║  │                          technology: [...]}                                      │    ║
║  │  channels_used       →  ["markets", "risk_compliance", "technology"]             │    ║
║  └──────────────────────────────────────────────────────────────────────────────────┘    ║
╚══════════════════════════════════════════════════════════════════════════════════════════╝
```

## Design Decision: One Design Decision Deliberately Considered and Rejected

### Rejected: Global Shared Context Dictionary

The original implementation stored agent context as a single mutable dictionary on the agent instance (`self.shared_context`). When multiple queries ran concurrently, all tasks were reading and writing to the same memory address at the same time and whichever query finished last (from random funcition stub) would overwrite every other query's context and thus losing all data hsitory for concurrent sessions (race condition).

My intial fix was to add a lock (`asyncio.Lock`) on every read and write to serialise access. This was deliberately rejected for two reasons:

1. A lock serialises concurrent writes so agents that should run in parallel now wait for each other which contradicts the benefit of using `asyncio.gather` in the first place.
2.  fixes the symptom (race condition) without fixing the cause (shared mutable context). The context still belongs to the agent instance, meaning the architecture still couples query state to agent identity.

The chosen approach instead was to move context ownership  out of the agent and into `ChannelContext`, keyed by `(agent_id, session_id, timestamp_ns)`. Each query owns its own session_id, so concurrent writes to the same channel never collide and they produce distinct keys. This way no lock is needed and there's still full concurrency.
