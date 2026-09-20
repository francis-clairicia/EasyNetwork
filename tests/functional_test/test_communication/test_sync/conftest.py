from __future__ import annotations

import selectors
import time
from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

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


def _can_use_selector(method: str) -> bool:
    import select

    """Check if we can use the selector depending upon the
    operating system. """
    # Implementation based upon https://github.com/sethmlarson/selectors2/blob/master/selectors2.py
    selector = getattr(select, method, None)
    if selector is None:
        # select module does not implement method
        return False
    # check if the OS and Kernel actually support the method. Call may fail with
    # OSError: [Errno 38] Function not implemented
    try:
        selector_obj = selector()
        if method == "poll":
            # check that poll actually works
            selector_obj.poll(0)
        else:
            # close epoll, kqueue, and devpoll fd
            selector_obj.close()
        return True
    except OSError:
        return False


_AVAILABLE_SELECTORS: dict[str, Callable[[], selectors.BaseSelector] | None] = {
    "select": selectors.SelectSelector,
    "poll": getattr(selectors, "PollSelector") if _can_use_selector("poll") else None,
    "epoll": getattr(selectors, "EpollSelector") if _can_use_selector("epoll") else None,
    "devpoll": getattr(selectors, "DevpollSelector") if _can_use_selector("devpoll") else None,
    "kqueue": getattr(selectors, "KqueueSelector") if _can_use_selector("kqueue") else None,
}


@pytest.fixture(params=sorted([s for s in _AVAILABLE_SELECTORS if _AVAILABLE_SELECTORS[s]]))
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
