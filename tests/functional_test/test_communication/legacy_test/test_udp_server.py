# -*- coding: Utf-8 -*-

from __future__ import annotations

import os
from threading import Thread
from time import sleep
from typing import Any, Callable

from easynetwork.client import UDPNetworkEndpoint
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import PickleSerializer
from easynetwork.server import AbstractUDPNetworkServer
from easynetwork.server.executors import AbstractRequestExecutor, ForkingRequestExecutor, ThreadingRequestExecutor
from easynetwork.tools.socket import SocketAddress

import pytest

from ._utils import run_server_in_thread


class _TestServer(AbstractUDPNetworkServer[Any, Any]):
    def __init__(
        self,
        protocol: DatagramProtocol[Any, Any],
        *,
        request_executor_factory: Callable[[], AbstractRequestExecutor] | None = None,
    ) -> None:
        super().__init__(("127.0.0.1", 0), protocol, request_executor_factory=request_executor_factory)

    def process_request(self, request: Any, client_address: SocketAddress) -> None:
        self.send_packet(client_address, request)


def test_serve_forever_default() -> None:
    with _TestServer(DatagramProtocol(PickleSerializer())) as server:
        assert not server.running()
        t: Thread = Thread(target=server.serve_forever)
        t.start()
        sleep(0.15)
        assert server.running()
        server.shutdown()
        t.join()
        assert not server.running()


def test_serve_forever_context_shut_down() -> None:
    with _TestServer(DatagramProtocol(PickleSerializer())) as server:
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


def test_service_actions() -> None:
    with _TestServiceActionServer(DatagramProtocol(PickleSerializer())) as server:
        run_server_in_thread(server)
        sleep(0.3)
    assert getattr(server, "service_actions_called", False)


from .test_tcp_server import _IntegerSerializer


def test_request_handling() -> None:
    with _TestServer(DatagramProtocol(_IntegerSerializer())) as server:
        address = server.address
        run_server_in_thread(server)
        with (
            UDPNetworkEndpoint(protocol=DatagramProtocol(_IntegerSerializer())) as client_1,
            UDPNetworkEndpoint(protocol=DatagramProtocol(_IntegerSerializer())) as client_2,
            UDPNetworkEndpoint(protocol=DatagramProtocol(_IntegerSerializer())) as client_3,
        ):
            client_1.send_packet_to(350, address)
            client_2.send_packet_to(-634, address)
            client_3.send_packet_to(0, address)
            sleep(0.2)
            assert client_1.recv_packet_from()[0] == 350
            assert client_2.recv_packet_from()[0] == -634
            assert client_3.recv_packet_from()[0] == 0


class _TestThreadingServer(_TestServer):
    def process_request(self, request: Any, client_address: SocketAddress) -> None:
        import threading

        self.send_packet(client_address, (request, threading.current_thread() is not threading.main_thread()))


def test_threading_server() -> None:
    with _TestThreadingServer(DatagramProtocol(PickleSerializer()), request_executor_factory=ThreadingRequestExecutor) as server:
        run_server_in_thread(server)
        with UDPNetworkEndpoint[Any, Any](server.protocol()) as client:
            packet = {"data": 1}
            client.send_packet_to(packet, server.address)
            response: tuple[Any, bool] = client.recv_packet_from()[0]
            assert response[0] == packet
            assert response[1] is True


class _TestForkingServer(_TestServer):
    def process_request(self, request: Any, client_address: SocketAddress) -> None:
        from os import getpid

        self.send_packet(client_address, (request, getpid()))


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork() not supported on this platform")
def test_forking_server() -> None:
    from os import getpid

    with _TestForkingServer(DatagramProtocol(PickleSerializer()), request_executor_factory=ForkingRequestExecutor) as server:
        run_server_in_thread(server)
        with UDPNetworkEndpoint[Any, Any](server.protocol()) as client:
            for _ in range(2):
                packet = {"data": 1}
                client.send_packet_to(packet, server.address)
                response: tuple[Any, int] = client.recv_packet_from()[0]
                assert response[0] == packet
                assert response[1] != getpid()
