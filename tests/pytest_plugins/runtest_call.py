from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None]:
    __tracebackhide__ = True

    if item.get_closest_marker("trio"):
        # pytest-trio wraps *ALL* exceptions in a BaseExceptionGroup because of the test's global nursery
        try:
            return (yield)
        except BaseExceptionGroup as excgrp:
            if "nursery" in excgrp.message.lower() and len(excgrp.exceptions) == 1:
                raise excgrp.exceptions[0] from None
            raise

    if item.get_closest_marker("asyncio"):
        # Some tests are under an asyncio.TaskGroup scope.
        try:
            return (yield)
        except* AssertionError as excgrp:
            if "TaskGroup" in excgrp.message and len(excgrp.exceptions) == 1:
                raise excgrp.exceptions[0] from None
            raise

    return (yield)
