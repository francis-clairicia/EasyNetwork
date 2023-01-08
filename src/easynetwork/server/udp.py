# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server abstract base classes module"""

from __future__ import annotations

__all__ = ["AbstractUDPNetworkServer"]

import sys
from abc import abstractmethod
from collections import deque
from selectors import EVENT_READ, EVENT_WRITE, DefaultSelector as _Selector
from socket import SOCK_DGRAM, socket as Socket
from threading import Event, RLock
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeAlias, TypeVar, cast, final, overload

from ..protocol import DatagramProtocol
from ..tools.datagram import DatagramConsumer, DatagramConsumerError, DatagramProducer, DatagramProducerError
from ..tools.socket import AF_INET, MAX_DATAGRAM_SIZE, SocketAddress, create_server, new_socket_address
from .abc import AbstractNetworkServer
from .executors.abc import AbstractRequestExecutor
from .executors.sync import SyncRequestExecutor

if TYPE_CHECKING:
    from _typeshed import OptExcInfo

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")

DatagramProtocolFactory: TypeAlias = Callable[[], DatagramProtocol[_ResponseT, _RequestT]]

_default_global_executor = SyncRequestExecutor()


class AbstractUDPNetworkServer(AbstractNetworkServer[_RequestT, _ResponseT], Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__socket",
        "__producer",
        "__consumer",
        "__addr",
        "__lock",
        "__loop",
        "__closed",
        "__is_shutdown",
        "__protocol_factory",
        "__request_executor",
        "__default_send_flags",
        "__default_recv_flags",
        "__unsent_datagrams",
    )

    def __init__(
        self,
        address: tuple[str, int] | tuple[str, int, int, int],
        protocol_factory: DatagramProtocolFactory[_ResponseT, _RequestT],
        *,
        family: int = AF_INET,
        reuse_port: bool = False,
        send_flags: int = 0,
        recv_flags: int = 0,
        request_executor: AbstractRequestExecutor | None = None,
    ) -> None:
        protocol = protocol_factory()
        if not isinstance(protocol, DatagramProtocol):
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
        self.__socket: Socket = socket
        self.__producer: DatagramProducer[_ResponseT, SocketAddress] = DatagramProducer(protocol)
        self.__consumer: DatagramConsumer[_RequestT] = DatagramConsumer(protocol, on_error="raise")
        self.__request_executor: AbstractRequestExecutor = (
            request_executor if request_executor is not None else _default_global_executor
        )
        self.__addr: SocketAddress = new_socket_address(socket.getsockname(), socket.family)
        self.__lock: RLock = RLock()
        self.__loop: bool = False
        self.__closed: bool = False
        self.__is_shutdown: Event = Event()
        self.__is_shutdown.set()
        self.__protocol_factory: DatagramProtocolFactory[_ResponseT, _RequestT] = protocol_factory
        self.__default_send_flags: int = int(send_flags)
        self.__default_recv_flags: int = int(recv_flags)
        self.__unsent_datagrams: deque[tuple[bytes, SocketAddress]] = deque()
        super().__init__()

    def serve_forever(self) -> None:
        with self.__lock:
            self._check_not_closed()
            if self.running():
                raise RuntimeError("Server already running")
            self.__is_shutdown.clear()
            self.__loop = True

        socket: Socket = self.__socket

        request_executor: AbstractRequestExecutor = self.__request_executor

        def receive_requests() -> None:
            try:
                data, sender = socket.recvfrom(MAX_DATAGRAM_SIZE, self.__default_recv_flags)
            except (TimeoutError, BlockingIOError, InterruptedError):
                return
            sender = new_socket_address(sender, socket.family)
            self.__consumer.queue(data, sender)

        def process_requests() -> None:
            try:
                request, address = next(self.__consumer)
            except StopIteration:
                return
            except DatagramConsumerError as exc:
                address = exc.sender
                try:
                    self.bad_request(exc)
                except Exception:
                    self.handle_error(address, sys.exc_info())
            else:
                try:
                    request_executor.execute(self.process_request, None, request, address, self.handle_error)
                except Exception as exc:
                    raise RuntimeError(f"request_executor.execute() raised an exception: {exc}") from exc

        with _Selector() as selector:
            selector.register(socket, EVENT_READ | EVENT_WRITE)
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
                            receive_requests()
                        process_requests()
                        request_executor.service_actions()
                        self.service_actions()
                        if ready & EVENT_WRITE:
                            self.__flush_responses()

            finally:
                with self.__lock:
                    self.__loop = False
                    self.__is_shutdown.set()

    def server_close(self) -> None:
        try:
            with self.__lock:
                if not self.__is_shutdown.is_set():
                    raise RuntimeError("Cannot close running server. Use shutdown() first")
                if self.__closed:
                    return
                self.__closed = True
                self.__socket.close()
                del self.__socket
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

    def handle_error(self, client_address: SocketAddress, exc_info: OptExcInfo) -> None:
        from sys import stderr
        from traceback import print_exception

        if exc_info == (None, None, None):
            return

        print("-" * 40, file=stderr)
        print(f"Exception occurred during processing of request from {client_address}", file=stderr)
        print_exception(*exc_info, file=stderr)
        print("-" * 40, file=stderr)

    def shutdown(self) -> None:
        with self.__lock:
            self.__loop = False
        self.__is_shutdown.wait()

    def send_packet(self, address: SocketAddress, packet: _ResponseT) -> None:
        with self.__lock:
            self._check_not_closed()
            self.__producer.queue(address, packet)
            self.__flush_responses()

    def send_packets(self, address: SocketAddress, *packets: _ResponseT) -> None:
        if not packets:
            return
        with self.__lock:
            self._check_not_closed()
            self.__producer.queue(address, *packets)
            self.__flush_responses()

    def __flush_responses(self) -> None:
        socket = self.__socket
        queue, self.__unsent_datagrams = self.__unsent_datagrams, deque()
        while True:
            try:
                queue.append(next(self.__producer))
            except StopIteration:
                break
            except DatagramProducerError as exc:
                self.handle_error(cast(SocketAddress, exc.sender), sys.exc_info())
        while queue:
            response, address = queue.popleft()
            try:
                socket.sendto(response, self.__default_send_flags, address)
            except (TimeoutError, BlockingIOError, InterruptedError):
                self.__unsent_datagrams.append((response, address))

    def bad_request(self, exc: DatagramConsumerError) -> None:
        pass

    def protocol(self) -> DatagramProtocol[_ResponseT, _RequestT]:
        return self.__protocol_factory()

    @overload
    def getsockopt(self, __level: int, __optname: int, /) -> int:
        ...

    @overload
    def getsockopt(self, __level: int, __optname: int, __buflen: int, /) -> bytes:
        ...

    def getsockopt(self, *args: int) -> int | bytes:
        with self.__lock:
            self._check_not_closed()
            return self.__socket.getsockopt(*args)

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: int | bytes, /) -> None:
        ...

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
        ...

    def setsockopt(self, *args: Any) -> None:
        with self.__lock:
            self._check_not_closed()
            return self.__socket.setsockopt(*args)

    @final
    def _check_not_closed(self) -> None:
        if self.__closed:
            raise RuntimeError("Closed server")

    @property
    @final
    def address(self) -> SocketAddress:
        return self.__addr

    @property
    @final
    def send_flags(self) -> int:
        return self.__default_send_flags

    @property
    @final
    def recv_flags(self) -> int:
        return self.__default_recv_flags
