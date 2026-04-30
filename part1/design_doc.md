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

## Design Decision: Rejected Global Shared Context Dictionary

The original implementation stored agent context as a single mutable dictionary on the agent instance (`self.shared_context`). When multiple queries ran concurrently, all tasks were reading and writing to the same memory address at the same time and whichever query finished last (from random funcition stub) would overwrite every other query's context, losing all data hsitory for concurrent sessions. Classic race condition.

My intial fix was to add a lock (`asyncio.Lock`) on every read and write to serialise access. Rejected this for two reasons:

1. A lock serialises concurrent writes so agents that should run in parallel now wait for each other, which contradicts the benefit of using `asyncio.gather` in the first place.
2. It fixes the symptom (race condition) without fixing the cause (shared mutable context). The context still belongs to the agent instance, meaning the architecture still couples query state to agent identity.

Chose instead to move context ownership out of the agent and into `ChannelContext`, keyed by `(agent_id, session_id, timestamp_ns)`. Each query owns its own session_id, so concurrent writes to the same channel never collide, they produce distinct keys. No lock needed and full concurrency preserved.

---

## Part 2a, Failure Categorisation

**Query 1, Retrieval Miss.** The retriever pulled chunks about Q2 2023 performance, fund inception, fee structure and management charges, benchmark compare and redemption/liquidity policy, none of which contain Q3 2023 NAV data. The correct chunk simply doesn't exist in the retrieved set. The model seems to have hallucinated and given an incorrect yet specific figure ($2.4 billion, 3.2%) because it had no grounding to work from (which it shouldn't do, could be an issue with the system prompt). This is retrieval miss because the right document wasn't fetched.

**Query 2, Ranking Failure.** The correct chunk did exist in the indexed records but it was ranked 6th, however TOP_K=5 so the records output was cut off before it could be retrieved. What was returned instead was a general redemption gate policy chunk (Chunk C) which contained a similar but incorrect figure (15% instead of 10%). The model used the wrong chunk because the right one was just outside the retrieval window. Redemption policy sits with fund or institutional mandates and although liquidity terms for APs may be included in the same documentation, segmenting with metadata for sections in mandates would help.

**Query 3, Context Pollution.** The retriever actually got the right chunk as Chunk B contains the correct answer, but Chunk E (comparable fund, key persons) was also retrieved and it contains key person data for a different strategy. The model conflated the two, mixing names from both chunks into a single answer. The retrieval didn't miss but it returned excess noise from Chunk E which distorted the response.

---

## Part 2c, Targeted Retrieval Improvement

The dominant failure mode is `ranking_failure`. It directly caused the error in Query 2 and also partially contributed to Query 3, where Chunk E (a different strategy) being ranked highly enough to enter Top-K is the same underlying problem.

Proposed fix: add a metadata pre-filter against a reference table linked by ID to the retrieval table, before retrieval. Before running the vector search, extract the strategy name from the query ("Alternative Credit", "Real Assets" etc.) and filter the candidate pool to only chunks tagged with that strategy, or with a reference column in a table containing the required value or code. The retriever then ranks within a clean set rather than across the entire dataset.

The reason this is specific to ranking failure is because the problem isn't embedding quality. "Redemption gate policy (general)" is semantically close to "liquidity terms for Alternative Credit" so the model ranks it highly regardless. Filtering by strategy metadata removes it from contention before ranking even runs so the correct strategy-related chunk rises to the top.

How to measure: `ranking_failure` rate in `failure_category` should drop, and running the same three queries after the fix should show Q2 no longer returns `ranking_failure`. `_quantile_correlation` should move toward 0 or negative (if scores go down as rank goes up that's a good ranker). Relevant chunks should now be concentrated in the top quantiles, not the lower ones. `context_precision` should also increase for both queries as the retrieved set becomes cleaner. A successful fix would show `failure_category` returning `ok` for both queries on the golden dataset.

---

## Part 3a, Bug Identification

The bug is a check-then-act flaw spanning these lines in the `dispatch` method:

```python
if self.tokens_used >= self.token_budget:
    raise RuntimeError('Token budget exceeded')

try:
    result = await fn()
    tokens = result.get('tokens_used', 0)
    self.tokens_used += tokens
```

The check and the update are separated by `await fn()`.

asyncio is single-threaded so there are no memory-level race conditions from parallel writes, but it uses cooperative multitasking so every `await` yields control back to the event loop, pausing the current task to let another run. Task A checks the budget, sees theres still some, hits `await fn()`. While A is suspended waiting for the LLM, Task B enters, checks the same `tokens_used` (A hasn't updated it yet), also sees budget still available, so proceeds. This repeats up to `max_concurrent` limit.

Triggers under high concurrent load when the remaining budget is smaller than the combined token usage of all in-flight requests. e.g. budget is 10,000, current usage is 9,500, code allows 10 concurrent tasks. All 10 check the budget before any one of them updates it, all pass, each uses 500 tokens, total `tokens_used` ends up at 14,500.

---

## Part 4, Advanced AI Reasoning

### (a) Theoretical Accuracy

Each agent is an independant Bernoulli trial with probability of success p = 0.92 and probability of failure q = 1 - p = 0.08. With n = 8 trials the number of successes X follows a binomial distribution, X ~ B(8, 0.92).

A simple majority requires at least 5 successes out of 8 trials so:

P(correct) = P(X ≥ 5) = sum from k=5 to 8 of C(8,k) × p^k × q^(n-k)

Where C(8, k) = 8! / (k!(8-k)!) is the number of ways to get k successes in n = 8 trials.

For k = 5 successes:
P(X = 5) = 56 × 0.92^5 × 0.08^3 = 56 × 0.65908 × 0.000512 = 0.01890

For k = 6 successes:
P(X = 6) = 28 × 0.92^6 × 0.08^2 = 28 × 0.60636 × 0.0064 = 0.10866

For k = 7 successes:
P(X = 7) = 8 × 0.92^7 × 0.08 = 8 × 0.55785 × 0.08 = 0.35702

For k = 8 successes:
P(X = 8) = 1 × 0.92^8 = 0.51322

P(X ≥ 5) = 0.01890 + 0.10866 + 0.35702 + 0.51322 = 0.99780

P(correct) ≈ 99.78%, predicted error rate ≈ 0.22%.

### (b) Production Discrepancy

Observed error is roughly 3x higher (~0.66%). The binomial calc relies on three things being true: failures are independent (i.i.d.), every agent has 92% accuracy on every query type, and wrong answers are unique per agent. Each hypothesis breaks one of those.

H1, correlated failures from shared base model. If all 8 agents are built on the same base model or fine-tuned from the same training data they tend to fail on the same kinds of things, rare entities, ambigous phrasings, weird formats. The binomial assumes failures are independent but in reality they cluster, so joint failures show up way more often than 0.08^k would predict. To check, compute the pairwise error correlation matrix across the 8 agents on production traffic. Independence predicts off-diagonal ≈ 0, correlated failures show up as strong positive entries. Using 8 by 8 matrix.

H2, specialty mismatch dilutes the vote. The 92% accuracy number is an average across all query types but each agent is good at different things. Test set probaly had a balanced mix of querys that played to every agents strenghts, so they all looked like they hit 92%. In production though, the mix of querys is skewed so most of them fall outside what most agents are actualy good at. Imagine a credit query, only 1-2 agents are credit specialists, the other 6-7 are guessing. Those off-specialty agents dont just sit out, they vote and they vote close to random, which drags the experts down. To check, compare the query type distributions between test and production. If they match, the hypothesis is wrong. If production is heavily skewed toward types where most agents are off-specialty, thats H2.

H3, wrong answers cluster. The binomial assumes that when agents are wrong they each get it wrong differently, so 4 wrong agents give 4 different wrong answers and none of them have a majority. In reality LLMs tend to make the same mistake, they all latch onto the same plausible-but-wrong answer. So 4 wrong agents can all vote for the exact same wrong answer and either tie the 4 right ones or even beat them 5-3. To check, look at the queries where the vote came out wrong and see how concentrated the wrong votes are. If they keep piling onto the same one or two wrong answers thats H3, if the wrong votes are scattered across loads of different answers H3 is ruled out.

### (c) Instrumentation

Log the full vote vector per query. For every query, write down the query id, the query type tag, and for each of the 8 agents what answer they gave plus their confidence. Also log the final majority winner and the actual right answer where you can get it (spot checks, user feedback, downstream signals etc).

This one log lets you check H1 and H3 from the same data.

For H1 (correlated failures), look at every pair of agents and see how often they were both wrong on the same query. If failures are truly independant the rate of both being wrong together should be roughly 0.08 × 0.08 = 0.0064 per pair. If its much higher than that the agents are failing together and H1 is alive. If its near 0.0064 H1 is dead.

For H3 (wrong-answer clustering), filter down to the queries where the vote got it wrong, then count how many distinct wrong answers showed up in the votes. If the wrong votes keep piling onto the same one or two answers thats H3. If they spread out across loads of different wrong answers H3 is wrong.

H1 looks at who fails together, H3 looks at what they fail to. Same log shows both patterns. As a side benefit the query type tag also lets you test H2, you can compare per-type accuracy between test and production from the same data.
