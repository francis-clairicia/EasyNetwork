# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import enum
import importlib
from typing import TYPE_CHECKING, Any, assert_never

import pytest


class EventLoop(enum.StrEnum):
    ASYNCIO = "asyncio"
    ASYNCIO_PROACTOR = "asyncio-proactor"
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


def _get_windows_selector_policy() -> type[asyncio.AbstractEventLoopPolicy] | None:
    return getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)


def _get_windows_proactor_policy() -> type[asyncio.AbstractEventLoopPolicy] | None:
    return getattr(asyncio, "WindowsProactorEventLoopPolicy", None)


def _set_event_loop_policy_according_to_configuration(config: pytest.Config) -> None:
    event_loop: EventLoop = config.getoption(ASYNCIO_EVENT_LOOP_OPTION)
    match event_loop:
        case EventLoop.ASYNCIO:
            WindowsSelectorEventLoopPolicy = _get_windows_selector_policy()
            if WindowsSelectorEventLoopPolicy is not None:
                asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
        case EventLoop.ASYNCIO_PROACTOR:
            WindowsProactorEventLoopPolicy = _get_windows_proactor_policy()
            if WindowsProactorEventLoopPolicy is None:
                raise pytest.UsageError(f"{event_loop} event loop is not available in this platform")
            asyncio.set_event_loop_policy(WindowsProactorEventLoopPolicy())
        case EventLoop.UVLOOP:
            try:
                uvloop: Any = importlib.import_module("uvloop")
            except ModuleNotFoundError:
                raise pytest.UsageError(f"{event_loop} event loop is not available in this platform")

            uvloop.install()
        case _:
            assert_never(event_loop)


def pytest_configure(config: pytest.Config) -> None:
    _set_event_loop_policy_according_to_configuration(config)
    config.addinivalue_line("markers", "skipif_uvloop: Skip asyncio test if uvloop is used")
    config.addinivalue_line("markers", "xfail_uvloop: Expected asyncio test to fail if uvloop is used")


@pytest.hookimpl(trylast=True)  # type: ignore[misc]
def pytest_report_header(config: pytest.Config) -> str:
    return f"asyncio event-loop: {config.getoption(ASYNCIO_EVENT_LOOP_OPTION)}"


def _skip_test_if_uvloop_is_used(config: pytest.Config, item: pytest.Item) -> None:
    if item.get_closest_marker("skipif_uvloop") is not None:
        item.add_marker(
            pytest.mark.skipif(
                config.getoption(ASYNCIO_EVENT_LOOP_OPTION) == EventLoop.UVLOOP,
                reason="Skipped because uvloop runner is used",
            )
        )


def _xfail_test_if_uvloop_is_used(config: pytest.Config, item: pytest.Item) -> None:
    if item.get_closest_marker("xfail_uvloop") is not None:
        item.add_marker(
            pytest.mark.xfail(
                config.getoption(ASYNCIO_EVENT_LOOP_OPTION) == EventLoop.UVLOOP,
                reason="uvloop runner does not implement the needed function",
                strict=True,
                raises=NotImplementedError,
            )
        )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        _skip_test_if_uvloop_is_used(config, item)
        _xfail_test_if_uvloop_is_used(config, item)


@pytest.fixture
def event_loop_name(pytestconfig: pytest.Config) -> EventLoop:
    return pytestconfig.getoption(ASYNCIO_EVENT_LOOP_OPTION)


if TYPE_CHECKING:

    @pytest.fixture
    def event_loop(event_loop: asyncio.AbstractEventLoop) -> asyncio.AbstractEventLoop:
        ...
