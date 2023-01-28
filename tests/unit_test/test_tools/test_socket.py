# -*- coding: Utf-8 -*-

from __future__ import annotations

import socket
from typing import Any

from easynetwork.tools.socket import AddressFamily, IPv4SocketAddress, IPv6SocketAddress, SocketAddress, new_socket_address

import pytest


@pytest.mark.parametrize("name", list(AddressFamily.__members__))
def test____AddressFamily____constants(name: str) -> None:
    # Arrange
    enum = AddressFamily[name]
    constant = getattr(socket, name)

    # Act

    # Assert
    assert enum.value == constant


class TestSocketAddress:
    @pytest.mark.parametrize("address", [IPv4SocketAddress("127.0.0.1", 3000), IPv6SocketAddress("127.0.0.1", 3000)])
    def test____for_connection____return_host_port_tuple(self, address: SocketAddress) -> None:
        # Arrange

        # Act
        host, port = address.for_connection()

        # Assert
        assert host is address.host
        assert port is address.port

    @pytest.mark.parametrize(
        ["address", "family", "expected_type"],
        [
            pytest.param(("127.0.0.1", 3000), AddressFamily.AF_INET, IPv4SocketAddress),
            pytest.param(("127.0.0.1", 3000), AddressFamily.AF_INET6, IPv6SocketAddress),
            pytest.param(("127.0.0.1", 3000, 0, 0), AddressFamily.AF_INET6, IPv6SocketAddress),
        ],
    )
    def test____new_socket_address____factory(
        self,
        address: tuple[Any, ...],
        family: AddressFamily,
        expected_type: type[SocketAddress],
    ) -> None:
        # Arrange

        # Act
        socket_address = new_socket_address(address, family)

        # Assert
        assert isinstance(socket_address, expected_type)
