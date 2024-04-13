from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import DatagramProtocolParseError, DeserializeError, UnsupportedOperation
from easynetwork.lowlevel.api_async.endpoints.datagram import AsyncDatagramEndpoint
from easynetwork.lowlevel.api_async.transports.abc import (
    AsyncDatagramReadTransport,
    AsyncDatagramTransport,
    AsyncDatagramWriteTransport,
)
from easynetwork.lowlevel.std_asyncio.backend import AsyncIOBackend

import pytest

from ....base import BaseTestWithDatagramProtocol
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncDatagramEndpoint(BaseTestWithDatagramProtocol):
    @pytest.fixture(params=[AsyncDatagramReadTransport, AsyncDatagramWriteTransport, AsyncDatagramTransport])
    @staticmethod
    def mock_datagram_transport(
        asyncio_backend: AsyncIOBackend,
        request: pytest.FixtureRequest,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=request.param, backend=asyncio_backend)

    @pytest.fixture
    @staticmethod
    def endpoint(mock_datagram_transport: MagicMock, mock_datagram_protocol: MagicMock) -> AsyncDatagramEndpoint[Any, Any]:
        return AsyncDatagramEndpoint(mock_datagram_transport, mock_datagram_protocol)

    async def test____dunder_init____invalid_transport(
        self,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected an AsyncDatagramTransport object, got .*$"):
            _ = AsyncDatagramEndpoint(mock_invalid_transport, mock_datagram_protocol)

    async def test____dunder_init____invalid_protocol(
        self,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = AsyncDatagramEndpoint(mock_datagram_transport, mock_invalid_protocol)

    @pytest.mark.parametrize("transport_closed", [False, True])
    async def test____is_closing____default(
        self,
        endpoint: AsyncDatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
        transport_closed: bool,
    ) -> None:
        # Arrange
        mock_datagram_transport.is_closing.assert_not_called()
        mock_datagram_transport.is_closing.return_value = transport_closed

        # Act
        state = endpoint.is_closing()

        # Assert
        mock_datagram_transport.is_closing.assert_called_once_with()
        assert state is transport_closed

    async def test____aclose____default(
        self,
        endpoint: AsyncDatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_transport.aclose.assert_not_called()

        # Act
        await endpoint.aclose()

        # Assert
        mock_datagram_transport.aclose.assert_awaited_once_with()

    async def test____extra_attributes____default(
        self,
        endpoint: AsyncDatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_transport.extra_attributes = {mocker.sentinel.name: lambda: mocker.sentinel.extra_info}

        # Act
        value = endpoint.extra(mocker.sentinel.name)

        # Assert
        assert value is mocker.sentinel.extra_info

    async def test____send_packet____send_bytes_to_transport(
        self,
        endpoint: AsyncDatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        with contextlib.suppress(AttributeError):
            mock_datagram_transport.send.return_value = None

        # Act
        with (
            pytest.raises(UnsupportedOperation, match=r"^transport does not support sending data$")
            if mock_datagram_transport.__class__ not in (AsyncDatagramWriteTransport, AsyncDatagramTransport)
            else contextlib.nullcontext()
        ):
            await endpoint.send_packet(mocker.sentinel.packet)

        # Assert
        if mock_datagram_transport.__class__ in (AsyncDatagramWriteTransport, AsyncDatagramTransport):
            mock_datagram_protocol.make_datagram.assert_called_once_with(mocker.sentinel.packet)
            mock_datagram_transport.send.assert_awaited_once_with(b"packet")
        else:
            mock_datagram_protocol.make_datagram.assert_not_called()

    @pytest.mark.parametrize("mock_datagram_transport", [AsyncDatagramWriteTransport], indirect=True)
    async def test____send_packet____protocol_crashed(
        self,
        endpoint: AsyncDatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_datagram_transport.send.return_value = None
        expected_error = Exception("Error")
        mock_datagram_protocol.make_datagram.side_effect = expected_error

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.make_datagram\(\) crashed$") as exc_info:
            await endpoint.send_packet(mocker.sentinel.packet)

        # Assert
        assert exc_info.value.__cause__ is expected_error
        mock_datagram_transport.send.assert_not_called()

    async def test____recv_packet____receive_bytes_from_transport(
        self,
        endpoint: AsyncDatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        with contextlib.suppress(AttributeError):
            mock_datagram_transport.recv.side_effect = [b"packet"]

        # Act
        packet: Any = mocker.sentinel.packet_not_received
        with (
            pytest.raises(UnsupportedOperation, match=r"^transport does not support receiving data$")
            if mock_datagram_transport.__class__ not in (AsyncDatagramReadTransport, AsyncDatagramTransport)
            else contextlib.nullcontext()
        ):
            packet = await endpoint.recv_packet()

        # Assert
        if mock_datagram_transport.__class__ in (AsyncDatagramReadTransport, AsyncDatagramTransport):
            mock_datagram_transport.recv.assert_awaited_once_with()
            mock_datagram_protocol.build_packet_from_datagram.assert_called_once_with(b"packet")
            assert packet is mocker.sentinel.packet
        else:
            mock_datagram_protocol.build_packet_from_datagram.assert_not_called()
            assert packet is mocker.sentinel.packet_not_received

    @pytest.mark.parametrize("mock_datagram_transport", [AsyncDatagramReadTransport], indirect=True)
    async def test____recv_packet____protocol_parse_error(
        self,
        endpoint: AsyncDatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_transport.recv.side_effect = [b"packet"]
        expected_error = DatagramProtocolParseError(DeserializeError("Invalid packet"))
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(DatagramProtocolParseError) as exc_info:
            await endpoint.recv_packet()

        # Assert
        assert exc_info.value is expected_error

    @pytest.mark.parametrize("mock_datagram_transport", [AsyncDatagramReadTransport], indirect=True)
    async def test____recv_packet____protocol_crashed(
        self,
        endpoint: AsyncDatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        mock_datagram_transport.recv.side_effect = [b"packet"]
        expected_error = Exception("Error")
        mock_datagram_protocol.build_packet_from_datagram.side_effect = expected_error

        # Act
        with pytest.raises(RuntimeError, match=r"^protocol\.build_packet_from_datagram\(\) crashed$") as exc_info:
            await endpoint.recv_packet()

        # Assert
        assert exc_info.value.__cause__ is expected_error

    async def test____get_backend____returns_inner_transport_backend(
        self,
        endpoint: AsyncDatagramEndpoint[Any, Any],
        mock_datagram_transport: MagicMock,
    ) -> None:
        # Arrange

        # Act & Assert
        assert endpoint.backend() is mock_datagram_transport.backend()
