from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None]:
    __tracebackhide__ = True

    if item.get_closest_marker("trio"):
        # pytest-trio wraps *ALL* exceptions in a BaseExceptionGroup because of the test's global nursery
        try:
            return (yield)
        except BaseExceptionGroup as excgrp:
            if "nursery" in excgrp.message.lower() and len(excgrp.exceptions) == 1:
                old_context = excgrp.exceptions[0].__context__
                try:
                    raise excgrp.exceptions[0]
                finally:
                    excgrp.exceptions[0].__context__ = old_context
                    old_context = None
            raise

    return (yield)
