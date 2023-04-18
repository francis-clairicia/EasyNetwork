# -*- coding: Utf-8 -*-

from __future__ import annotations

import enum
from typing import assert_never

import pytest


class EventLoop(enum.StrEnum):
    ASYNCIO = "asyncio"
    UVLOOP = "uvloop"


ASYNCIO_EVENT_LOOP_OPTION = "asyncio_event_loop"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--asyncio-event-loop",
        dest=ASYNCIO_EVENT_LOOP_OPTION,
        type=EventLoop,
        default=EventLoop.ASYNCIO,
        choices=list(map(str, EventLoop)),
    )


def pytest_configure(config: pytest.Config) -> None:
    event_loop: EventLoop = config.getoption(ASYNCIO_EVENT_LOOP_OPTION)
    match event_loop:
        case EventLoop.ASYNCIO:
            pass
        case EventLoop.UVLOOP:
            import uvloop

            uvloop.install()
        case _:
            assert_never(event_loop)

    config.addinivalue_line("markers", "skip_uvloop: Skip asyncio test if uvloop is used")


def pytest_report_header(config: pytest.Config) -> str:
    return f"asyncio event-loop: {config.getoption(ASYNCIO_EVENT_LOOP_OPTION)}"


def pytest_runtest_setup(item: pytest.Item) -> None:
    event_loop: EventLoop = item.config.getoption(ASYNCIO_EVENT_LOOP_OPTION)

    match event_loop:
        case EventLoop.UVLOOP if item.get_closest_marker("skip_uvloop") is not None:
            pytest.skip("Skipped because uvloop runner is used")
