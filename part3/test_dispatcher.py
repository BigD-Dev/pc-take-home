import asyncio
import pytest
import sys
sys.path.insert(0, 'part3')
from dispatcher import TokenBudgetDispatcher


#reconstructed the orignal defective version to show the race condtion
# check and update seperated by await so another corotuine can sneak in between them
class DefectiveTokenBudgetDispatcher:
    def __init__(self, token_budget: int, max_concurrent: int = 10):
        self.token_budget = token_budget
        self.tokens_used  = 0
        self.semaphore    = asyncio.Semaphore(max_concurrent)

    async def dispatch(self, fn):
        async with self.semaphore:
            if self.tokens_used >= self.token_budget:  # CHECK
                raise RuntimeError('Token budget exceeded')
            result = await fn()  # yeild point, another task can pass the check here before we update
            self.tokens_used += result.get('tokens_used', 0)  # UPDATE to late
        return result


@pytest.mark.asyncio
async def test_budget_overrun_regression():
    #force the race deterministicaly using asyncio.Event, no timing reliance
    # task A passes check then suspends task B also passes check while A is waiting
    # both update and total exeeds budget

    # part 1 - defective code allows the overrun

    a_passed_check = asyncio.Event()
    b_finished     = asyncio.Event()

    async def fn_a():
        a_passed_check.set()    #A passed check now yeilding
        await b_finished.wait() # stay here so B can sneak past the check
        return {'tokens_used': 90}

    async def fn_b():
        b_finished.set() # wake A back up
        return {'tokens_used': 90}

    defective = DefectiveTokenBudgetDispatcher(token_budget=100)

    task_a = asyncio.create_task(defective.dispatch(fn_a))
    await a_passed_check.wait()    # A is suspended, tokens_used still 0
    await defective.dispatch(fn_b) # B also passes check (0 < 100) updates to 90
    await task_a                   # A resumes, 90 + 90 = 180 budget blown

    assert defective.tokens_used > defective.token_budget, ( #should be over 100
        f"defective code should of overrun: tokens_used={defective.tokens_used} budget={defective.token_budget}"
    )

    # part 2 - same conditions, fixed code holds the budget

    a_passed_check2 = asyncio.Event()
    b_finished2     = asyncio.Event()

    async def fn_a2():
        a_passed_check2.set()
        await b_finished2.wait()
        return {'tokens_used': 90}

    async def fn_b2():
        b_finished2.set()
        return {'tokens_used': 90}

    fixed = TokenBudgetDispatcher(token_budget=100)

    task_a2 = asyncio.create_task(fixed.dispatch(fn_a2))
    await a_passed_check2.wait()
    await fixed.dispatch(fn_b2) # lock makes check+update atomic, updates to 90

    try:
        await task_a2 # A tries to update, lock rejects 90+90=180 > 100
    except RuntimeError:
        pass # expected

    assert fixed.tokens_used <= fixed.token_budget, ( # should be 90 not 180
        f"fixed code shouldnt overrun: tokens_used={fixed.tokens_used} budget={fixed.token_budget}"
    )
