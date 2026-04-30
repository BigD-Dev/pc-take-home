import asyncio
import random
import time
from dataclasses import dataclass
from typing import Callable, Awaitable
from enum import Enum


class CircuitState(Enum):
    CLOSED    = 'closed'     # Normal - requests pass through
    OPEN      = 'open'       # Tripped - reject all requests
    HALF_OPEN = 'half_open'  # Probing - allow one attempt


@dataclass
class CircuitBreaker:
    failure_threshold: int          = 5
    recovery_timeout:  float        = 30.0
    state:             CircuitState = CircuitState.CLOSED
    failure_count:     int          = 0
    last_failure_time: float        = 0.0

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN

    def record_success(self):
        # reset count on any success, dont want old failures counting against us
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def can_attempt(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            # wait for recovery window before trying again
            if time.monotonic() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True  # HALF_OPEN: allow one probe


class TokenBudgetDispatcher:
    def __init__(self, token_budget: int, max_concurrent: int = 10):
        self.token_budget    = token_budget
        self.tokens_used     = 0
        self.semaphore       = asyncio.Semaphore(max_concurrent)
        self.circuit_breaker = CircuitBreaker()
        self._lock           = asyncio.Lock()  # fix: asyncio.Lock so check+update is atomic, no threading.Lock

    async def dispatch(self, fn: Callable[[], Awaitable[dict]]) -> dict:
        """Dispatch one LLM call, enforcing the token budget."""
        if not self.circuit_breaker.can_attempt():
            raise RuntimeError('Circuit breaker is OPEN')

        async with self.semaphore:
            try:
                result = await fn()  # fix: outside the lock so concurrent LLM calls arent serialised
            except Exception:
                self.circuit_breaker.record_failure()
                raise

            tokens = result.get('tokens_used', 0)

            # fix: lock only held here for the synchronous check+update, no await inside
            # so no context switch can happen between the check and the increment
            async with self._lock:
                if self.tokens_used + tokens > self.token_budget:
                    self.circuit_breaker.record_failure()
                    raise RuntimeError('Token budget exceeded')
                self.tokens_used += tokens

            self.circuit_breaker.record_success()
            return result

    async def dispatch_with_backoff(
        self,
        fn: Callable[[], Awaitable[dict]],
        max_retries: int = 3,
        base: float = 0.5,
        cap: float = 30.0,
    ) -> dict:
        # common error: random.uniform(0, cap) flat window every attempt, doesnt actually grow exponentially
        # correct full jitter = uniform between 0 and min(cap, base * 2**attempt) so early retrys
        # have a small window that grows each attempt untill it hits the cap
        for attempt in range(max_retries + 1):
            try:
                return await self.dispatch(fn)
            except RuntimeError:
                raise  # budget exceeded or circuit open, retrying wont help here
            except Exception:
                if attempt == max_retries:
                    raise
                # window grows exponentialy with each attempt, not flat accross all retries
                sleep = random.uniform(0, min(cap, base * 2 ** attempt))
                await asyncio.sleep(sleep)

    def budget_remaining(self) -> int:
        # how much is left, usefull for callers that want to check before dispatching
        return self.token_budget - self.tokens_used

    def reset(self):
        self.tokens_used = 0
        # important: dont just zero failure_count, need to replace the whole breaker
        # otherwise state stays OPEN and every request gets rejected even after reset
        self.circuit_breaker = CircuitBreaker()
