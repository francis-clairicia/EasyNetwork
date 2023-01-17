# -*- coding: Utf-8 -*-

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Any

from easynetwork.tools.socket import (
    AddressFamily,
    IPv4SocketAddress,
    IPv6SocketAddress,
    ShutdownFlag,
    SocketAddress,
    guess_best_recv_size,
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

    # Act

    # Assert
    assert enum.value == constant


@pytest.mark.parametrize("name", list(ShutdownFlag.__members__))
def test____ShutdownFlag_____constants(name: str) -> None:
    # Arrange
    enum = ShutdownFlag[name]
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


def test____guess_best_recv_size____return_socket_file_blocksize(mock_tcp_socket: MagicMock, mocker: MockerFixture) -> None:
    # Arrange
    mock_tcp_socket.fileno.return_value = mocker.sentinel.fileno
    mock_os_fstat = mocker.patch("os.fstat")
    mock_stat: MagicMock = mock_os_fstat.return_value
    mock_stat.st_blksize = 123456789

    # Act
    best_recv_size: int = guess_best_recv_size(mock_tcp_socket)

    # Assert
    mock_tcp_socket.fileno.assert_called_once_with()
    mock_os_fstat.assert_called_once_with(mocker.sentinel.fileno)
    assert best_recv_size == 123456789


@pytest.mark.parametrize(
    "blksize",
    [
        pytest.param(0, id="null value"),
        pytest.param(-1, id="negative value"),
        pytest.param(None, id="undefined attribute"),
    ],
)
def test____guess_best_recv_size____return_io_default_buffer_size_if_blocksize_is_undefined(
    blksize: int | None,
    mock_tcp_socket: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    mock_stat: MagicMock = mocker.patch("os.fstat").return_value
    if blksize is not None:
        mock_stat.st_blksize = blksize
    else:
        del mock_stat.st_blksize
    mocker.patch("io.DEFAULT_BUFFER_SIZE", mocker.sentinel.DEFAULT_BUFFER_SIZE)

    # Act
    best_recv_size: int = guess_best_recv_size(mock_tcp_socket)

    # Assert
    assert best_recv_size is mocker.sentinel.DEFAULT_BUFFER_SIZE


def test____guess_best_recv_size____return_io_default_buffer_size_if_fstat_does_not_support_socket_fd(
    mock_tcp_socket: MagicMock,
    mocker: MockerFixture,
) -> None:
    # Arrange
    mock_os_fstat = mocker.patch("os.fstat")
    mock_os_fstat.side_effect = OSError
    mocker.patch("io.DEFAULT_BUFFER_SIZE", mocker.sentinel.DEFAULT_BUFFER_SIZE)

    # Act
    best_recv_size: int = guess_best_recv_size(mock_tcp_socket)

    # Assert
    assert best_recv_size is mocker.sentinel.DEFAULT_BUFFER_SIZE


def test____guess_best_recv_size____invalid_socket_type(mock_udp_socket: MagicMock) -> None:
    # Arrange

    # Act & Assert
    with pytest.raises(ValueError, match=r"^Unsupported socket type$"):
        _ = guess_best_recv_size(mock_udp_socket)
