from __future__ import annotations

import io
import os
import socketserver
import sys
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from socket import SHUT_WR, socket as Socket
from typing import TYPE_CHECKING, Any, cast

import pytest

from .....tools import TimeTest
from .common import readline

if sys.platform != "win32":
    from easynetwork.clients.unix_stream import UnixStreamClient
    from easynetwork.exceptions import ClientClosedError, StreamProtocolParseError
    from easynetwork.lowlevel import _unix_utils
    from easynetwork.lowlevel.socket import SocketAncillary
    from easynetwork.protocol import AnyStreamProtocolType

    from .common import readmsg

    if TYPE_CHECKING:
        from .....pytest_plugins.unix_sockets import UnixSocketPathFactory

    @pytest.mark.flaky(retries=3, delay=0.1)
    class TestUnixStreamClient:
        @pytest.fixture
        @staticmethod
        def server(unix_socket_pair: tuple[Socket, Socket]) -> Socket:
            server = unix_socket_pair[0]
            return server

        @pytest.fixture
        @staticmethod
        def client(
            unix_socket_pair: tuple[Socket, Socket],
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> Iterator[UnixStreamClient[str, str]]:
            with UnixStreamClient(unix_socket_pair[1], stream_protocol) as client:
                yield client

        def test____close____idempotent(
            self,
            client: UnixStreamClient[str, str],
        ) -> None:
            assert not client.is_closed()
            client.close()
            assert client.is_closed()
            client.close()
            assert client.is_closed()

        def test____send_packet____default(
            self,
            client: UnixStreamClient[str, str],
            server: Socket,
        ) -> None:
            client.send_packet("ABCDEF")
            assert readline(server) == b"ABCDEF\n"

        def test____send_packet____with_ancillary_data(
            self,
            tmp_file: io.FileIO,
            client: UnixStreamClient[str, str],
            server: Socket,
        ) -> None:
            sent_ancillary = SocketAncillary()
            sent_ancillary.add_fds([tmp_file.fileno()])
            client.send_packet("ABCDEF", ancillary_data=sent_ancillary)

            received_packet, received_ancillary = readmsg(server)
            _unix_utils.close_fds_in_socket_ancillary(received_ancillary)
            assert received_packet == b"ABCDEF\n"
            assert len(list(received_ancillary.iter_fds())) == 1

        def test____send_packet____closed_client(self, client: UnixStreamClient[str, str]) -> None:
            client.close()
            with pytest.raises(ClientClosedError):
                client.send_packet("ABCDEF")

        def test____send_eof____close_write_stream(
            self,
            client: UnixStreamClient[str, str],
            server: Socket,
        ) -> None:
            client.send_eof()
            assert readline(server) == b""
            with pytest.raises(RuntimeError):
                client.send_packet("ABC")

            server.sendall(b"ABCDEF\n")
            assert client.recv_packet() == "ABCDEF"

        def test____send_eof____closed_client(
            self,
            client: UnixStreamClient[str, str],
        ) -> None:
            client.close()
            client.send_eof()

        def test____send_eof____idempotent(
            self,
            client: UnixStreamClient[str, str],
            server: Socket,
        ) -> None:
            client.send_eof()
            assert readline(server) == b""
            client.send_eof()
            client.send_eof()

        def test____recv_packet____default(
            self,
            client: UnixStreamClient[str, str],
            server: Socket,
        ) -> None:
            server.sendall(b"ABCDEF\n")
            assert client.recv_packet() == "ABCDEF"

        def test____recv_packet____with_ancillary_data(
            self,
            tmp_file: io.FileIO,
            client: UnixStreamClient[str, str],
            server: Socket,
        ) -> None:
            sent_ancillary = SocketAncillary()
            sent_ancillary.add_fds([tmp_file.fileno()])
            server.sendmsg([b"ABCDEF\n"], sent_ancillary.as_raw())

            received_packet, received_ancillary = client.recv_packet_with_ancillary(1024)
            _unix_utils.close_fds_in_socket_ancillary(received_ancillary)
            assert received_packet == "ABCDEF"
            assert len(list(received_ancillary.iter_fds())) == 1

        def test____recv_packet____partial(
            self,
            client: UnixStreamClient[str, str],
            server: Socket,
            schedule_call_in_thread: Callable[[float, Callable[[], Any]], None],
        ) -> None:
            server.sendall(b"ABC")
            schedule_call_in_thread(0.1, lambda: server.sendall(b"DEF\n"))
            assert client.recv_packet() == "ABCDEF"

        def test____recv_packet____buffer(
            self,
            client: UnixStreamClient[str, str],
            server: Socket,
        ) -> None:
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

        def test____recv_packet____partial____with_ancillary_data(
            self,
            tmp_file: io.FileIO,
            client: UnixStreamClient[str, str],
            server: Socket,
        ) -> None:
            sent_ancillary = SocketAncillary()
            sent_ancillary.add_fds([tmp_file.fileno()])
            server.sendmsg([b"ABC"], sent_ancillary.as_raw())

            with pytest.raises(EOFError):
                client.recv_packet_with_ancillary(1024)

        def test____recv_packet____buffer____with_ancillary_data(
            self,
            tmp_file: io.FileIO,
            client: UnixStreamClient[str, str],
            server: Socket,
        ) -> None:
            sent_ancillary = SocketAncillary()
            sent_ancillary.add_fds([tmp_file.fileno()])
            server.sendmsg([b"A\nB\n"], sent_ancillary.as_raw())

            received_packet, received_ancillary = client.recv_packet_with_ancillary(1024)
            _unix_utils.close_fds_in_socket_ancillary(received_ancillary)
            assert received_packet == "A"
            assert len(list(received_ancillary.iter_fds())) == 1

            received_packet, received_ancillary = client.recv_packet_with_ancillary(1024, timeout=0)
            assert received_packet == "B"
            assert len(list(received_ancillary.messages())) == 0

        def test____recv_packet____timeout(
            self,
            client: UnixStreamClient[str, str],
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
            with TimeTest(0.4, approx=2e-1), pytest.raises(TimeoutError):
                client.recv_packet(timeout=0.4)
            assert client.recv_packet(timeout=None) == "ABCDEF"

        def test____recv_packet____eof____closed_remote(self, client: UnixStreamClient[str, str], server: Socket) -> None:
            server.close()
            with pytest.raises(ConnectionAbortedError):
                client.recv_packet()

        def test____recv_packet____eof____shutdown_write_only(self, client: UnixStreamClient[str, str], server: Socket) -> None:
            server.shutdown(SHUT_WR)
            with pytest.raises(ConnectionAbortedError):
                client.recv_packet()

            client.send_packet("ABCDEF")
            assert readline(server) == b"ABCDEF\n"

        def test____recv_packet____client_close_error(self, client: UnixStreamClient[str, str]) -> None:
            client.close()
            with pytest.raises(ClientClosedError):
                client.recv_packet()

        def test____recv_packet____invalid_data(self, client: UnixStreamClient[str, str], server: Socket) -> None:
            server.sendall("\u00e9\nvalid\n".encode("latin-1"))
            with pytest.raises(StreamProtocolParseError):
                client.recv_packet()
            assert client.recv_packet() == "valid"

        def test____iter_received_packets____yields_available_packets_until_timeout(
            self,
            client: UnixStreamClient[str, str],
            server: Socket,
        ) -> None:
            server.sendall(b"A\nB\nC\nD\nE\nF\n")
            assert list(client.iter_received_packets(timeout=1)) == ["A", "B", "C", "D", "E", "F"]

        def test____iter_received_packets____yields_available_packets_until_eof(
            self,
            client: UnixStreamClient[str, str],
            server: Socket,
        ) -> None:
            server.sendall(b"A\nB\nC\nD\nE\nF")
            server.shutdown(SHUT_WR)
            server.close()
            assert list(client.iter_received_packets(timeout=None)) == ["A", "B", "C", "D", "E"]

        def test____fileno____consistency(self, client: UnixStreamClient[str, str]) -> None:
            assert client.fileno() == client.socket.fileno()

        def test____fileno____closed_client(self, client: UnixStreamClient[str, str]) -> None:
            client.close()
            assert client.fileno() == -1

        def test____get_local_name____consistency(
            self,
            client: UnixStreamClient[str, str],
        ) -> None:
            from easynetwork.lowlevel.socket import UnixSocketAddress

            address = client.get_local_name()
            assert isinstance(address, UnixSocketAddress)
            assert address.as_raw() == client.socket.getsockname()

        def test____get_peer_name____consistency(
            self,
            client: UnixStreamClient[str, str],
        ) -> None:
            from easynetwork.lowlevel.socket import UnixSocketAddress

            address = client.get_peer_name()
            assert isinstance(address, UnixSocketAddress)
            assert address.as_raw() == client.socket.getpeername()

    class EchoRequestHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            data: bytes = self.rfile.readline()
            if data:
                self.wfile.write(data)

    class TestUnixStreamClientConnection:
        @pytest.fixture(autouse=True)
        @classmethod
        def server(cls, unix_socket_path_factory: UnixSocketPathFactory) -> Iterator[socketserver.UnixStreamServer]:
            from threading import Thread

            with socketserver.UnixStreamServer(unix_socket_path_factory(), EchoRequestHandler) as server:
                server_thread = Thread(target=server.serve_forever, daemon=True)
                server_thread.start()
                yield server
                server.shutdown()
                server_thread.join()

        @pytest.fixture
        @staticmethod
        def remote_address(server: socketserver.UnixStreamServer) -> str | bytes:
            return cast(str | bytes, server.server_address)

        def test____dunder_init____connect_to_server(
            self,
            remote_address: str | bytes,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            with UnixStreamClient(remote_address, stream_protocol) as client:
                client.send_packet("Test")
                assert client.recv_packet() == "Test"

        def test____dunder_init____with_local_path(
            self,
            unix_socket_path_factory: UnixSocketPathFactory,
            remote_address: str | bytes,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            with UnixStreamClient(remote_address, stream_protocol, local_path=unix_socket_path_factory()) as client:
                client.send_packet("Test")
                assert client.recv_packet() == "Test"

        def test____get_peer_credentials____consistency(
            self,
            remote_address: str | bytes,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            with UnixStreamClient(remote_address, stream_protocol) as client:
                peer_credentials = client.get_peer_credentials()

                if sys.platform.startswith(("darwin", "linux", "openbsd", "netbsd")):
                    assert peer_credentials.pid == os.getpid()
                else:
                    assert peer_credentials.pid is None
                assert peer_credentials.uid == os.geteuid()
                assert peer_credentials.gid == os.getegid()

        def test____get_peer_credentials____cached_result(
            self,
            remote_address: str | bytes,
            stream_protocol: AnyStreamProtocolType[str, str],
        ) -> None:
            with UnixStreamClient(remote_address, stream_protocol) as client:
                assert client.get_peer_credentials() is client.get_peer_credentials()
