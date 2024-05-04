from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel.api_sync.endpoints.datagram import DatagramReceiverEndpoint
from easynetwork.lowlevel.api_sync.transports.abc import DatagramReadTransport

import pytest

from ....mock_tools import make_transport_mock
from .base import BaseEndpointReceiveTests

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestDatagramReceiverEndpoint(BaseEndpointReceiveTests):
    @pytest.fixture
    @staticmethod
    def mock_datagram_transport(mocker: MockerFixture) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=DatagramReadTransport)

    @pytest.fixture
    @staticmethod
    def endpoint(
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> Iterator[DatagramReceiverEndpoint[Any]]:
        endpoint: DatagramReceiverEndpoint[Any] = DatagramReceiverEndpoint(mock_datagram_transport, mock_datagram_protocol)
        with endpoint:
            yield endpoint

    def test____dunder_init____invalid_transport(
        self,
        mock_datagram_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_transport = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramReadTransport object, got .*$"):
            _ = DatagramReceiverEndpoint(mock_invalid_transport, mock_datagram_protocol)

    def test____dunder_init____invalid_protocol(
        self,
        mock_datagram_transport: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_invalid_protocol = mocker.NonCallableMagicMock(spec=object)

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Expected a DatagramProtocol object, got .*$"):
            _ = DatagramReceiverEndpoint(mock_datagram_transport, mock_invalid_protocol)

    def test____dunder_del____ResourceWarning(
        self,
        mock_datagram_transport: MagicMock,
        mock_datagram_protocol: MagicMock,
    ) -> None:
        # Arrange
        endpoint: DatagramReceiverEndpoint[Any] = DatagramReceiverEndpoint(mock_datagram_transport, mock_datagram_protocol)

        # Act & Assert
        with pytest.warns(ResourceWarning, match=r"^unclosed endpoint .+$"):
            del endpoint

        mock_datagram_transport.close.assert_called()
