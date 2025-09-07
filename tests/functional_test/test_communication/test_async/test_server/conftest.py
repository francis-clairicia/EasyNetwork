from __future__ import annotations

import collections
import itertools
import logging
from collections.abc import Generator
from threading import Event
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def logger_crash_enable() -> Event:
    return Event()


@pytest.fixture
def logger_crash_threshold_level() -> dict[str, int]:
    return {}


@pytest.fixture
def logger_crash_maximum_nb_lines() -> dict[str, int]:
    return {}


@pytest.fixture
def logger_crash_xfail() -> dict[str, str]:
    return {}


# Workaround to make a test properly fail after each test call without using fixtures.
# More details here: https://github.com/pytest-dev/pytest/issues/5044
@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None]:
    if not isinstance(item, pytest.Function):
        return (yield)

    item_fixtures: dict[str, Any] = item.funcargs

    yield

    logger_crash_enable: Event = item_fixtures["logger_crash_enable"]
    if not logger_crash_enable.is_set():
        return

    caplog: pytest.LogCaptureFixture | None = item_fixtures.get("caplog")
    if not caplog:
        return

    logger_crash_threshold_level: dict[str, int] = item_fixtures.get("logger_crash_threshold_level", {})
    logger_crash_maximum_nb_lines: dict[str, int] = item_fixtures.get("logger_crash_maximum_nb_lines", {})
    logger_crash_xfail: dict[str, str] = item_fixtures.get("logger_crash_xfail", {})

    log_line_counter: collections.Counter[str] = collections.Counter()

    failure_caught: dict[str, str] = {}
    expected_failure_caught: dict[str, str] = {}
    for record in itertools.chain(caplog.get_records("setup"), caplog.get_records("call")):
        if record.name in failure_caught or record.name in expected_failure_caught:
            continue
        threshold_level = logger_crash_threshold_level.get(record.name, logging.ERROR)
        if record.levelno < threshold_level:
            continue
        log_line_counter[record.name] += 1
        maximum_nb_lines = max(logger_crash_maximum_nb_lines.get(record.name, 0), 0)
        if log_line_counter[record.name] <= maximum_nb_lines:
            continue
        threshold_level_name = logging.getLevelName(threshold_level)

        if maximum_nb_lines:
            failure_message = f"More than {maximum_nb_lines} logs with level equal to or greater than {threshold_level_name} caught in {record.name} logger"
        else:
            failure_message = f"Logs with level equal to or greater than {threshold_level_name} caught in {record.name} logger"

        expected_failure_message: str = logger_crash_xfail.get(record.name, "")
        if expected_failure_message:
            expected_failure_caught[record.name] = f"{failure_message} because: {expected_failure_message}"
        else:
            failure_caught[record.name] = failure_message

    if failure_caught:
        failure_message = "\n".join(
            itertools.chain(failure_caught.values(), (f"(xfail) {msg}" for msg in expected_failure_caught.values()))
        )
        pytest.fail(failure_message)

    if expected_failure_caught:
        expected_failure_message = "\n".join(expected_failure_caught.values())
        pytest.xfail(expected_failure_message)
