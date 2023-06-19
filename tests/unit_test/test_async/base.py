# -*- coding: utf-8 -*-

from __future__ import annotations

from socket import AF_INET6
from typing import TYPE_CHECKING

from easynetwork.tools.socket import new_socket_address

if TYPE_CHECKING:
    from unittest.mock import MagicMock

from ..base import BaseTestSocket


class BaseTestAsyncSocketAdapter(BaseTestSocket):
    @staticmethod
    def set_local_address_to_async_socket_adapter_mock(
        mock_async_socket_adapter: MagicMock,
        socket_family: int,
        address: tuple[str, int] | None,
    ) -> None:
        if address is None:
            if socket_family == AF_INET6:
                address = ("::", 0)
            else:
                address = ("0.0.0.0", 0)
        mock_async_socket_adapter.get_local_address.return_value = new_socket_address(address, socket_family)

    @staticmethod
    def set_remote_address_to_async_socket_adapter_mock(
        mock_async_socket_adapter: MagicMock,
        socket_family: int,
        address: tuple[str, int],
    ) -> None:
        mock_async_socket_adapter.get_remote_address.return_value = new_socket_address(address, socket_family)
