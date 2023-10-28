from __future__ import annotations

from socket import AF_INET, AF_INET6
from typing import TYPE_CHECKING

from easynetwork.lowlevel.socket import AddressFamily

from ._utils import get_all_socket_families

if TYPE_CHECKING:
    from unittest.mock import MagicMock

SUPPORTED_FAMILIES: tuple[str, ...] = tuple(sorted(AddressFamily.__members__))
UNSUPPORTED_FAMILIES: tuple[str, ...] = tuple(sorted(get_all_socket_families().difference(SUPPORTED_FAMILIES)))


class BaseTestSocket:
    @classmethod
    def get_local_addr_from_family(cls, socket_family: int) -> str:
        if socket_family == AF_INET6:
            address = "::1"
        else:
            assert socket_family == AF_INET
            address = "127.0.0.1"
        return address

    @classmethod
    def get_any_addr_from_family(cls, socket_family: int) -> str:
        if socket_family == AF_INET6:
            address = "::"
        else:
            assert socket_family == AF_INET
            address = "0.0.0.0"
        return address

    @classmethod
    def get_resolved_addr_format(
        cls,
        address: tuple[str, int],
        socket_family: int,
    ) -> tuple[str, int] | tuple[str, int, int, int]:
        if socket_family == AF_INET6:
            return address + (0, 0)
        return address

    @classmethod
    def get_resolved_local_addr(cls, socket_family: int) -> tuple[str, int] | tuple[str, int, int, int]:
        return cls.get_resolved_addr_format((cls.get_local_addr_from_family(socket_family), 0), socket_family)

    @classmethod
    def get_resolved_any_addr(cls, socket_family: int) -> tuple[str, int] | tuple[str, int, int, int]:
        return cls.get_resolved_addr_format((cls.get_any_addr_from_family(socket_family), 0), socket_family)

    @classmethod
    def set_local_address_to_socket_mock(
        cls,
        mock_socket: MagicMock,
        socket_family: int,
        address: tuple[str, int] | None,
    ) -> None:
        if address is None:
            full_address = cls.get_resolved_local_addr(socket_family)
        else:
            full_address = cls.get_resolved_addr_format(address, socket_family)

        mock_socket.getsockname.return_value = full_address

    @classmethod
    def set_remote_address_to_socket_mock(
        cls,
        mock_socket: MagicMock,
        socket_family: int,
        address: tuple[str, int],
    ) -> None:
        mock_socket.getpeername.return_value = cls.get_resolved_addr_format(address, socket_family)

    @classmethod
    def configure_socket_mock_to_raise_ENOTCONN(cls, mock_socket: MagicMock) -> OSError:
        import errno
        import os

        ## Exception raised by socket.getpeername() if socket.connect() was not called before
        enotconn_exception = OSError(errno.ENOTCONN, os.strerror(errno.ENOTCONN))
        mock_socket.getpeername.side_effect = enotconn_exception
        return enotconn_exception
