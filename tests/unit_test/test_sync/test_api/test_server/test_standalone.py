from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.servers.standalone_tcp import StandaloneTCPNetworkServer
from easynetwork.servers.standalone_udp import StandaloneUDPNetworkServer
from easynetwork.servers.standalone_unix_datagram import StandaloneUnixDatagramServer
from easynetwork.servers.standalone_unix_stream import StandaloneUnixStreamServer

import pytest

from .....tools import PlatformMarkers

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_asyncio_bootstrap(mocker: MockerFixture) -> MagicMock:
    mock_asyncio_bootstrap = mocker.patch.object(AsyncIOBackend, "bootstrap", return_value=None)
    return mock_asyncio_bootstrap


class TestStandaloneTCPNetworkServer:
    def test____dunder_init____backend____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected either a string literal or a backend instance, got .*$"):
            _ = StandaloneTCPNetworkServer(None, 0, mock_stream_protocol, mock_stream_request_handler, invalid_backend)

    @pytest.mark.parametrize(
        ["init_options", "serve_forever_options"],
        [
            pytest.param(None, None),
            pytest.param({"loop_factory": asyncio.new_event_loop, "debug": False}, None),
            pytest.param(None, {"loop_factory": asyncio.new_event_loop, "debug": False}),
            pytest.param({"loop_factory": asyncio.new_event_loop}, {"debug": False}),
            pytest.param({"loop_factory": asyncio.new_event_loop, "debug": False}, {"debug": True}),
        ],
    )
    def test____serve_forever____runner_options____parameter(
        self,
        init_options: dict[str, Any] | None,
        serve_forever_options: dict[str, Any] | None,
        mock_asyncio_bootstrap: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_runner_options: dict[str, Any] | None
        if init_options:
            if serve_forever_options:
                expected_runner_options = dict(init_options) | dict(serve_forever_options)
            else:
                expected_runner_options = init_options
        else:
            expected_runner_options = serve_forever_options

        server: StandaloneTCPNetworkServer[Any, Any] = StandaloneTCPNetworkServer(
            None,
            9000,
            mock_stream_protocol,
            mock_stream_request_handler,
            runner_options=init_options,
        )

        # Act
        server.serve_forever(runner_options=serve_forever_options)

        # Assert
        mock_asyncio_bootstrap.assert_called_once_with(mocker.ANY, runner_options=expected_runner_options)


class TestStandaloneUDPNetworkServer:
    def test____dunder_init____backend____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected either a string literal or a backend instance, got .*$"):
            _ = StandaloneUDPNetworkServer(None, 0, mock_datagram_protocol, mock_datagram_request_handler, invalid_backend)

    @pytest.mark.parametrize(
        ["init_options", "serve_forever_options"],
        [
            pytest.param(None, None),
            pytest.param({"loop_factory": asyncio.new_event_loop, "debug": False}, None),
            pytest.param(None, {"loop_factory": asyncio.new_event_loop, "debug": False}),
            pytest.param({"loop_factory": asyncio.new_event_loop}, {"debug": False}),
            pytest.param({"loop_factory": asyncio.new_event_loop, "debug": False}, {"debug": True}),
        ],
    )
    def test____serve_forever____runner_options____parameter(
        self,
        init_options: dict[str, Any] | None,
        serve_forever_options: dict[str, Any] | None,
        mock_asyncio_bootstrap: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_runner_options: dict[str, Any] | None
        if init_options:
            if serve_forever_options:
                expected_runner_options = dict(init_options) | dict(serve_forever_options)
            else:
                expected_runner_options = init_options
        else:
            expected_runner_options = serve_forever_options

        server: StandaloneUDPNetworkServer[Any, Any] = StandaloneUDPNetworkServer(
            None,
            9000,
            mock_datagram_protocol,
            mock_datagram_request_handler,
            runner_options=init_options,
        )

        # Act
        server.serve_forever(runner_options=serve_forever_options)

        # Assert
        mock_asyncio_bootstrap.assert_called_once_with(mocker.ANY, runner_options=expected_runner_options)


@PlatformMarkers.skipif_platform_win32
class TestStandaloneUnixStreamServer:
    def test____dunder_init____backend____invalid_value(
        self,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected either a string literal or a backend instance, got .*$"):
            _ = StandaloneUnixStreamServer("/path/to/sock", mock_stream_protocol, mock_stream_request_handler, invalid_backend)

    @pytest.mark.parametrize(
        ["init_options", "serve_forever_options"],
        [
            pytest.param(None, None),
            pytest.param({"loop_factory": asyncio.new_event_loop, "debug": False}, None),
            pytest.param(None, {"loop_factory": asyncio.new_event_loop, "debug": False}),
            pytest.param({"loop_factory": asyncio.new_event_loop}, {"debug": False}),
            pytest.param({"loop_factory": asyncio.new_event_loop, "debug": False}, {"debug": True}),
        ],
    )
    def test____serve_forever____runner_options____parameter(
        self,
        init_options: dict[str, Any] | None,
        serve_forever_options: dict[str, Any] | None,
        mock_asyncio_bootstrap: MagicMock,
        mock_stream_protocol: MagicMock,
        mock_stream_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_runner_options: dict[str, Any] | None
        if init_options:
            if serve_forever_options:
                expected_runner_options = dict(init_options) | dict(serve_forever_options)
            else:
                expected_runner_options = init_options
        else:
            expected_runner_options = serve_forever_options

        server: StandaloneUnixStreamServer[Any, Any] = StandaloneUnixStreamServer(
            "/path/to/sock",
            mock_stream_protocol,
            mock_stream_request_handler,
            runner_options=init_options,
        )

        # Act
        server.serve_forever(runner_options=serve_forever_options)

        # Assert
        mock_asyncio_bootstrap.assert_called_once_with(mocker.ANY, runner_options=expected_runner_options)


@PlatformMarkers.skipif_platform_win32
class TestStandaloneUnixDatagramServer:
    def test____dunder_init____backend____invalid_value(
        self,
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        invalid_backend = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected either a string literal or a backend instance, got .*$"):
            _ = StandaloneUnixDatagramServer(
                "/path/to/sock",
                mock_datagram_protocol,
                mock_datagram_request_handler,
                invalid_backend,
            )

    @pytest.mark.parametrize(
        ["init_options", "serve_forever_options"],
        [
            pytest.param(None, None),
            pytest.param({"loop_factory": asyncio.new_event_loop, "debug": False}, None),
            pytest.param(None, {"loop_factory": asyncio.new_event_loop, "debug": False}),
            pytest.param({"loop_factory": asyncio.new_event_loop}, {"debug": False}),
            pytest.param({"loop_factory": asyncio.new_event_loop, "debug": False}, {"debug": True}),
        ],
    )
    def test____serve_forever____runner_options____parameter(
        self,
        init_options: dict[str, Any] | None,
        serve_forever_options: dict[str, Any] | None,
        mock_asyncio_bootstrap: MagicMock,
        mock_datagram_protocol: MagicMock,
        mock_datagram_request_handler: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        expected_runner_options: dict[str, Any] | None
        if init_options:
            if serve_forever_options:
                expected_runner_options = dict(init_options) | dict(serve_forever_options)
            else:
                expected_runner_options = init_options
        else:
            expected_runner_options = serve_forever_options

        server: StandaloneUnixDatagramServer[Any, Any] = StandaloneUnixDatagramServer(
            "/path/to/sock",
            mock_datagram_protocol,
            mock_datagram_request_handler,
            runner_options=init_options,
        )

        # Act
        server.serve_forever(runner_options=serve_forever_options)

        # Assert
        mock_asyncio_bootstrap.assert_called_once_with(mocker.ANY, runner_options=expected_runner_options)
