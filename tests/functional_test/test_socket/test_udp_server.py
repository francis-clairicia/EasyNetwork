# -*- coding: Utf-8 -*-

from __future__ import annotations

import os
from threading import Thread
from time import sleep
from typing import Any

from easynetwork.client import UDPNetworkEndpoint
from easynetwork.protocol import DatagramProtocol
from easynetwork.serializers import PickleSerializer
from easynetwork.server import AbstractUDPNetworkServer
from easynetwork.server.executors import ForkingRequestExecutor, ThreadingRequestExecutor
from easynetwork.tools.socket import SocketAddress

import pytest

from ._utils import run_server_in_thread


class _TestServer(AbstractUDPNetworkServer[Any, Any]):
    def process_request(self, request: Any, client_address: SocketAddress) -> None:
        self.send_packet(client_address, request)


_RANDOM_HOST_PORT = ("localhost", 0)


def test_serve_forever_default() -> None:
    with _TestServer(_RANDOM_HOST_PORT, lambda: DatagramProtocol(PickleSerializer())) as server:
        assert not server.running()
        t: Thread = Thread(target=server.serve_forever)
        t.start()
        sleep(0.15)
        assert server.running()
        server.shutdown()
        t.join()
        assert not server.running()


def test_serve_forever_context_shut_down() -> None:
    with _TestServer(_RANDOM_HOST_PORT, lambda: DatagramProtocol(PickleSerializer())) as server:
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
    with _TestServiceActionServer(_RANDOM_HOST_PORT, lambda: DatagramProtocol(PickleSerializer())) as server:
        run_server_in_thread(server)
        sleep(0.3)
    assert getattr(server, "service_actions_called", False)


from .test_tcp_server import _IntegerSerializer


def test_request_handling() -> None:
    with _TestServer(_RANDOM_HOST_PORT, protocol_factory=lambda: DatagramProtocol(_IntegerSerializer())) as server:
        address = server.address
        run_server_in_thread(server)
        with (
            UDPNetworkEndpoint(protocol=DatagramProtocol(_IntegerSerializer())) as client_1,
            UDPNetworkEndpoint(protocol=DatagramProtocol(_IntegerSerializer())) as client_2,
            UDPNetworkEndpoint(protocol=DatagramProtocol(_IntegerSerializer())) as client_3,
        ):
            client_1.send_packet_to(address, 350)
            client_2.send_packet_to(address, -634)
            client_3.send_packet_to(address, 0)
            sleep(0.2)
            assert client_1.recv_packet_from()[0] == 350
            assert client_2.recv_packet_from()[0] == -634
            assert client_3.recv_packet_from()[0] == 0


class _TestThreadingServer(AbstractUDPNetworkServer[Any, Any]):
    def process_request(self, request: Any, client_address: SocketAddress) -> None:
        import threading

        self.send_packet(client_address, (request, threading.current_thread() is not threading.main_thread()))


def test_threading_server() -> None:
    with _TestThreadingServer(
        _RANDOM_HOST_PORT, lambda: DatagramProtocol(PickleSerializer()), request_executor=ThreadingRequestExecutor()
    ) as server:
        run_server_in_thread(server)
        with UDPNetworkEndpoint[Any, Any](server.protocol()) as client:
            packet = {"data": 1}
            client.send_packet_to(server.address, packet)
            response: tuple[Any, bool] = client.recv_packet_from()[0]
            assert response[0] == packet
            assert response[1] is True


class _TestForkingServer(AbstractUDPNetworkServer[Any, Any]):
    def process_request(self, request: Any, client_address: SocketAddress) -> None:
        from os import getpid

        self.send_packet(client_address, (request, getpid()))


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork() not supported on this platform")
def test_forking_server() -> None:
    from os import getpid

    with _TestForkingServer(
        _RANDOM_HOST_PORT, lambda: DatagramProtocol(PickleSerializer()), request_executor=ForkingRequestExecutor()
    ) as server:
        run_server_in_thread(server)
        with UDPNetworkEndpoint[Any, Any](server.protocol()) as client:
            for _ in range(2):
                packet = {"data": 1}
                client.send_packet_to(server.address, packet)
                response: tuple[Any, int] = client.recv_packet_from()[0]
                assert response[0] == packet
                assert response[1] != getpid()
