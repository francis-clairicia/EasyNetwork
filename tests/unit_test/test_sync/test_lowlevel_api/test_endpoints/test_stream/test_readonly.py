from __future__ import annotations

import math
import warnings
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel.api_sync.endpoints.stream import StreamReceiverEndpoint
from easynetwork.lowlevel.api_sync.transports.abc import BufferedStreamReadTransport, StreamReadTransport
from easynetwork.warnings import ManualBufferAllocationWarning

import pytest

from ....mock_tools import make_transport_mock
from .base import BaseEndpointReceiveTests, pytest_mark_ignore_manual_buffer_allocation_warning

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestStreamReceiverEndpoint(BaseEndpointReceiveTests):
    @pytest.fixture(
        params=[
            pytest.param("recv_data", marks=pytest_mark_ignore_manual_buffer_allocation_warning),
            pytest.param("recv_buffer"),
        ]
    )
    @staticmethod
    def mock_stream_transport(request: pytest.FixtureRequest, mocker: MockerFixture) -> MagicMock:
        match request.param:
            case "recv_data":
                return make_transport_mock(mocker=mocker, spec=StreamReadTransport)
            case "recv_buffer":
                return make_transport_mock(mocker=mocker, spec=BufferedStreamReadTransport)
            case _:
                pytest.fail("Invalid stream transport parameter")

    @pytest.fixture
    @staticmethod
    def endpoint(
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> Iterator[StreamReceiverEndpoint[Any]]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ManualBufferAllocationWarning)
            endpoint: StreamReceiverEndpoint[Any] = StreamReceiverEndpoint(
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
            )
        with endpoint:
            yield endpoint

    def test____dunder_init____invalid_transport(
        self,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamReadTransport object, got .*$"):
            _ = StreamReceiverEndpoint(mock_invalid_transport, mock_stream_protocol, max_recv_size)

    def test____dunder_init____invalid_protocol(
        self,
        mock_stream_transport: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a StreamProtocol object, got .*$"):
            _ = StreamReceiverEndpoint(mock_stream_transport, mock_invalid_protocol, max_recv_size)

    @pytest.mark.parametrize("max_recv_size", [1, 2**16], ids=lambda p: f"max_recv_size=={p}")
    def test____dunder_init____max_recv_size____valid_value(
        self,
        request: pytest.FixtureRequest,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act
        endpoint: StreamReceiverEndpoint[Any] = StreamReceiverEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)
        request.addfinalizer(endpoint.close)

        # Assert
        assert endpoint.max_recv_size == max_recv_size

    @pytest.mark.parametrize("max_recv_size", [0, -1, 10.4], ids=lambda p: f"max_recv_size=={p}")
    def test____dunder_init____max_recv_size____invalid_value(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: Any,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r"^'max_recv_size' must be a strictly positive integer$"):
            _ = StreamReceiverEndpoint(mock_stream_transport, mock_stream_protocol, max_recv_size)

    @pytest.mark.parametrize("manual_buffer_allocation", ["unknown", ""], ids=lambda p: f"manual_buffer_allocation=={p!r}")
    def test____dunder_init____manual_buffer_allocation____invalid_value(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        manual_buffer_allocation: Any,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(ValueError, match=r'^"manual_buffer_allocation" must be "try", "no" or "force"$'):
            _ = StreamReceiverEndpoint(
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation=manual_buffer_allocation,
            )

    def test____dunder_del____ResourceWarning(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange
        endpoint: StreamReceiverEndpoint[Any] = StreamReceiverEndpoint(
            mock_stream_transport,
            mock_stream_protocol,
            max_recv_size,
            manual_buffer_allocation="no",
        )

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed endpoint .+$"):
            del endpoint

        mock_stream_transport.close.assert_called()

    # NOTE: The cases where recv_packet() uses transport.recv() or transport.recv_into() when manual_buffer_allocation == "try"
    #       are implicitly tested above, because this is the default behavior.

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    def test____manual_buffer_allocation____try____but_stream_protocol_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with warnings.catch_warnings():
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            endpoint = StreamReceiverEndpoint[Any](
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation="try",
            )

        endpoint.close()

    @pytest.mark.parametrize("mock_stream_transport", ["recv_data"], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____manual_buffer_allocation____try____but_stream_transport_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with pytest.warns(
            ManualBufferAllocationWarning,
            match=r'^The transport implementation .+ does not implement BufferedStreamReadTransport interface\. Consider explicitly setting the "manual_buffer_allocation" strategy to "no"\.$',
        ):
            endpoint = StreamReceiverEndpoint[Any](
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation="try",
            )

        endpoint.close()

    def test____manual_buffer_allocation____disabled(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_stream_transport.recv.side_effect = [b"packet\n"]

        # Act
        endpoint: StreamReceiverEndpoint[Any]
        with warnings.catch_warnings():
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            endpoint = StreamReceiverEndpoint(
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation="no",
            )
        packet = endpoint.recv_packet()
        endpoint.close()

        # Assert
        mock_stream_transport.recv.assert_called_once_with(max_recv_size, math.inf)
        if hasattr(mock_stream_transport, "recv_into"):
            mock_stream_transport.recv_into.assert_not_called()
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("stream_protocol_mode", ["data"], indirect=True)
    def test____manual_buffer_allocation____force____but_stream_protocol_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with (
            pytest.raises(UnsupportedOperation, match=r"^This protocol does not support the buffer API$") as exc_info,
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            _ = StreamReceiverEndpoint(
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation="force",
            )

        assert exc_info.value.__notes__ == [
            'Consider setting the "manual_buffer_allocation" strategy to "no"',
        ]

    @pytest.mark.parametrize("mock_stream_transport", ["recv_data"], indirect=True)
    @pytest.mark.parametrize("stream_protocol_mode", ["buffer"], indirect=True)
    def test____manual_buffer_allocation____force____but_stream_transport_does_not_support_it(
        self,
        mock_stream_transport: MagicMock,
        mock_stream_protocol: MagicMock,
        max_recv_size: int,
    ) -> None:
        # Arrange

        # Act & Assert
        with (
            pytest.raises(
                UnsupportedOperation,
                match=r"^The transport implementation .+ does not implement BufferedStreamReadTransport interface$",
            ) as exc_info,
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", ManualBufferAllocationWarning)
            _ = StreamReceiverEndpoint(
                mock_stream_transport,
                mock_stream_protocol,
                max_recv_size,
                manual_buffer_allocation="force",
            )

        assert exc_info.value.__notes__ == [
            'Consider setting the "manual_buffer_allocation" strategy to "no"',
        ]
