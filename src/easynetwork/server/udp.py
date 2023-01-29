# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server abstract base classes module"""

from __future__ import annotations

__all__ = ["AbstractUDPNetworkServer"]

import logging
import sys
from abc import abstractmethod
from collections import deque
from selectors import EVENT_READ, EVENT_WRITE, BaseSelector
from socket import socket as Socket
from threading import Event, RLock
from typing import TYPE_CHECKING, Any, Callable, Generic, Iterator, TypeAlias, TypeVar, final, overload

from ..protocol import DatagramProtocol, DatagramProtocolParseError, ParseErrorType
from ..tools.datagram import DatagramConsumer, DatagramProducer
from ..tools.socket import AF_INET, SocketAddress, new_socket_address
from .abc import AbstractNetworkServer
from .executors.abc import AbstractRequestExecutor

if TYPE_CHECKING:
    from _typeshed import OptExcInfo

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")

DatagramProtocolFactory: TypeAlias = Callable[[], DatagramProtocol[_ResponseT, _RequestT]]


class AbstractUDPNetworkServer(AbstractNetworkServer[_RequestT, _ResponseT], Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__socket",
        "__producer",
        "__consumer",
        "__addr",
        "__send_lock",
        "__loop",
        "__closed",
        "__is_shutdown",
        "__protocol_factory",
        "__selector_factory",
        "__request_executor",
        "__default_send_flags",
        "__default_recv_flags",
        "__unsent_datagrams",
        "__poll_interval",
        "__logger",
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
        selector_factory: Callable[[], BaseSelector] | None = None,
        logger: logging.Logger | None = None,
        poll_interval: float = 0.1,
    ) -> None:
        super().__init__()

        protocol = protocol_factory()
        if not isinstance(protocol, DatagramProtocol):
            raise TypeError("Invalid arguments")
        assert request_executor is None or isinstance(request_executor, AbstractRequestExecutor)
        send_flags = int(send_flags)
        recv_flags = int(recv_flags)
        poll_interval = float(poll_interval)

        import socket as _socket

        socket = _socket.socket(family, _socket.SOCK_DGRAM)
        try:
            if reuse_port:
                if not hasattr(_socket, "SO_REUSEPORT"):
                    raise ValueError("SO_REUSEPORT not supported on this platform")
                socket.setsockopt(_socket.SOL_SOCKET, getattr(_socket, "SO_REUSEPORT"), 1)

            if family == _socket.AF_INET6 and _socket.has_ipv6:
                try:
                    socket.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, 1)
                except OSError:
                    pass

            socket.bind(address)
        except BaseException:
            socket.close()
            raise

        socket.settimeout(0)
        self.__socket: Socket = socket
        self.__producer: DatagramProducer[_ResponseT, SocketAddress] = DatagramProducer(protocol)
        self.__consumer: DatagramConsumer[_RequestT] = DatagramConsumer(protocol)
        self.__request_executor: AbstractRequestExecutor | None = request_executor
        self.__addr: SocketAddress = new_socket_address(socket.getsockname(), socket.family)
        self.__send_lock: RLock = RLock()
        self.__loop: bool = False
        self.__closed: bool = False
        self.__is_shutdown: Event = Event()
        self.__is_shutdown.set()
        self.__protocol_factory: DatagramProtocolFactory[_ResponseT, _RequestT] = protocol_factory
        self.__default_send_flags: int = int(send_flags)
        self.__default_recv_flags: int = int(recv_flags)
        self.__unsent_datagrams: deque[tuple[bytes, SocketAddress]] = deque()
        self.__poll_interval: float = poll_interval

        self.__selector_factory: Callable[[], BaseSelector]
        if selector_factory is None:
            from selectors import DefaultSelector

            self.__selector_factory = DefaultSelector
        else:
            self.__selector_factory = selector_factory

        self.__logger: logging.Logger = logger or logging.getLogger(__name__)

    def serve_forever(self) -> None:
        self._check_not_closed()
        if self.running():
            raise RuntimeError("Server already running")

        logger: logging.Logger = self.__logger
        request_executor: AbstractRequestExecutor | None = self.__request_executor

        try:
            self.__is_shutdown.clear()
            self.__loop = True

            with self.__selector_factory() as selector:
                selector_key = selector.register(self.__socket, EVENT_READ)

                logger.info("Start serving at %s", self.__addr)

                while self.__loop:
                    ready: int
                    try:
                        ready = selector.select(timeout=self.__poll_interval)[0][1]
                    except IndexError:
                        ready = 0
                    if not self.__loop:
                        break  # type: ignore[unreachable]

                    if ready & EVENT_WRITE:
                        self.__flush_unsent_datagrams()
                    if ready & EVENT_READ:
                        self.__receive_datagrams()
                    self.__handle_received_datagrams()

                    if request_executor is not None:
                        request_executor.service_actions()
                    self.service_actions()

                    if self.__unsent_datagrams:
                        if not (selector_key.events & EVENT_WRITE):
                            selector_key = selector.modify(
                                selector_key.fileobj,
                                selector_key.events | EVENT_WRITE,
                                selector_key.data,
                            )
                    elif selector_key.events & EVENT_WRITE:
                        selector_key = selector.modify(
                            selector_key.fileobj,
                            selector_key.events & ~EVENT_WRITE,
                            selector_key.data,
                        )

        finally:
            if request_executor is not None:
                try:
                    request_executor.on_server_stop()
                except Exception:
                    pass
            self.__loop = False
            self.__is_shutdown.set()
            logger.info("Server stopped")

    def server_close(self) -> None:
        if not self.__is_shutdown.is_set():
            raise RuntimeError("Cannot close running server. Use shutdown() first")
        if self.__closed:
            return
        try:
            self.__closed = True
            self.__socket.close()
            del self.__socket
        finally:
            if (request_executor := self.__request_executor) is not None:
                request_executor.on_server_close()

    def service_actions(self) -> None:
        pass

    @final
    def is_closed(self) -> bool:
        return self.__closed

    @final
    def running(self) -> bool:
        return not self.__is_shutdown.is_set()

    def __receive_datagrams(self) -> None:
        logger: logging.Logger = self.__logger
        socket: Socket = self.__socket
        recv_flags: int = self.__default_recv_flags
        while True:
            try:
                data, sender = socket.recvfrom(65536, recv_flags)
            except (TimeoutError, BlockingIOError, InterruptedError):
                return
            sender = new_socket_address(sender, socket.family)
            logger.debug("Received a datagram from %s", sender)
            self.__consumer.queue(data, sender)

    def __handle_received_datagrams(self) -> None:
        logger: logging.Logger = self.__logger
        request_executor: AbstractRequestExecutor | None = self.__request_executor
        for request, address in self.__iter_consumer():
            logger.info("Processing request sent by %s", address)
            try:
                if request_executor is not None:
                    request_executor.execute(self.__execute_request, request, address)
                else:
                    self.__execute_request(request, address)
            except Exception as exc:
                if request_executor is not None:
                    raise RuntimeError(f"request_executor.execute() raised an exception: {exc}") from exc
                raise RuntimeError(f"Error when processing request: {exc}") from exc

    def __iter_consumer(self) -> Iterator[tuple[_RequestT, SocketAddress]]:
        while True:
            try:
                return (yield from self.__consumer)
            except DatagramProtocolParseError as exc:
                self.__logger.info("Malformed request sent by %s", exc.sender)
                try:
                    self.bad_request(exc.sender, exc.error_type, exc.message, exc.error_info)
                except Exception:
                    self.handle_error(exc.sender, sys.exc_info())
            except Exception as exc:
                raise RuntimeError(str(exc)) from exc

    def __execute_request(self, request: _RequestT, client_address: SocketAddress) -> None:
        try:
            self.process_request(request, client_address)
        except Exception:
            self.handle_error(client_address, sys.exc_info())

    @abstractmethod
    def process_request(self, request: _RequestT, client_address: SocketAddress) -> None:
        raise NotImplementedError

    def handle_error(self, client_address: SocketAddress, exc_info: OptExcInfo) -> None:
        if exc_info == (None, None, None):
            return

        logger: logging.Logger = self.__logger

        logger.error("-" * 40)
        logger.error("Exception occurred during processing of request from %s", client_address, exc_info=exc_info)
        logger.error("-" * 40)

    def shutdown(self) -> None:
        self._check_not_closed()
        self.__loop = False
        self.__is_shutdown.wait()

    def send_packet(self, address: SocketAddress, packet: _ResponseT) -> None:
        with self.__send_lock:
            self._check_not_closed()
            self.__producer.queue(address, packet)
            self.__logger.debug("Put 1 packet to queue for %s", address)
            self.__send_datagrams()

    def send_packets(self, address: SocketAddress, *packets: _ResponseT) -> None:
        if not packets:
            return
        with self.__send_lock:
            self._check_not_closed()
            self.__producer.queue(address, *packets)
            if (nb_packets := len(packets)) > 1:
                self.__logger.debug("Put %d packets to queue for %s", nb_packets, address)
            else:
                self.__logger.debug("Put 1 packet to queue for %s", address)
            self.__send_datagrams()

    def __send_datagrams(self) -> None:
        logger: logging.Logger = self.__logger
        socket = self.__socket
        unsent_datagrams = self.__unsent_datagrams
        flags: int = self.__default_send_flags
        for response, address in self.__producer:
            logger.info("A response will be sent to %s", address)
            if unsent_datagrams:
                logger.debug("-> There is unsent datagrams, queue it.")
                unsent_datagrams.append((response, address))
                continue
            try:
                socket.sendto(response, flags, address)
            except (TimeoutError, BlockingIOError, InterruptedError):
                logger.debug("-> Failed to send datagram, queue it.")
                unsent_datagrams.append((response, address))
            except OSError:
                logger.exception("-> Failed to send datagram")
            else:
                logger.debug("-> Datagram successfully sent.")

    def __flush_unsent_datagrams(self) -> None:
        logger: logging.Logger = self.__logger
        socket = self.__socket
        unsent_datagrams = self.__unsent_datagrams
        flags: int = self.__default_send_flags
        with self.__send_lock:
            while unsent_datagrams:
                response, address = unsent_datagrams[0]
                logger.debug("Try to send saved datagram to %s", address)
                try:
                    socket.sendto(response, flags, address)
                except (TimeoutError, BlockingIOError, InterruptedError):
                    logger.debug("-> Failed to send datagram, bail out.")
                    return
                except OSError:
                    logger.exception("-> Failed to send datagram")
                    return
                else:
                    logger.debug("-> Datagram successfully sent.")
                    del unsent_datagrams[0]

    def bad_request(self, client_address: SocketAddress, error_type: ParseErrorType, message: str, error_info: Any) -> None:
        pass

    @final
    def protocol(self) -> DatagramProtocol[_ResponseT, _RequestT]:
        return self.__protocol_factory()

    @overload
    def getsockopt(self, __level: int, __optname: int, /) -> int:
        ...

    @overload
    def getsockopt(self, __level: int, __optname: int, __buflen: int, /) -> bytes:
        ...

    @final
    def getsockopt(self, *args: int) -> int | bytes:
        self._check_not_closed()
        return self.__socket.getsockopt(*args)

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: int | bytes, /) -> None:
        ...

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
        ...

    @final
    def setsockopt(self, *args: Any) -> None:
        self._check_not_closed()
        return self.__socket.setsockopt(*args)

    @final
    def _check_not_closed(self) -> None:
        if self.__closed:
            raise RuntimeError("Closed server")

    @property
    @final
    def logger(self) -> logging.Logger:
        return self.__logger

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
