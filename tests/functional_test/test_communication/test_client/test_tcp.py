# -*- coding: Utf-8 -*-

from __future__ import annotations

import time
from socket import AF_INET, AF_INET6, SOCK_STREAM, socket as Socket
from typing import Any, Callable, Iterator

from easynetwork.client.tcp import TCPNetworkClient
from easynetwork.protocol import StreamProtocol, StreamProtocolParseError
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress

import pytest

from ..serializer import StringSerializer


# Origin: https://gist.github.com/4325783, by Geert Jansen.  Public domain.
# Cannot use socket.socketpair() vendored with Python on unix since it is required to use AF_UNIX family :)
@pytest.fixture(params=[AF_INET, AF_INET6])
def socket_pair(request: Any) -> Iterator[tuple[Socket, Socket]]:
    family: int = request.param
    if family == AF_INET:
        host = "127.0.0.1"
    elif family == AF_INET6:
        host = "::1"
    else:
        pytest.fail("Invalid family")
    # We create a connected TCP socket. Note the trick with
    # setblocking(False) that prevents us from having to create a thread.
    lsock = Socket(family, SOCK_STREAM)
    try:
        lsock.bind((host, 0))
        lsock.listen()
        # On IPv6, ignore flow_info and scope_id
        addr, port = lsock.getsockname()[:2]
        csock = Socket(family, SOCK_STREAM)
        try:
            csock.setblocking(False)
            try:
                csock.connect((addr, port))
            except (BlockingIOError, InterruptedError):
                pass
            csock.setblocking(True)
            ssock, _ = lsock.accept()
        except:  # noqa
            csock.close()
            raise
    finally:
        lsock.close()
    with ssock, csock:
        yield ssock, csock


class TestTCPNetworkClient:
    @pytest.fixture(scope="class")
    @staticmethod
    def protocol() -> StreamProtocol[str, str]:
        return StreamProtocol(StringSerializer())

    @pytest.fixture
    @staticmethod
    def server(socket_pair: tuple[Socket, Socket]) -> Socket:
        return socket_pair[0]

    @pytest.fixture
    @staticmethod
    def client(socket_pair: tuple[Socket, Socket], protocol: StreamProtocol[str, str]) -> Iterator[TCPNetworkClient[str, str]]:
        with TCPNetworkClient(socket_pair[1], protocol, give=False) as client:
            yield client

    def test____close____double_close(self, client: TCPNetworkClient[str, str]) -> None:
        assert not client.is_closed()
        client.close()
        assert client.is_closed()
        client.close()
        assert client.is_closed()

    def test____send_packet____default(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        client.send_packet("ABCDEF")
        assert server.recv(1024) == b"ABCDEF\n"

    def test____send_packet____closed_client(self, client: TCPNetworkClient[str, str]) -> None:
        client.close()
        with pytest.raises(OSError):
            client.send_packet("ABCDEF")

    def test____recv_packet____default(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.sendall(b"ABCDEF\n")
        assert client.recv_packet() == "ABCDEF"

    def test____recv_packet____partial(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
        schedule_call_in_thread: Callable[[float, Callable[[], Any]], None],
    ) -> None:
        server.sendall(b"ABC")
        schedule_call_in_thread(0.1, lambda: server.sendall(b"DEF\n"))
        assert client.recv_packet() == "ABCDEF"

    def test____recv_packet____buffer(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.sendall(b"A\nB\nC\nD\n")
        assert client.recv_packet() == "A"
        assert client.recv_packet(timeout=0) == "B"
        assert client.recv_packet(timeout=0) == "C"
        assert client.recv_packet(timeout=0) == "D"
        server.sendall(b"E\nF\nG\nH\nI")
        assert client.recv_packet() == "E"
        assert client.recv_packet(timeout=0) == "F"
        assert client.recv_packet(timeout=0) == "G"
        assert client.recv_packet(timeout=0) == "H"
        with pytest.raises(TimeoutError):
            client.recv_packet(timeout=0)
        server.sendall(b"J\n")
        assert client.recv_packet() == "IJ"

    def test____recv_packet____timeout(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
        schedule_call_in_thread: Callable[[float, Callable[[], Any]], None],
    ) -> None:
        # Case 1: Default timeout behaviour
        server.sendall(b"ABC")
        schedule_call_in_thread(0.1, lambda: server.sendall(b"DEF\n"))
        with pytest.raises(TimeoutError):
            client.recv_packet(timeout=0.01)
        assert client.recv_packet(timeout=0.2) == "ABCDEF"

        # Case 2: Several recv() within timeout
        monotonic = time.monotonic
        schedule_call_in_thread(0.1, lambda: server.sendall(b"A"))
        schedule_call_in_thread(0.2, lambda: server.sendall(b"B"))
        schedule_call_in_thread(0.3, lambda: server.sendall(b"C"))
        schedule_call_in_thread(0.4, lambda: server.sendall(b"D"))
        schedule_call_in_thread(0.5, lambda: server.sendall(b"E"))
        start_time: float = -1
        end_time: float = -1
        with pytest.raises(TimeoutError):
            start_time = monotonic()
            try:
                client.recv_packet(timeout=0.6)
            finally:
                end_time = monotonic()
        assert start_time > 0 and end_time > start_time
        assert (end_time - start_time) == pytest.approx(0.6, rel=1e-2)
        server.sendall(b"F\n")
        assert client.recv_packet(timeout=None) == "ABCDEF"

    def test____recv_packet____eof(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(EOFError):
            client.recv_packet()

    def test____recv_packet____client_close_considered_as_eof(self, client: TCPNetworkClient[str, str]) -> None:
        client.close()
        with pytest.raises(EOFError):
            client.recv_packet()

    def test____recv_packet____invalid_data(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.sendall("\u00E1\nvalid\n".encode("latin-1"))
        with pytest.raises(StreamProtocolParseError):
            client.recv_packet()
        assert client.recv_packet() == "valid"

    def test____fileno____consistency(self, client: TCPNetworkClient[str, str]) -> None:
        assert client.fileno() == client.socket.fileno()

    def test____fileno____closed_client(self, client: TCPNetworkClient[str, str]) -> None:
        client.close()
        assert client.fileno() == -1

    def test____get_local_address____consistency(self, client: TCPNetworkClient[str, str]) -> None:
        address = client.get_local_address()
        if client.socket.family == int(AF_INET):
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getsockname()

    def test____get_remote_address____consistency(self, client: TCPNetworkClient[str, str]) -> None:
        address = client.get_remote_address()
        if client.socket.family == int(AF_INET):
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getpeername()
