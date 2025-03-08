from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import pytest


@pytest.fixture
def schedule_call_in_thread_with_future(
    request: pytest.FixtureRequest,
) -> Iterator[Callable[[float, Callable[[], Any]], Future[Any]]]:
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
