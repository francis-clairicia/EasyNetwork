from __future__ import annotations

import functools
import inspect
import pathlib
import socketserver
from collections.abc import Callable, Iterator
from socket import socket as Socket
from typing import Any, cast

from easynetwork.clients.unix_datagram import UnixDatagramClient
from easynetwork.exceptions import ClientClosedError, DatagramProtocolParseError
from easynetwork.lowlevel.socket import UnixSocketAddress
from easynetwork.protocol import DatagramProtocol

import pytest

from .....pytest_plugins.unix_sockets import UnixSocketPathFactory
from .....tools import PlatformMarkers


@pytest.fixture
def unix_datagram_socket_factory(
    request: pytest.FixtureRequest,
    unix_datagram_socket_factory: Callable[[], Socket],
    unix_socket_path_factory: UnixSocketPathFactory,
) -> Callable[[], Socket]:

    from easynetwork.lowlevel import _unix_utils

    @functools.wraps(unix_datagram_socket_factory)
    def bound_unix_datagram_socket_factory() -> Socket:
        sock = unix_datagram_socket_factory()
        sock.settimeout(3)
        match getattr(request, "param", None):
            case "PATHNAME":
                sock.bind(unix_socket_path_factory())
            case "ABSTRACT":
                sock.bind("")
            case None:
                if _unix_utils.platform_supports_automatic_socket_bind():
                    sock.bind("")
                else:
                    sock.bind(unix_socket_path_factory())
            case _:
                sock.close()
                pytest.fail(f"Invalid use_unix_address_type parameter: {request.param}")
        return sock

    return bound_unix_datagram_socket_factory


@pytest.mark.flaky(retries=3, delay=0.1)
@PlatformMarkers.skipif_platform_win32
class TestUnixDatagramClient:
    @pytest.fixture
    @staticmethod
    def server(unix_datagram_socket_factory: Callable[[], Socket]) -> Socket:
        return unix_datagram_socket_factory()

    @pytest.fixture
    @staticmethod
    def client(
        server: Socket,
        unix_datagram_socket_factory: Callable[[], Socket],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> Iterator[UnixDatagramClient[str, str]]:
        address: str | bytes = server.getsockname()
        socket = unix_datagram_socket_factory()
        socket.connect(address)

        with UnixDatagramClient(socket, datagram_protocol) as client:
            yield client

    def test____close____idempotent(self, client: UnixDatagramClient[str, str]) -> None:
        assert not client.is_closed()
        client.close()
        assert client.is_closed()
        client.close()
        assert client.is_closed()

    def test____send_packet____default(self, client: UnixDatagramClient[str, str], server: Socket) -> None:
        client.send_packet("ABCDEF")
        assert server.recvfrom(1024) == (b"ABCDEF", client.get_local_name().as_raw())

    @PlatformMarkers.runs_only_on_platform("linux", "Windows, MacOS and BSD-like do not raise error")
    def test____send_packet____connection_refused(self, client: UnixDatagramClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(ConnectionRefusedError):
            client.send_packet("ABCDEF")

    @PlatformMarkers.runs_only_on_platform("linux", "Windows, MacOS and BSD-like do not raise error")
    def test____send_packet____connection_refused____after_previous_successful_try(
        self,
        client: UnixDatagramClient[str, str],
        server: Socket,
    ) -> None:
        client.send_packet("ABC")
        assert server.recvfrom(1024) == (b"ABC", client.get_local_name().as_raw())
        server.close()
        with pytest.raises(ConnectionRefusedError):
            client.send_packet("DEF")

    def test____send_packet____closed_client(self, client: UnixDatagramClient[str, str]) -> None:
        client.close()
        with pytest.raises(ClientClosedError):
            client.send_packet("ABCDEF")

    def test____recv_packet____default(self, client: UnixDatagramClient[str, str], server: Socket) -> None:
        server.sendto(b"ABCDEF", client.get_local_name().as_raw())
        assert client.recv_packet() == "ABCDEF"

    def test____recv_packet____timeout(
        self,
        client: UnixDatagramClient[str, str],
        server: Socket,
        schedule_call_in_thread: Callable[[float, Callable[[], Any]], None],
    ) -> None:
        schedule_call_in_thread(0.1, lambda: server.sendto(b"ABCDEF", client.get_local_name().as_raw()))
        with pytest.raises(TimeoutError):
            client.recv_packet(timeout=0)
        assert client.recv_packet(timeout=None) == "ABCDEF"

    def test____recv_packet____closed_client(self, client: UnixDatagramClient[str, str]) -> None:
        client.close()
        with pytest.raises(ClientClosedError):
            client.recv_packet()

    def test____recv_packet____invalid_data(self, client: UnixDatagramClient[str, str], server: Socket) -> None:
        server.sendto("\u00e9".encode("latin-1"), client.get_local_name().as_raw())
        with pytest.raises(DatagramProtocolParseError):
            client.recv_packet()

    def test____iter_received_packets____yields_available_packets(
        self,
        client: UnixDatagramClient[str, str],
        server: Socket,
    ) -> None:
        for p in [b"A", b"B", b"C", b"D", b"E", b"F"]:
            server.sendto(p, client.get_local_name().as_raw())

        # NOTE: Comparison using set because equality check does not verify order
        assert set(client.iter_received_packets(timeout=0.1)) == {"A", "B", "C", "D", "E", "F"}

    def test____fileno____consistency(self, client: UnixDatagramClient[str, str]) -> None:
        assert client.fileno() == client.socket.fileno()

    def test____fileno____closed_client(self, client: UnixDatagramClient[str, str]) -> None:
        client.close()
        assert client.fileno() == -1

    def test____get_local_name____consistency(self, client: UnixDatagramClient[str, str]) -> None:
        address = client.get_local_name()
        assert isinstance(address, UnixSocketAddress)
        assert address.as_raw() == client.socket.getsockname()

    def test____get_peer_name____consistency(self, client: UnixDatagramClient[str, str]) -> None:
        address = client.get_peer_name()
        assert isinstance(address, UnixSocketAddress)
        assert address.as_raw() == client.socket.getpeername()


class EchoRequestHandler(socketserver.DatagramRequestHandler):
    def handle(self) -> None:
        data: bytes = self.rfile.read()
        self.wfile.write(data)


@PlatformMarkers.skipif_platform_win32
class TestUnixDatagramClientConnection:
    @pytest.fixture(autouse=True)
    @classmethod
    def server(cls, unix_socket_path_factory: UnixSocketPathFactory) -> Iterator[socketserver.UnixDatagramServer]:  # type: ignore[name-defined,unused-ignore]
        from threading import Thread

        with socketserver.UnixDatagramServer(unix_socket_path_factory(), EchoRequestHandler) as server:  # type: ignore[attr-defined,unused-ignore]
            server_thread = Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            yield server
            server.shutdown()
            server_thread.join()

    @pytest.fixture
    @staticmethod
    def remote_address(server: socketserver.UnixDatagramServer) -> str | bytes:  # type: ignore[name-defined,unused-ignore]
        return cast(str | bytes, server.server_address)

    @pytest.fixture
    @staticmethod
    def local_path(unix_socket_path_factory: UnixSocketPathFactory) -> str:
        return unix_socket_path_factory()

    @PlatformMarkers.supports_abstract_sockets
    def test____dunder_init____automatic_local_name(
        self,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        with UnixDatagramClient(remote_address, datagram_protocol) as client:
            assert not client.get_local_name().is_unnamed()

            client.send_packet("Test")
            assert client.recv_packet() == "Test"

    @PlatformMarkers.abstract_sockets_unsupported
    def test____dunder_init____automatic_local_name____unsupported_by_current_platform(
        self,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        with pytest.raises(
            ValueError,
            match=r"^local_path parameter is required on this platform and cannot be an empty string\.",
        ):
            _ = UnixDatagramClient(remote_address, datagram_protocol)

    def test____dunder_init____with_local_name(
        self,
        local_path: str,
        remote_address: str | bytes,
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        with UnixDatagramClient(remote_address, datagram_protocol, local_path=local_path) as client:
            assert client.get_local_name().as_pathname() == pathlib.Path(local_path)

            client.send_packet("Test")
            assert client.recv_packet() == "Test"

    def test____dunder_init____peer_name____not_set(
        self,
        unix_datagram_socket_factory: Callable[[], Socket],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        with pytest.raises(OSError):
            _ = UnixDatagramClient(unix_datagram_socket_factory(), datagram_protocol)

    def test____dunder_init____local_name____not_set(
        self,
        remote_address: str | bytes,
        unix_datagram_socket_factory: Callable[[], Socket],
        datagram_protocol: DatagramProtocol[str, str],
    ) -> None:
        unix_datagram_socket_factory = inspect.unwrap(unix_datagram_socket_factory)
        sock = unix_datagram_socket_factory()
        sock.connect(remote_address)
        assert not sock.getsockname()
        with pytest.raises(ValueError, match=r"^UnixDatagramClient requires the socket to be named.$"):
            _ = UnixDatagramClient(sock, datagram_protocol)
