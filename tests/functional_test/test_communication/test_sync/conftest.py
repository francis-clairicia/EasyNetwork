from __future__ import annotations

import selectors
import time
from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from easynetwork.lowlevel.api_sync.transports.base_selector import _can_use_selector

import pytest


@pytest.fixture
def schedule_call_in_thread_with_future(
    request: pytest.FixtureRequest,
) -> Generator[Callable[[float, Callable[[], Any]], Future[Any]]]:
    with ThreadPoolExecutor(thread_name_prefix=f"pytest-easynetwork_{request.node.name}") as executor:
        perf_counter = time.perf_counter

        def task(time_to_sleep: float, callback: Callable[[], Any], submit_timestamp: float) -> None:
            time_to_sleep -= perf_counter() - submit_timestamp
            if time_to_sleep > 0:
                time.sleep(time_to_sleep)
            callback()

        def schedule_call(time_to_sleep: float, callback: Callable[[], Any]) -> Future[Any]:
            return executor.submit(task, time_to_sleep, callback, perf_counter())

        yield schedule_call


@pytest.fixture
def schedule_call_in_thread(
    schedule_call_in_thread_with_future: Callable[[float, Callable[[], Any]], Future[Any]],
) -> Callable[[float, Callable[[], Any]], None]:
    def schedule_call_in_thread(*args: Any) -> None:
        schedule_call_in_thread_with_future(*args)

    return schedule_call_in_thread


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
