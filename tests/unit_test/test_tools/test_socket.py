# -*- coding: Utf-8 -*-

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Any

from easynetwork.tools.socket import (
    AddressFamily,
    IPv4SocketAddress,
    IPv6SocketAddress,
    SocketAddress,
    SocketProxy,
    new_socket_address,
)

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.parametrize("name", list(AddressFamily.__members__))
def test____AddressFamily____constants(name: str) -> None:
    # Arrange
    enum = AddressFamily[name]
    constant = getattr(socket, name)

    # Act & Assert
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


class TestSocketProxy:
    @pytest.fixture
    @staticmethod
    def mock_new_socket_address(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("easynetwork.tools.socket.new_socket_address", autospec=True)

    @pytest.mark.parametrize("prop", ["family", "type", "proto"])
    def test____property____access(self, prop: str, mock_tcp_socket: MagicMock) -> None:
        # Arrange
        expected_value = getattr(mock_tcp_socket, prop)

        # Act
        socket_proxy = SocketProxy(mock_tcp_socket)
        prop_value = getattr(socket_proxy, prop)

        # Assert
        assert prop_value == expected_value

    def test____fileno____sub_call(self, mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        mock_tcp_socket.fileno.return_value = mocker.sentinel.fd
        socket_proxy = SocketProxy(mock_tcp_socket)

        # Act
        fd = socket_proxy.fileno()

        # Assert
        mock_tcp_socket.fileno.assert_called_once_with()
        assert fd is mocker.sentinel.fd

    def test____dup____sub_call(self, mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        mock_tcp_socket.dup.return_value = mocker.sentinel.dup_socket
        socket_proxy = SocketProxy(mock_tcp_socket)

        # Act
        socket = socket_proxy.dup()

        # Assert
        mock_tcp_socket.dup.assert_called_once_with()
        assert socket is mocker.sentinel.dup_socket

    def test____get_inheritable____sub_call(self, mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        mock_tcp_socket.get_inheritable.return_value = mocker.sentinel.status
        socket_proxy = SocketProxy(mock_tcp_socket)

        # Act
        status = socket_proxy.get_inheritable()

        # Assert
        mock_tcp_socket.get_inheritable.assert_called_once_with()
        assert status is mocker.sentinel.status

    @pytest.mark.parametrize("nb_args", [2, 3], ids=lambda nb: f"{nb} arguments")
    def test____getsockopt____sub_call(self, nb_args: int, mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        mock_tcp_socket.getsockopt.return_value = mocker.sentinel.value
        socket_proxy = SocketProxy(mock_tcp_socket)
        args: tuple[Any, ...] = (mocker.sentinel.level, mocker.sentinel.optname)
        if nb_args == 3:
            args += (mocker.sentinel.buflen,)

        # Act
        value = socket_proxy.getsockopt(*args)

        # Assert
        mock_tcp_socket.getsockopt.assert_called_once_with(*args)
        assert value is mocker.sentinel.value

    @pytest.mark.parametrize("nb_args", [3, 4], ids=lambda nb: f"{nb} arguments")
    def test____setsockopt____sub_call(self, nb_args: int, mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        socket_proxy = SocketProxy(mock_tcp_socket)
        args: tuple[Any, ...] = (mocker.sentinel.level, mocker.sentinel.optname, mocker.sentinel.value)
        if nb_args == 4:
            args += (mocker.sentinel.optlen,)

        # Act
        socket_proxy.setsockopt(*args)

        # Assert
        mock_tcp_socket.setsockopt.assert_called_once_with(*args)

    @pytest.mark.parametrize("method", ["getsockname", "getpeername"])
    def test____socket_address____sub_call(
        self,
        method: str,
        mock_tcp_socket: MagicMock,
        mock_new_socket_address: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        socket_proxy = SocketProxy(mock_tcp_socket)
        getattr(mock_tcp_socket, method).return_value = mocker.sentinel.address_to_convert
        mock_new_socket_address.return_value = mocker.sentinel.converted_address

        # Act
        address = getattr(socket_proxy, method)()

        # Assert
        getattr(mock_tcp_socket, method).assert_called_once_with()
        mock_new_socket_address.assert_called_once_with(mocker.sentinel.address_to_convert, mock_tcp_socket.family)
        assert address is mocker.sentinel.converted_address
