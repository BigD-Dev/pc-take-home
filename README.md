# pc-take-home

Submission for the ExodusPoint AI Engineer take-home. Three implementation parts plus a written design doc.

## Layout

- `part1/` — `agent_swarm.py`, multi-agent orchestrator with intent-based routing, channel context, weighted majority vote
- `part2/` — `evaluator.py`, offline scoring harness for a hybrid RAG pipeline (faithfulness, context precision, answer relevance, failure category)
- `part3/` — `dispatcher.py` (TokenBudgetDispatcher with concurrency bug fix and exponential backoff) and `test_dispatcher.py` (deterministic regression test)
- `part1/design_doc.md` — written answers for Parts 1c, 2a, 2c, and Part 4

## Running

Python 3.10+ recomended. Standard library only, plus `pytest` and `pytest-asyncio` for the regression test.

```bash
pip install pytest pytest-asyncio
pytest part3/test_dispatcher.py -v
```

## Assumptions

- **LLM-as-judge calls are stubbed.** `RetrievalEvaluator.faithfulness_score` returns a hardcoded value (0.85) where a real implementation would call haiku, gpt-4o-mini or similar. The prompt is written out in the function so the wiring is obvious.
- **Embedding model is stubbed.** `answer_relevance` returns 0.75 where a real cosine similarity over query/response embeddings would go. The TODO in the code shows the substitution point.
- **Golden dataset is stubbed.** `context_precision` and `_quantile_correlation` reference a "golden dataset" via hardcoded values. In production this would be a labelled reference db built from expert annotations, queried by `golden_db.lookup(query)` or similar.
- **Conclusions in the agent swarm are deterministic stubs.** `ResearchAgent._SPECIALTY_CONCLUSIONS` maps each specialty to a fixed conclusion so the majority vote groups properly. Real agents would output via an actual LLM call.
- **Token usage in the dispatcher is read from the LLM response.** `dispatch` expects `fn()` to return a dict with `tokens_used`. A real implementation would either take the count from the API response (OpenAI/Anthropic both return this) or estimate before the call.

## Dependencies

- Python 3.10+ (uses `dict[str, int]` style type hints)
- `pytest`, `pytest-asyncio` for the regression test
- No external API keys, no model weights, no other infra

## Known Limitations

- **Stubs everywhere.** None of the actual model calls are wired up. The regression test runs because it doesn't depend on real LLM behaviour but the evaluator and the agent swarm produce stub outputs. Designed this way so the structure is reviewable without API access.
- **Circuit breaker recovery uses `time.monotonic()`** which means tests touching the recovery path would need to manipulate `last_failure_time` directly (the regression test does this).
- **`dispatch_with_backoff` retries on any non-RuntimeError exception.** RuntimeErrors (budget exceeded, circuit open) are re-raised immediately because retrying wouldn't help. A more sophisticated version would distinguish transient network errors from permanent ones.
- **The agent swarm runs all assigned agents concurrently per query but doesn't currently support inter-agent calls.** CycleGuard is in place for when that gets added, but no agent currently calls another.
- **Failure categorisation thresholds in `failure_category` (0.4, 0.3, 0.15, 0.1) are placeholders.** They need tuning against real labelled production data once the LLM judge is wired up.
