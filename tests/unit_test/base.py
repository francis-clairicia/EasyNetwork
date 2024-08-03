from __future__ import annotations

from collections.abc import Generator
from socket import AF_INET, AF_INET6
from typing import TYPE_CHECKING, Any

import pytest

from ._utils import get_all_socket_families

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

SUPPORTED_FAMILIES: tuple[str, ...] = tuple(sorted(("AF_INET", "AF_INET6")))
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

        mock_socket.getsockname.side_effect = None
        mock_socket.getsockname.return_value = full_address

    @classmethod
    def set_remote_address_to_socket_mock(
        cls,
        mock_socket: MagicMock,
        socket_family: int,
        address: tuple[str, int],
    ) -> None:
        mock_socket.getpeername.side_effect = None
        mock_socket.getpeername.return_value = cls.get_resolved_addr_format(address, socket_family)

    @classmethod
    def configure_socket_mock_to_raise_ENOTCONN(cls, mock_socket: MagicMock) -> OSError:
        import errno
        import os

        ## Exception raised by socket.getpeername() if socket.connect() was not called before
        enotconn_exception = OSError(errno.ENOTCONN, os.strerror(errno.ENOTCONN))
        mock_socket.getpeername.side_effect = enotconn_exception
        mock_socket.getpeername.return_value = None
        return enotconn_exception


class MixinTestSocketSendMSG:
    @pytest.fixture(autouse=True)
    @staticmethod
    def SC_IOV_MAX(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> int:
        try:
            value: int = request.param
        except AttributeError:
            value = 1024
        monkeypatch.setattr("easynetwork.lowlevel.constants.SC_IOV_MAX", value)
        return value


class BaseTestWithStreamProtocol:
    @pytest.fixture
    @staticmethod
    def mock_buffered_stream_protocol(
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> MagicMock:
        def generate_chunks_side_effect(packet: Any) -> Generator[bytes]:
            yield str(packet).removeprefix("sentinel.").encode("ascii") + b"\n"

        def build_packet_from_buffer_side_effect(buffer: memoryview) -> Generator[None, int, tuple[Any, bytes]]:
            chunk: bytes = b""
            while True:
                nbytes = yield
                chunk += buffer[:nbytes]
                if b"\n" not in chunk:
                    continue
                del buffer
                data, chunk = chunk.split(b"\n", 1)
                return getattr(mocker.sentinel, data.decode(encoding="ascii")), chunk

        mock_buffered_stream_protocol.generate_chunks.side_effect = generate_chunks_side_effect
        mock_buffered_stream_protocol.build_packet_from_buffer.side_effect = build_packet_from_buffer_side_effect
        return mock_buffered_stream_protocol

    @pytest.fixture(params=["data", "buffer"])
    @staticmethod
    def stream_protocol_mode(request: pytest.FixtureRequest) -> str:
        assert request.param in ("data", "buffer")
        return request.param

    @pytest.fixture
    @staticmethod
    def mock_stream_protocol(
        stream_protocol_mode: str,
        mock_stream_protocol: MagicMock,
        mock_buffered_stream_protocol: MagicMock,
        mocker: MockerFixture,
    ) -> MagicMock:
        def generate_chunks_side_effect(packet: Any) -> Generator[bytes]:
            yield str(packet).removeprefix("sentinel.").encode("ascii") + b"\n"

        def build_packet_from_chunks_side_effect() -> Generator[None, bytes, tuple[Any, bytes]]:
            buffer = b""
            while True:
                buffer += yield
                if b"\n" not in buffer:
                    continue
                data, buffer = buffer.split(b"\n", 1)
                return getattr(mocker.sentinel, data.decode(encoding="ascii")), buffer

        mock_stream_protocol.generate_chunks.side_effect = generate_chunks_side_effect
        mock_stream_protocol.build_packet_from_chunks.side_effect = build_packet_from_chunks_side_effect

        match stream_protocol_mode:
            case "data":
                return mock_stream_protocol
            case "buffer":
                return mock_buffered_stream_protocol
            case _:
                pytest.fail(f'"stream_protocol_mode": Invalid parameter, got {stream_protocol_mode!r}')


class BaseTestWithDatagramProtocol:
    @pytest.fixture
    @staticmethod
    def mock_datagram_protocol(mock_datagram_protocol: MagicMock, mocker: MockerFixture) -> MagicMock:
        def make_datagram_side_effect(packet: Any) -> bytes:
            return str(packet).encode("ascii").removeprefix(b"sentinel.")

        def build_packet_from_datagram_side_effect(data: bytes) -> Any:
            return getattr(mocker.sentinel, data.decode("ascii"))

        mock_datagram_protocol.make_datagram.side_effect = make_datagram_side_effect
        mock_datagram_protocol.build_packet_from_datagram.side_effect = build_packet_from_datagram_side_effect
        return mock_datagram_protocol
