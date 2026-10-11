from __future__ import annotations

import errno
import selectors
from collections.abc import Callable

from easynetwork.lowlevel._errno import error_from_errno
from easynetwork.lowlevel.api_sync.transports.base_selector import _can_use_selector

import pytest


class BadSelector(selectors.SelectSelector):

    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        raise error_from_errno(errno.EINVAL)


_AVAILABLE_SELECTORS: dict[str, Callable[[], selectors.BaseSelector] | None] = {
    "kqueue": getattr(selectors, "KqueueSelector") if _can_use_selector("kqueue") else None,
    "epoll": getattr(selectors, "EpollSelector") if _can_use_selector("epoll") else None,
    "devpoll": getattr(selectors, "DevpollSelector") if _can_use_selector("devpoll") else None,
    "poll": getattr(selectors, "PollSelector") if _can_use_selector("poll") else None,
    "select": selectors.SelectSelector,
}


@pytest.fixture(params=[s for s in _AVAILABLE_SELECTORS if _AVAILABLE_SELECTORS[s]])
def selector_factory(request: pytest.FixtureRequest) -> Callable[[], selectors.BaseSelector]:
    if request.param == "default":
        return selectors.DefaultSelector
    if request.param == "invalid":
        return BadSelector
    assert request.param in _AVAILABLE_SELECTORS
    selector_factory: Callable[[], selectors.BaseSelector] | None = _AVAILABLE_SELECTORS[request.param]
    if selector_factory is None:
        pytest.skip(f"{request.param!r} selector unavailable")
    return selector_factory


@pytest.hookimpl(tryfirst=True)
def pytest_report_header() -> list[str]:
    return [
        f"server selector: {name} ({factory.__module__}.{factory.__qualname__})"
        for name, factory in _AVAILABLE_SELECTORS.items()
        if factory
    ]
