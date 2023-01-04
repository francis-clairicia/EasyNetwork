# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server abstract base classes module"""

from __future__ import annotations

__all__ = ["AbstractUDPNetworkServer"]

from selectors import EVENT_READ, DefaultSelector as _Selector
from socket import SOCK_DGRAM
from threading import Event, RLock
from typing import Any, Callable, Generic, TypeAlias, TypeVar, final, overload

from ..client.udp import UDPNetworkEndpoint
from ..protocol.abc import NetworkProtocol
from ..tools.socket import AF_INET, SocketAddress, create_server
from .abc import AbstractNetworkServer, ConnectedClient

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")

NetworkProtocolFactory: TypeAlias = Callable[[], NetworkProtocol[_ResponseT, _RequestT]]


class AbstractUDPNetworkServer(AbstractNetworkServer[_RequestT, _ResponseT], Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__server",
        "__addr",
        "__lock",
        "__loop",
        "__is_shutdown",
        "__protocol_cls",
    )

    def __init__(
        self,
        address: tuple[str, int] | tuple[str, int, int, int],
        protocol_factory: NetworkProtocolFactory[_ResponseT, _RequestT],
        *,
        family: int = AF_INET,
        reuse_port: bool = False,
        send_flags: int = 0,
        recv_flags: int = 0,
    ) -> None:
        protocol = protocol_factory()
        if not isinstance(protocol, NetworkProtocol):
            raise TypeError("Invalid arguments")
        send_flags = int(send_flags)
        recv_flags = int(recv_flags)
        socket = create_server(
            address,
            family=family,
            type=SOCK_DGRAM,
            backlog=None,
            reuse_port=reuse_port,
            dualstack_ipv6=False,
        )
        socket.settimeout(0)
        self.__server: UDPNetworkEndpoint[_ResponseT, _RequestT] = UDPNetworkEndpoint(
            protocol=protocol,
            socket=socket,
            give=True,
            send_flags=send_flags,
            recv_flags=recv_flags,
        )
        self.__addr: SocketAddress = self.__server.get_local_address()
        self.__lock: RLock = RLock()
        self.__loop: bool = False
        self.__is_shutdown: Event = Event()
        self.__is_shutdown.set()
        self.__protocol_cls: NetworkProtocolFactory[_ResponseT, _RequestT] = protocol_factory
        super().__init__()

    def serve_forever(self) -> None:
        from ..client import UDPInvalidPacket

        with self.__lock:
            self._check_not_closed()
            if self.running():
                raise RuntimeError("Server already running")
            self.__is_shutdown.clear()
            self.__loop = True

        server: UDPNetworkEndpoint[_ResponseT, _RequestT] = self.__server
        make_connected_client = self.__ConnectedUDPClient

        handle_request = AbstractNetworkServer.handle_request

        def parse_requests() -> None:
            bad_request_address: SocketAddress | None = None
            try:
                packets = server.recv_packets_from_anyone(timeout=0, on_error="raise")
            except (BlockingIOError, InterruptedError):  # TODO: Already deserialized request not handled
                return
            except UDPInvalidPacket as exc:
                bad_request_address = exc.sender
                packets = exc.already_deserialized_packets
            process_requests(packets)
            if bad_request_address is not None:
                connected_client = make_connected_client(server, bad_request_address)
                try:
                    self.bad_request(connected_client)
                except Exception:
                    self.handle_error(connected_client)
                finally:
                    connected_client.close()

        def process_requests(packets: list[tuple[_RequestT, SocketAddress]]) -> None:
            for request, address in packets:
                connected_client = make_connected_client(server, address)
                try:
                    handle_request(self, request, connected_client)
                except (BlockingIOError, InterruptedError):  # TODO: Store not sent packets for further retry
                    return
                except Exception:
                    self.handle_error(connected_client)
                finally:
                    connected_client.close()

        with _Selector() as selector:
            selector.register(server, EVENT_READ)
            try:
                while self.__loop:
                    ready: int
                    try:
                        ready = selector.select(timeout=0)[0][1]
                    except IndexError:
                        ready = 0
                    if not self.__loop:
                        break  # type: ignore[unreachable]
                    with self.__lock:
                        if ready & EVENT_READ:
                            parse_requests()
                        self.service_actions()
            finally:
                with self.__lock:
                    self.__loop = False
                    self.__is_shutdown.set()

    def server_close(self) -> None:
        with self.__lock:
            if not self.__is_shutdown.is_set():
                raise RuntimeError("Cannot close running server. Use shutdown() first")
            if not self.__server.closed:
                self.__server.close()

    def service_actions(self) -> None:
        pass

    def running(self) -> bool:
        with self.__lock:
            return not self.__is_shutdown.is_set()

    def shutdown(self) -> None:
        with self.__lock:
            self.__loop = False
        self.__is_shutdown.wait()

    def send_packet(self, address: SocketAddress, packet: _ResponseT) -> None:  # TODO: handle BlockingIOError/InterruptedError
        self._check_not_closed()
        self.__server.send_packet(address, packet)

    def send_packets(self, address: SocketAddress, *packets: _ResponseT) -> None:  # TODO: handle BlockingIOError/InterruptedError
        self._check_not_closed()
        self.__server.send_packet(address, *packets)

    def bad_request(self, client: ConnectedClient[_ResponseT]) -> None:  # TODO: handle BlockingIOError/InterruptedError
        pass

    def protocol(self) -> NetworkProtocol[_ResponseT, _RequestT]:
        return self.__protocol_cls()

    @overload
    def getsockopt(self, __level: int, __optname: int, /) -> int:
        ...

    @overload
    def getsockopt(self, __level: int, __optname: int, __buflen: int, /) -> bytes:
        ...

    def getsockopt(self, *args: int) -> int | bytes:
        self._check_not_closed()
        return self.__server.getsockopt(*args)

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: int | bytes, /) -> None:
        ...

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
        ...

    def setsockopt(self, *args: Any) -> None:
        self._check_not_closed()
        return self.__server.setsockopt(*args)

    @final
    def _check_not_closed(self) -> None:
        if self.__server.closed:
            raise RuntimeError("Closed server")

    @property
    @final
    def address(self) -> SocketAddress:
        return self.__addr

    @property
    @final
    def send_flags(self) -> int:
        return self.__server.default_send_flags

    @property
    @final
    def recv_flags(self) -> int:
        return self.__server.default_recv_flags

    @final
    class __ConnectedUDPClient(ConnectedClient[_ResponseT]):
        __slots__ = ("__s",)

        def __init__(
            self,
            server: UDPNetworkEndpoint[_ResponseT, Any] | None,
            address: SocketAddress,
        ) -> None:
            super().__init__(address)
            self.__s: UDPNetworkEndpoint[_ResponseT, Any] | None = server

        def close(self) -> None:
            with self.transaction():
                self.__s = None

        def send_packet(self, packet: _ResponseT) -> None:
            with self.transaction():
                server: UDPNetworkEndpoint[_ResponseT, Any] | None = self.__s
                if server is None:
                    raise RuntimeError("Closed client")
                server.send_packet(self.address, packet)

        def send_packets(self, *packets: _ResponseT) -> None:
            if not packets:
                return
            with self.transaction():
                server: UDPNetworkEndpoint[_ResponseT, Any] | None = self.__s
                if server is None:
                    raise RuntimeError("Closed client")
                server.send_packets(self.address, *packets)

        def flush(self) -> None:
            if self.closed:
                raise RuntimeError("Closed client")

        @property
        def closed(self) -> bool:
            return self.__s is None
