# -*- coding: utf-8 -*-

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any, final

from easynetwork.api_sync.client.abc import AbstractNetworkClient
from easynetwork.tools.socket import SocketAddress

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@final
class MockClient(AbstractNetworkClient[Any, Any]):
    def __init__(self, mocker: MockerFixture) -> None:
        super().__init__()
        self.mock_is_closed = mocker.MagicMock(return_value=True)
        self.mock_close = mocker.MagicMock(return_value=None)
        self.mock_recv_packet = mocker.MagicMock()

    def is_closed(self) -> bool:
        return self.mock_is_closed()

    def close(self) -> None:
        return self.mock_close()

    def get_local_address(self) -> SocketAddress:
        raise NotImplementedError

    def get_remote_address(self) -> SocketAddress:
        raise NotImplementedError

    def send_packet(self, packet: Any) -> None:
        raise NotImplementedError

    def recv_packet(self, timeout: float | None = None) -> Any:
        return self.mock_recv_packet(timeout)

    def fileno(self) -> int:
        raise NotImplementedError


class TestAbstractNetworkClient:
    def test____context____close_client_at_end(self, mocker: MockerFixture) -> None:
        # Arrange
        client = MockClient(mocker)

        # Act
        with client:
            client.mock_close.assert_not_called()

        # Assert
        client.mock_close.assert_called_once_with()

    def test____iter_received_packets____yields_available_packets_with_given_timeout(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        now: float = 798546132
        mocker.patch("time.monotonic", return_value=now)
        received_packets_queue = deque([mocker.sentinel.packet_a, mocker.sentinel.packet_b, mocker.sentinel.packet_c])

        def side_effect(timeout: Any) -> Any:
            try:
                return received_packets_queue.popleft()
            except IndexError:
                raise TimeoutError

        client = MockClient(mocker)
        client.mock_recv_packet.side_effect = side_effect

        # Act
        packets = list(client.iter_received_packets(timeout=123456789))

        # Assert
        assert client.mock_recv_packet.mock_calls == [mocker.call(123456789) for _ in range(4)]
        assert packets == [mocker.sentinel.packet_a, mocker.sentinel.packet_b, mocker.sentinel.packet_c]

    @pytest.mark.parametrize("timeout", [123456789, None])
    @pytest.mark.parametrize("error", [OSError])
    def test____iter_received_packets____with_given_timeout_stop_if_an_error_occurs(
        self,
        timeout: int | None,
        error: type[BaseException],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        now: float = 798546132
        mocker.patch("time.monotonic", return_value=now)
        client = MockClient(mocker)
        client.mock_recv_packet.side_effect = [mocker.sentinel.packet_a, error]

        # Act
        packets = list(client.iter_received_packets(timeout=timeout))

        # Assert
        assert client.mock_recv_packet.mock_calls == [mocker.call(timeout) for _ in range(2)]
        assert packets == [mocker.sentinel.packet_a]
