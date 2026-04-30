# pc-take-home

Senior AI engineer take-home submission. Three implementation parts plus a written design doc.

# layout

part1/agent_swarm.py is the rewritten multi-agent orchestrator. design_doc.md lives in part1/ and covers the architecture diagram, the rejected design decision and written answers for 2a, 2c and Part 4.

part2/evaluator.py is the RetrievalEvaluator class with faithfulness, context precision, answer relevance and failure category methods.

part3/dispatcher.py is the fixed TokenBudgetDispatcher and part3/test_dispatcher.py is the determinstic regression test.

# running

Python 3.10 or higher. Standard library only, plus pytest and pytest-asyncio for the regression test.

pip install pytest pytest-asyncio
pytest part3/test_dispatcher.py -v

# assumptions

The LLM-as-judge call in faithfulness_score is stubbed and returns 0.85. The prompt is written out in the function so the wiring point is obvious, in production this would be a small lightweight model.

answer_relevance uses an embedding stub returning 0.75. A real version would embed the query and response and compute cosine similarity.

The golden dataset used by context_precision and _quantile_correlation is stubbed too. In production it would be a pre-labelled reference db built from expert annotations and queried by something like golden_db.lookup(query). context_precision takes an optional relevant_chunk_ids param so tests can pass labels in directly without hitting the stub.

Specialty conclusions in the swarm are deterministic stubs in _SPECIALTY_CONCLUSIONS so the majority vote groups properly. Real agents would output via an actual LLM call.

Agent confidence weights are static, set at agent creation. A more sophisticated version would have the intent classifier return a per-query relevance score per specialist so weights become effective_weight = agent.confidence_weight * relevance_score, that way a highly trusted agent answering an off-topic question gets downweighted. For this submission static is fine, it satisifes the brief, dynamic is a production enhancment.

Token usage in the dispatcher is read from the LLM response (fn returns a dict with tokens_used). A real implementation would either take the count from the API response or estimate before the call.

# dependencies

Python 3.10+, pytest, pytest-asyncio. No external API keys, no model weights, no other infra.

# known limitations

Stubs throughout, none of the actual model calls are wired up. The structure is reviewable without API access.

dispatch_with_backoff retries on any non-RuntimeError exception. RuntimeErrors (budget exceeded, circuit open) are re-raised immediately because retrying wouldnt help, those arent transient.

CycleGuard is in place for chained agent calls but the swarm doesn't currently invoke them, no agent calls another agent yet.

Failure category thresholds in failure_category (0.4, 0.3, 0.15, 0.1) are placeholders, they need tuning against real labelled production data once the LLM judge is wired up.

The regression test uses asyncio.Event to force the race deterministically rather than relying on timing, so it works the same on any machine regardless of speed.
