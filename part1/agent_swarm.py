import asyncio
import uuid
import time


class TokenBudgetExceeded(Exception):
    pass


class LoopDetected(Exception):
    pass
