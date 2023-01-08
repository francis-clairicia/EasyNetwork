# -*- coding: Utf-8 -*-

from __future__ import annotations

import os
import socket
import sys
from threading import Thread
from time import sleep
from typing import Any, ClassVar, Generator

from easynetwork.client import TCPNetworkClient
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import AbstractIncrementalPacketSerializer, PickleSerializer
from easynetwork.server import AbstractTCPNetworkServer, ConnectedClient
from easynetwork.server.executors import ForkingRequestExecutor, ThreadingRequestExecutor
from easynetwork.tools.socket import SocketAddress

import pytest

from ._utils import run_server_in_thread


class _TestServer(AbstractTCPNetworkServer[Any, Any]):
    def process_request(self, request: Any, client: ConnectedClient[Any]) -> None:
        for c in filter(lambda c: c is not client, self.get_clients()):
            c.send_packet(request)


_RANDOM_HOST_PORT = ("localhost", 0)


def test_serve_forever_default() -> None:
    with _TestServer(_RANDOM_HOST_PORT, lambda: StreamProtocol(PickleSerializer())) as server:
        assert not server.running()
        t: Thread = Thread(target=server.serve_forever)
        t.start()
        sleep(0.15)
        assert server.running()
        server.shutdown()
        t.join()
        assert not server.running()


@pytest.mark.skipif(sys.platform == "win32", reason="Expected failure")
def test_serve_forever_context_shut_down() -> None:
    with _TestServer(_RANDOM_HOST_PORT, lambda: StreamProtocol(PickleSerializer())) as server:
        t: Thread = Thread(target=server.serve_forever)
        t.start()
        sleep(0.15)
        assert server.running()
    t.join()
    assert not server.running()


class _TestServiceActionServer(_TestServer):
    def service_actions(self) -> None:
        super().service_actions()
        self.service_actions_called: bool = True


@pytest.mark.skipif(sys.platform == "win32", reason="Expected failure")
def test_service_actions() -> None:
    with _TestServiceActionServer(_RANDOM_HOST_PORT, lambda: StreamProtocol(PickleSerializer())) as server:
        run_server_in_thread(server)
        sleep(0.3)
    assert getattr(server, "service_actions_called", False)


@pytest.mark.skipif(sys.platform == "win32", reason="Expected failure")
def test_client_connection() -> None:
    with _TestServer(_RANDOM_HOST_PORT, lambda: StreamProtocol(PickleSerializer())) as server:
        address = server.address.for_connection()
        run_server_in_thread(server)
        sleep(0.1)
        assert len(server.get_clients()) == 0
        with TCPNetworkClient[Any, Any](address, server.protocol()):
            sleep(0.3)
            assert len(server.get_clients()) == 1
        sleep(0.3)
        assert len(server.get_clients()) == 0


class _TestWelcomeServer(_TestServer):
    def verify_new_client(self, client_socket: socket.socket, address: SocketAddress) -> bool:
        with TCPNetworkClient(client_socket, protocol=self.protocol()) as client:
            client.send_packet("Welcome !")
        return True


@pytest.mark.skipif(sys.platform == "win32", reason="Expected failure")
def test_welcome_connection() -> None:
    with _TestWelcomeServer(_RANDOM_HOST_PORT, lambda: StreamProtocol(PickleSerializer()), backlog=1) as server:
        address = server.address.for_connection()
        run_server_in_thread(server)
        with TCPNetworkClient[Any, Any](address, server.protocol()) as client:
            assert client.recv_packet() == "Welcome !"


@pytest.mark.skipif(sys.platform == "win32", reason="Expected failure")
def test_multiple_connections() -> None:
    with _TestWelcomeServer(_RANDOM_HOST_PORT, lambda: StreamProtocol(PickleSerializer())) as server:
        address = server.address.for_connection()
        run_server_in_thread(server)
        with (
            TCPNetworkClient[Any, Any](address, server.protocol()) as client_1,
            TCPNetworkClient[Any, Any](address, server.protocol()) as client_2,
            TCPNetworkClient[Any, Any](address, server.protocol()) as client_3,
        ):
            assert client_1.recv_packet() == "Welcome !"
            assert client_2.recv_packet() == "Welcome !"
            assert client_3.recv_packet() == "Welcome !"
            sleep(0.2)
            assert len(server.get_clients()) == 3


class _IntegerSerializer(AbstractIncrementalPacketSerializer[int, int]):
    BYTES_LENGTH: ClassVar[int] = 8

    def incremental_serialize(self, packet: int) -> Generator[bytes, None, None]:
        yield packet.to_bytes(self.BYTES_LENGTH, byteorder="big", signed=True)

    def incremental_deserialize(self) -> Generator[None, bytes, tuple[Any, bytes]]:
        data: bytes = b""
        while True:
            data += yield
            if len(data) >= self.BYTES_LENGTH:
                packet = int.from_bytes(data[: self.BYTES_LENGTH], byteorder="big", signed=True)
                return packet, data[self.BYTES_LENGTH :]


@pytest.mark.skipif(sys.platform == "win32", reason="Expected failure")
def test_request_handling() -> None:
    with _TestServer(_RANDOM_HOST_PORT, protocol_factory=lambda: StreamProtocol(_IntegerSerializer())) as server:
        address = server.address.for_connection()
        run_server_in_thread(server)
        with (
            TCPNetworkClient(address, protocol=StreamProtocol(_IntegerSerializer())) as client_1,
            TCPNetworkClient(address, protocol=StreamProtocol(_IntegerSerializer())) as client_2,
            TCPNetworkClient(address, protocol=StreamProtocol(_IntegerSerializer())) as client_3,
        ):
            while len(server.get_clients()) < 3:
                sleep(0.1)
            client_1.send_packet(350)
            sleep(0.3)
            assert client_2.recv_packet() == 350
            assert client_3.recv_packet() == 350
            with pytest.raises(TimeoutError):
                client_1.recv_packet_no_block()
            client_2.send_packet(-634)
            sleep(0.3)
            assert client_1.recv_packet() == -634
            assert client_3.recv_packet() == -634
            with pytest.raises(TimeoutError):
                client_2.recv_packet_no_block()
            client_3.send_packet(0)
            sleep(0.3)
            assert client_1.recv_packet() == 0
            assert client_2.recv_packet() == 0
            with pytest.raises(TimeoutError):
                client_3.recv_packet_no_block()
            client_1.send_packet(350)
            sleep(0.1)
            client_2.send_packet(-634)
            sleep(0.1)
            client_3.send_packet(0)
            sleep(0.3)
            assert client_1.recv_all_packets() == [-634, 0]
            assert client_2.recv_all_packets() == [350, 0]
            assert client_3.recv_all_packets() == [350, -634]


@pytest.mark.skipif(sys.platform == "win32", reason="Expected failure")
def test_disable_nagle_algorithm() -> None:
    with _TestServer(
        _RANDOM_HOST_PORT, lambda: StreamProtocol(PickleSerializer()), buffered_write=True, disable_nagle_algorithm=True
    ) as server:
        run_server_in_thread(server)
        with (
            TCPNetworkClient(server.address.for_connection(), protocol=server.protocol()) as client_1,
            TCPNetworkClient(server.address.for_connection(), protocol=server.protocol()) as client_2,
        ):
            packet = {"data": 1}
            client_1.send_packet(packet)
            assert client_2.recv_packet() == packet


class _TestThreadingServer(AbstractTCPNetworkServer[Any, Any]):
    def process_request(self, request: Any, client: ConnectedClient[Any]) -> None:
        import threading

        client.send_packet((request, threading.current_thread() is not threading.main_thread()))


@pytest.mark.skipif(sys.platform == "win32", reason="Expected failure")
def test_threading_server() -> None:
    with _TestThreadingServer(
        _RANDOM_HOST_PORT, lambda: StreamProtocol(PickleSerializer()), request_executor=ThreadingRequestExecutor()
    ) as server:
        run_server_in_thread(server)
        with TCPNetworkClient[Any, Any](server.address.for_connection(), server.protocol()) as client:
            packet = {"data": 1}
            client.send_packet(packet)
            response: tuple[Any, bool] = client.recv_packet()
            assert response[0] == packet
            assert response[1] is True


class _TestForkingServer(AbstractTCPNetworkServer[Any, Any]):
    def process_request(self, request: Any, client: ConnectedClient[Any]) -> None:
        from os import getpid

        client.send_packet((request, getpid()))


@pytest.mark.skipif(sys.platform == "win32", reason="Expected failure")
@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork() not supported on this platform")
@pytest.mark.parametrize(
    "buffered_write", [pytest.param(False, id="buffered_write==False"), pytest.param(True, id="buffered_write==True")]
)
def test_forking_server(buffered_write: bool) -> None:
    from os import getpid

    with _TestForkingServer(
        _RANDOM_HOST_PORT,
        lambda: StreamProtocol(PickleSerializer()),
        buffered_write=buffered_write,
        request_executor=ForkingRequestExecutor(),
    ) as server:
        run_server_in_thread(server)
        with TCPNetworkClient[Any, Any](server.address.for_connection(), server.protocol()) as client:
            for _ in range(2):
                packet = {"data": 1}
                client.send_packet(packet)
                response: tuple[Any, int] = client.recv_packet_no_block(timeout=5)
                assert response[0] == packet
                assert response[1] != getpid()
                sleep(0.5)
