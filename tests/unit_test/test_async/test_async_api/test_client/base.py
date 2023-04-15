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
        method_name: str = "getsockname",
    ) -> None:
        getattr(mock_socket, method_name).return_value = new_socket_address(address, socket_family)

    @staticmethod
    def set_remote_address_to_socket_mock(
        mock_socket: MagicMock,
        socket_family: int,
        address: tuple[str, int],
        method_name: str = "getpeername",
    ) -> None:
        getattr(mock_socket, method_name).return_value = new_socket_address(address, socket_family)

    @staticmethod
    def configure_socket_mock_to_raise_ENOTCONN(mock_socket: MagicMock) -> OSError:
        import errno
        import os

        ## Exception raised by socket.getpeername() if socket.connect() was not called before
        enotconn_exception = OSError(errno.ENOTCONN, os.strerror(errno.ENOTCONN))
        mock_socket.getpeername.side_effect = enotconn_exception
        return enotconn_exception
