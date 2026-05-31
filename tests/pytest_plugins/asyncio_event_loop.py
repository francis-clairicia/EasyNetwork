from __future__ import annotations

import asyncio
import enum
import functools
import importlib
import sys
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, TypeAlias, assert_never

import pytest

LoopFactory: TypeAlias = Callable[[], asyncio.AbstractEventLoop]


class EventLoop(enum.StrEnum):
    ASYNCIO = "asyncio"
    ASYNCIO_PROACTOR = "asyncio-proactor"
    UVLOOP = "uvloop"


ASYNCIO_EVENT_LOOPS_OPTION = "asyncio_event_loops"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("asyncio")
    group.addoption(
        "--asyncio-event-loop",
        dest=ASYNCIO_EVENT_LOOPS_OPTION,
        action="append",
        type=EventLoop,
        default=[],
        choices=list(map(str, EventLoop)),
        help="Choose which runners to use (default: all available)",
    )


def _get_proactor_event_loop() -> type[asyncio.AbstractEventLoop] | None:
    return getattr(asyncio, "ProactorEventLoop", None)


def _get_uvloop_event_loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    try:
        uvloop: Any = importlib.import_module("uvloop")
    except ModuleNotFoundError:
        return None
    return getattr(uvloop, "new_event_loop", None)


def _get_event_loop_factory(event_loop: EventLoop) -> LoopFactory | None:
    loop_factory: LoopFactory | None
    match event_loop:
        case EventLoop.ASYNCIO:
            loop_factory = asyncio.SelectorEventLoop
        case EventLoop.ASYNCIO_PROACTOR:
            loop_factory = _get_proactor_event_loop()
        case EventLoop.UVLOOP:
            loop_factory = _get_uvloop_event_loop_factory()
        case _:
            assert_never(event_loop)
    return loop_factory


@functools.cache
def _cached_event_loop_factories() -> MappingProxyType[str, LoopFactory]:
    return MappingProxyType(
        {
            event_loop: loop_factory
            for event_loop in EventLoop
            if (loop_factory := _get_event_loop_factory(event_loop)) is not None
        }
    )


def _get_event_loop_factories_from_config(config: pytest.Config) -> Mapping[str, LoopFactory]:
    needed_event_loops: list[EventLoop] = config.getoption(ASYNCIO_EVENT_LOOPS_OPTION, [])
    all_event_loops = _cached_event_loop_factories()
    if needed_event_loops:
        unknown_event_loops = set(needed_event_loops).difference(all_event_loops.keys())
        if unknown_event_loops:
            raise pytest.UsageError(f"Event loop not available in this platform: {', '.join(sorted(unknown_event_loops))}")
        return {event_loop: all_event_loops[event_loop] for event_loop in needed_event_loops}
    return all_event_loops


def pytest_asyncio_loop_factories(config: pytest.Config) -> Mapping[str, LoopFactory]:
    return _get_event_loop_factories_from_config(config)


@pytest.hookimpl(trylast=True)
def pytest_report_header(config: pytest.Config) -> list[str]:
    event_loops = _get_event_loop_factories_from_config(config)
    return [
        f"asyncio event-loop: {event_loop} ({loop_factory.__module__}.{loop_factory.__qualname__})"
        for event_loop, loop_factory in event_loops.items()
    ]


def pytest_configure() -> None:
    import inspect

    if sys.version_info >= (3, 14):
        # asyncio.iscoroutinefunction is deprecated since Python 3.12 but uvloop uses it and creates 2000+ warnings with Python 3.14.
        asyncio.iscoroutinefunction = inspect.iscoroutinefunction  # type: ignore[assignment]
