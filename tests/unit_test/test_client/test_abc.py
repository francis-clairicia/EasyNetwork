# -*- coding: Utf-8 -*-

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any, TypeVar, final, overload

from easynetwork.client.abc import AbstractNetworkClient
from easynetwork.tools.socket import SocketAddress

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

_T = TypeVar("_T")


@final
class _ClientForTest(AbstractNetworkClient[Any, Any]):
    def is_closed(self) -> bool:
        return True

    def close(self) -> None:
        raise NotImplementedError

    def get_local_address(self) -> SocketAddress:
        raise NotImplementedError

    def get_remote_address(self) -> SocketAddress:
        raise NotImplementedError

    def send_packet(self, packet: Any) -> None:
        raise NotImplementedError

    def recv_packet(self) -> Any:
        raise NotImplementedError

    @overload
    def recv_packet_no_block(self, *, timeout: float = ...) -> Any:
        ...

    @overload
    def recv_packet_no_block(self, *, default: _T, timeout: float = ...) -> Any | _T:
        ...

    def recv_packet_no_block(self, *, default: _T = ..., timeout: float = ...) -> Any | _T:
        raise NotImplementedError

    def fileno(self) -> int:
        raise NotImplementedError


class TestAbstractNetworkClient:
    def test____context____close_client_at_end(self, mocker: MockerFixture) -> None:
        # Arrange
        client = _ClientForTest()
        mock_close = mocker.patch.object(client, "close")

        # Act
        with client:
            mock_close.assert_not_called()

        # Assert
        mock_close.assert_called_once_with()

    def test____iter_received_packets____yields_available_packets_with_given_timeout(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        received_packets_queue = deque([mocker.sentinel.packet_a, mocker.sentinel.packet_b, mocker.sentinel.packet_c])

        def side_effect(timeout: Any, default: Any) -> Any:
            try:
                return received_packets_queue.popleft()
            except IndexError:
                return default

        client = _ClientForTest()
        mock_recv_packet_no_block = mocker.patch.object(client, "recv_packet_no_block", side_effect=side_effect)

        # Act
        packets = list(client.iter_received_packets(timeout=123456789))

        assert mock_recv_packet_no_block.mock_calls == [mocker.call(timeout=123456789, default=mocker.ANY) for _ in range(4)]
        assert packets == [mocker.sentinel.packet_a, mocker.sentinel.packet_b, mocker.sentinel.packet_c]

    def test____iter_received_packets____wait_and_yield_if_timeout_is_None(
        self,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        client = _ClientForTest()
        mock_recv_packet = mocker.patch.object(client, "recv_packet", side_effect=[mocker.sentinel.packet])

        # Act
        packet = next(client.iter_received_packets(timeout=None))

        mock_recv_packet.assert_called_once_with()
        assert packet is mocker.sentinel.packet
