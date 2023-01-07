# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server abstract base classes module"""

from __future__ import annotations

__all__ = ["AbstractUDPNetworkServer"]

from abc import abstractmethod
from selectors import EVENT_READ, DefaultSelector as _Selector
from socket import SOCK_DGRAM
from threading import Event, RLock
from typing import Any, Callable, Generic, TypeAlias, TypeVar, final, overload

from ..client.udp import UDPNetworkEndpoint
from ..serializers.abc import PacketSerializer
from ..tools.socket import AF_INET, SocketAddress, create_server
from .abc import AbstractNetworkServer
from .executors.abc import AbstractRequestExecutor
from .executors.sync import SyncRequestExecutor

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")

PacketSerializerFactory: TypeAlias = Callable[[], PacketSerializer[_ResponseT, _RequestT]]

_default_global_executor = SyncRequestExecutor()


class AbstractUDPNetworkServer(AbstractNetworkServer[_RequestT, _ResponseT], Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__server",
        "__addr",
        "__lock",
        "__loop",
        "__is_shutdown",
        "__serializer_factory",
        "__request_executor",
    )

    def __init__(
        self,
        address: tuple[str, int] | tuple[str, int, int, int],
        serializer_factory: PacketSerializerFactory[_ResponseT, _RequestT],
        *,
        family: int = AF_INET,
        reuse_port: bool = False,
        send_flags: int = 0,
        recv_flags: int = 0,
        request_executor: AbstractRequestExecutor | None = None,
    ) -> None:
        serializer = serializer_factory()
        if not isinstance(serializer, PacketSerializer):
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
            serializer=serializer,
            socket=socket,
            give=True,
            send_flags=send_flags,
            recv_flags=recv_flags,
            on_recv_error="raise",
        )
        self.__request_executor: AbstractRequestExecutor = (
            request_executor if request_executor is not None else _default_global_executor
        )
        self.__addr: SocketAddress = self.__server.get_local_address()
        self.__lock: RLock = RLock()
        self.__loop: bool = False
        self.__is_shutdown: Event = Event()
        self.__is_shutdown.set()
        self.__serializer_factory: PacketSerializerFactory[_ResponseT, _RequestT] = serializer_factory
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

        request_executor: AbstractRequestExecutor = self.__request_executor

        def parse_requests() -> None:
            try:
                request_tuple = server.recv_packet_no_block_from_anyone(default=None, timeout=0)
            except UDPInvalidPacket as exc:
                address = exc.sender
                del exc
                try:
                    self.bad_request(address)
                except Exception:
                    self.handle_error(address)
            else:
                if request_tuple is None:
                    return
                request, address = request_tuple
                try:
                    request_executor.execute(self.process_request, None, request, address, self.handle_error)
                except Exception as exc:  # TODO: Store not sent packets for further retry
                    raise RuntimeError(f"request_executor.execute() raised an exception: {exc}") from exc

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
                        request_executor.service_actions()
                        self.service_actions()
            finally:
                with self.__lock:
                    self.__loop = False
                    self.__is_shutdown.set()

    def server_close(self) -> None:
        try:
            with self.__lock:
                if not self.__is_shutdown.is_set():
                    raise RuntimeError("Cannot close running server. Use shutdown() first")
                if not self.__server.closed:
                    self.__server.close()
        finally:
            self.__request_executor.on_server_close()

    def service_actions(self) -> None:
        pass

    @final
    def running(self) -> bool:
        with self.__lock:
            return not self.__is_shutdown.is_set()

    @abstractmethod
    def process_request(self, request: _RequestT, client_address: SocketAddress) -> None:
        raise NotImplementedError

    def handle_error(self, client_address: SocketAddress) -> None:
        from sys import exc_info, stderr
        from traceback import print_exc

        if exc_info() == (None, None, None):
            return

        print("-" * 40, file=stderr)
        print(f"Exception occurred during processing of request from {client_address}", file=stderr)
        print_exc(file=stderr)
        print("-" * 40, file=stderr)

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

    def bad_request(self, client_address: SocketAddress) -> None:  # TODO: handle BlockingIOError/InterruptedError
        pass

    def serializer(self) -> PacketSerializer[_ResponseT, _RequestT]:
        return self.__serializer_factory()

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
