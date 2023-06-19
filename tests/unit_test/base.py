# -*- coding: utf-8 -*-

from __future__ import annotations

from socket import AF_INET6
from typing import TYPE_CHECKING, Any

from easynetwork.tools.socket import AddressFamily

from ._utils import get_all_socket_families

if TYPE_CHECKING:
    from unittest.mock import MagicMock

SUPPORTED_FAMILIES: tuple[str, ...] = tuple(sorted(AddressFamily.__members__))
UNSUPPORTED_FAMILIES: tuple[str, ...] = tuple(sorted(get_all_socket_families().difference(SUPPORTED_FAMILIES)))


class BaseTestSocket:
    @staticmethod
    def set_local_address_to_socket_mock(
        mock_socket: MagicMock,
        socket_family: int,
        address: tuple[str, int] | None,
    ) -> None:
        additional_address_components: tuple[Any, ...] = (0, 0) if socket_family == AF_INET6 else ()

        if address is None:
            if socket_family == AF_INET6:
                address = ("::", 0)
            else:
                address = ("0.0.0.0", 0)

        mock_socket.getsockname.return_value = address + additional_address_components

    @staticmethod
    def set_remote_address_to_socket_mock(
        mock_socket: MagicMock,
        socket_family: int,
        address: tuple[str, int],
    ) -> None:
        additional_address_components: tuple[Any, ...] = (0, 0) if socket_family == AF_INET6 else ()

        mock_socket.getpeername.return_value = address + additional_address_components

    @staticmethod
    def configure_socket_mock_to_raise_ENOTCONN(mock_socket: MagicMock) -> OSError:
        import errno
        import os

        ## Exception raised by socket.getpeername() if socket.connect() was not called before
        enotconn_exception = OSError(errno.ENOTCONN, os.strerror(errno.ENOTCONN))
        mock_socket.getpeername.side_effect = enotconn_exception
        return enotconn_exception
