# -*- coding: Utf-8 -*-

from __future__ import annotations

from socket import AF_INET, IPPROTO_TCP, IPPROTO_UDP, SOCK_DGRAM, SOCK_STREAM, socket as Socket
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

import random

random.seed(42)  # Fully deterministic random output


@pytest.fixture
def mock_socket_cls(mocker: MockerFixture) -> MagicMock:
    socket = mocker.patch("socket.socket", autospec=True)
    return socket


@pytest.fixture
def mock_tcp_socket(mocker: MockerFixture) -> MagicMock:
    mock_socket = mocker.MagicMock(spec=Socket())
    mock_socket.family = AF_INET
    mock_socket.type = SOCK_STREAM
    mock_socket.proto = IPPROTO_TCP
    return mock_socket


@pytest.fixture
def mock_udp_socket(mocker: MockerFixture) -> MagicMock:
    mock_socket = mocker.MagicMock(spec=Socket())
    mock_socket.family = AF_INET
    mock_socket.type = SOCK_DGRAM
    mock_socket.proto = IPPROTO_UDP
    return mock_socket
