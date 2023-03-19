# -*- coding: Utf-8 -*-

from __future__ import annotations

from concurrent.futures import Future
from socket import AF_INET, SHUT_WR, socket as Socket
from typing import Any, Callable, Iterator

from easynetwork.client.tcp import TCPNetworkClient
from easynetwork.exceptions import ClientClosedError, StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.tools.socket import IPv4SocketAddress, IPv6SocketAddress

import pytest

from ....tools import TimeTest


# Origin: https://gist.github.com/4325783, by Geert Jansen.  Public domain.
# Cannot use socket.socketpair() vendored with Python on unix since it is required to use AF_UNIX family :)
@pytest.fixture
def socket_pair(localhost: str, tcp_socket_factory: Callable[[], Socket]) -> Iterator[tuple[Socket, Socket]]:
    # We create a connected TCP socket. Note the trick with
    # setblocking(False) that prevents us from having to create a thread.
    lsock = tcp_socket_factory()
    try:
        lsock.bind((localhost, 0))
        lsock.listen()
        # On IPv6, ignore flow_info and scope_id
        addr, port = lsock.getsockname()[:2]
        csock = tcp_socket_factory()
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
    with ssock:  # csock will be closed later by tcp_socket_factory() teardown
        yield ssock, csock


class TestTCPNetworkClient:
    @pytest.fixture
    @staticmethod
    def server(socket_pair: tuple[Socket, Socket]) -> Socket:
        return socket_pair[0]

    @pytest.fixture
    @staticmethod
    def client(
        socket_pair: tuple[Socket, Socket],
        stream_protocol: StreamProtocol[str, str],
    ) -> Iterator[TCPNetworkClient[str, str]]:
        with TCPNetworkClient(socket_pair[1], stream_protocol, give=False) as client:
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

    @pytest.mark.platform_linux  # Windows and macOs raise ConnectionAbortedError but in the 2nd send() call
    def test____send_packet____connection_error____fresh_connection_closed_by_server(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        server.close()
        with pytest.raises(ConnectionError):
            client.send_packet("ABCDEF")

    @pytest.mark.platform_linux  # Windows and macOs raise ConnectionAbortedError but in the 2nd send() call
    def test____send_packet____connection_error____after_previous_successful_try(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        client.send_packet("ABCDEF")
        assert server.recv(1024) == b"ABCDEF\n"
        server.close()
        with pytest.raises(ConnectionError):
            client.send_packet("ABCDEF")

    def test____send_packet____connection_error____partial_read_then_close(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        client.send_packet("ABC")
        assert server.recv(1) == b"A"
        server.close()
        with pytest.raises(ConnectionError):
            client.send_packet("DEF")

    def test____send_packet____closed_client(self, client: TCPNetworkClient[str, str]) -> None:
        client.close()
        with pytest.raises(ClientClosedError):
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
        schedule_call_in_thread_with_future: Callable[[float, Callable[[], Any]], Future[Any]],
    ) -> None:
        # Case 1: Default timeout behaviour
        server.sendall(b"ABC")
        schedule_call_in_thread_with_future(0.1, lambda: server.sendall(b"DEF\n"))
        with pytest.raises(TimeoutError):
            client.recv_packet(timeout=0)
        assert client.recv_packet(timeout=None) == "ABCDEF"

        # Case 2: Several recv() within timeout
        def schedule_send(chunks: list[bytes]) -> None:
            f = schedule_call_in_thread_with_future(0.1, lambda: server.sendall(chunks.pop(0)))
            if chunks:
                f.add_done_callback(lambda _: schedule_send(chunks))

        schedule_send([b"A", b"B", b"C", b"D", b"E", b"F\n"])
        with pytest.raises(TimeoutError), TimeTest(0.4, approx=1e-1):
            client.recv_packet(timeout=0.4)
        assert client.recv_packet(timeout=None) == "ABCDEF"

    def test____recv_packet____eof(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.close()
        with pytest.raises(ConnectionAbortedError):
            client.recv_packet()

    def test____recv_packet____client_close_error(self, client: TCPNetworkClient[str, str]) -> None:
        client.close()
        with pytest.raises(ClientClosedError):
            client.recv_packet()

    def test____recv_packet____invalid_data(self, client: TCPNetworkClient[str, str], server: Socket) -> None:
        server.sendall("\u00E9\nvalid\n".encode("latin-1"))
        with pytest.raises(StreamProtocolParseError):
            client.recv_packet()
        assert client.recv_packet() == "valid"

    def test____iter_received_packets____yields_available_packets_until_timeout(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        server.sendall(b"A\nB\nC\nD\nE\nF\n")
        assert list(client.iter_received_packets(timeout=1)) == ["A", "B", "C", "D", "E", "F"]

    def test____iter_received_packets____yields_available_packets_until_eof(
        self,
        client: TCPNetworkClient[str, str],
        server: Socket,
    ) -> None:
        server.sendall(b"A\nB\nC\nD\nE\nF")
        server.shutdown(SHUT_WR)
        server.close()
        assert list(client.iter_received_packets(timeout=None)) == ["A", "B", "C", "D", "E"]

    def test____fileno____consistency(self, client: TCPNetworkClient[str, str]) -> None:
        assert client.fileno() == client.socket.fileno()

    def test____fileno____closed_client(self, client: TCPNetworkClient[str, str]) -> None:
        client.close()
        assert client.fileno() == -1

    def test____get_local_address____consistency(self, socket_family: int, client: TCPNetworkClient[str, str]) -> None:
        address = client.get_local_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getsockname()

    def test____get_remote_address____consistency(self, socket_family: int, client: TCPNetworkClient[str, str]) -> None:
        address = client.get_remote_address()
        if socket_family == AF_INET:
            assert isinstance(address, IPv4SocketAddress)
        else:
            assert isinstance(address, IPv6SocketAddress)
        assert address == client.socket.getpeername()
