# -*- coding: Utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING

from easynetwork.tools.socket import new_socket_address

if TYPE_CHECKING:
    from unittest.mock import MagicMock


class BaseTestClient:
    @staticmethod
    def set_local_address_to_socket_mock(
        mock_socket: MagicMock,
        socket_family: int,
        address: tuple[str, int],
    ) -> None:
        mock_socket.getsockname.return_value = new_socket_address(address, socket_family)

    @staticmethod
    def set_remote_address_to_socket_mock(
        mock_socket: MagicMock,
        socket_family: int,
        address: tuple[str, int],
    ) -> None:
        mock_socket.getpeername.return_value = new_socket_address(address, socket_family)
