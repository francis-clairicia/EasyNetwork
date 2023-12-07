from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from easynetwork.lowlevel.std_asyncio.datagram.endpoint import DatagramEndpoint
from easynetwork.lowlevel.std_asyncio.socket import AsyncSocket

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_async_socket_factory(mocker: MockerFixture, event_loop: asyncio.AbstractEventLoop) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=AsyncSocket)
        mock.is_closing.return_value = False
        mock.loop = event_loop
        mock.did_shutdown_SHUT_WR = False
        return mock

    return factory


@pytest.fixture
def mock_async_socket(mock_async_socket_factory: Callable[[], MagicMock]) -> MagicMock:
    return mock_async_socket_factory()


@pytest.fixture
def mock_datagram_endpoint_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=DatagramEndpoint)
        mock.is_closing.return_value = False
        return mock

    return factory


@pytest.fixture
def mock_asyncio_stream_reader_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=asyncio.StreamReader)
        return mock

    return factory


@pytest.fixture
def mock_asyncio_stream_writer_factory(mocker: MockerFixture) -> Callable[[], MagicMock]:
    def factory() -> MagicMock:
        mock = mocker.NonCallableMagicMock(spec=asyncio.StreamWriter)
        mock.is_closing.return_value = False
        mock.can_write_eof.return_value = True
        return mock

    return factory
