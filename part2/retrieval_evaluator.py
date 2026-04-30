import asyncio
import time
from statistics import mean


class RetrievalEvaluator:

    def faithfulness_score(
        self,
        response: str,
        retrieved_chunks: list[str],
    ) -> float:
        """
        Score 0.0-1.0: degree to which the response is grounded in
        the retrieved context. A response that introduces facts not
        present in any chunk should score low.
        """
        # LLM-as-judge would be ideal here - prompt a model to verify each
        # claim in the response against the chunks one by one. Using token
        # overlap as a stub heuristic instead.
        # Trade-off: misses paraphrasing but needs no API call and is fast.
        if not response or not retrieved_chunks:
            return 0.0

        response_tokens = set(response.lower().split())
        chunk_tokens = set()
        for chunk in retrieved_chunks:
            chunk_tokens.update(chunk.lower().split())

        overlap = response_tokens & chunk_tokens
        return round(len(overlap) / len(response_tokens), 2)

    def context_precision(
        self,
        retrieved_chunks: list[str],
        relevant_chunk_ids: list[int],
    ) -> float:
        """
        Score 0.0-1.0: proportion of retrieved chunks that are
        genuinely relevant to the query.
        """
        # pure heuristic - precision = relevant retrieved / total retrieved
        # relevant_chunk_ids are ground truth labels for which chunk positions are useful
        # Trade-off: requires ground truth labels but gives exact precision, no model needed
        if not retrieved_chunks:
            return 0.0

        return round(len(relevant_chunk_ids) / len(retrieved_chunks), 2)

    def answer_relevance(self, query: str, response: str) -> float:
        """
        Score 0.0-1.0: how well the response addresses what was asked.
        A response that is factually grounded but answers a different
        question should score low here.
        """
        # embedding cosine similarity would be ideal here - encode query and response
        # as vectors and measure semantic alignment in embedding space.
        # Using word overlap as a stub instead.
        # Trade-off: misses semantic similarity (synonyms, paraphrasing) but avoids
        # embedding model dependency - swap this out for sentence-transformers in prod
        if not query or not response:
            return 0.0

        query_tokens = set(query.lower().split())
        response_tokens = set(response.lower().split())

        overlap = query_tokens & response_tokens
        return round(len(overlap) / len(query_tokens), 2)

    def _score_chunk_relevance(self, chunk: str, query: str) -> float:
        # token overlap between a single chunk and the query
        # used internally to score chunks without ground truth labels
        query_tokens = set(query.lower().split())
        chunk_tokens = set(chunk.lower().split())
        if not query_tokens:
            return 0.0
        return len(query_tokens & chunk_tokens) / len(query_tokens)

    def _quantile_correlation(
        self,
        query: str,
        full_ranked_chunks: list[str],
        n_quantiles: int = 4,
    ) -> float:
        # splits the full ranked list into quantiles and scores each chunk's
        # relevance to the query. returns a correlation coefficient:
        # negative value = lower ranked chunks are MORE relevant than higher ranked ones
        # which is a strong signal of ranking failure
        if not full_ranked_chunks:
            return 0.0

        size = max(1, len(full_ranked_chunks) // n_quantiles)
        quantile_scores = []

        for i in range(n_quantiles):
            start = i * size
            end = start + size if i < n_quantiles - 1 else len(full_ranked_chunks)
            batch = full_ranked_chunks[start:end]
            if batch:
                quantile_scores.append(mean(
                    self._score_chunk_relevance(c, query) for c in batch
                ))

        if len(quantile_scores) < 2:
            return 0.0

        # simple correlation: are scores increasing as rank gets worse?
        # positive = lower quantiles more relevant = ranking is inverted = bad
        diffs = [quantile_scores[i+1] - quantile_scores[i]
                 for i in range(len(quantile_scores) - 1)]
        return mean(diffs)

    def _adjacent_pair_faithfulness(
        self,
        response: str,
        chunks: list[str],
    ) -> float:
        # scores pairs of adjacent chunks together against the response
        # if a pair scores significantly higher than either chunk alone,
        # the answer likely straddles a chunk boundary
        if len(chunks) < 2:
            return 0.0

        best_pair_score = 0.0
        best_solo_score = max(
            self.faithfulness_score(response, [c]) for c in chunks
        )

        for i in range(len(chunks) - 1):
            pair_score = self.faithfulness_score(response, [chunks[i], chunks[i+1]])
            best_pair_score = max(best_pair_score, pair_score)

        # return how much better a pair is vs the best single chunk
        return round(best_pair_score - best_solo_score, 2)

    def failure_category(
        self,
        query: str,
        response: str,
        retrieved_chunks: list[str],
        full_ranked_chunks: list[str] = None,   # full list before TOP_K cutoff
        relevant_chunk_ids: list[int] = None,   # ground truth labels if available
    ) -> str:
        """
        Returns one of:
            retrieval_miss | context_pollution | chunk_boundary |
            ranking_failure | ok
        """
        # compute core scores
        faith      = self.faithfulness_score(response, retrieved_chunks)
        relevance  = self.answer_relevance(query, response)
        precision  = (
            self.context_precision(retrieved_chunks, relevant_chunk_ids)
            if relevant_chunk_ids is not None
            else mean(self._score_chunk_relevance(c, query) for c in retrieved_chunks)
            # fall back to heuristic precision if no ground truth labels provided
        )

        # chunk boundary check - run before other checks since it has a
        # specific signature: faith is ok but relevance is low, and adjacent
        # pairs score meaningfully higher than individual chunks
        boundary_lift = self._adjacent_pair_faithfulness(response, retrieved_chunks)
        if faith >= 0.4 and relevance < 0.3 and boundary_lift > 0.15:
            return "chunk_boundary"

        # ranking failure check - only possible if full ranked list is provided
        # look for negative correlation between rank position and relevance score
        # i.e. chunks outside TOP_K are more relevant than those inside it
        if full_ranked_chunks is not None:
            rank_correlation = self._quantile_correlation(query, full_ranked_chunks)
            if rank_correlation > 0.1 and faith < 0.4:
                # lower quantiles (worse rank) scoring higher = ranking is inverting relevance
                return "ranking_failure"

        # context pollution - retrieved chunks contain a mix of relevant and
        # irrelevant content, model conflated them
        if faith < 0.4 and precision >= 0.4:
            return "context_pollution"

        # retrieval miss - nothing relevant came back, model hallucinated
        if faith < 0.4 and precision < 0.4:
            return "retrieval_miss"

        return "ok"
