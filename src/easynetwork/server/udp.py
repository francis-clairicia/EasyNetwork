# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server abstract base classes module"""

from __future__ import annotations

__all__ = ["AbstractUDPNetworkServer"]

import logging
import os
import socket as _socket
import sys
from abc import abstractmethod
from collections import deque
from contextlib import ExitStack
from selectors import EVENT_READ, EVENT_WRITE, BaseSelector
from threading import Event, RLock
from typing import Any, Callable, Generic, TypeVar, final

from ..protocol import DatagramProtocol, DatagramProtocolParseError, ParseErrorType
from ..tools.socket import MAX_DATAGRAM_BUFSIZE, SocketAddress, new_socket_address
from .abc import AbstractNetworkServer
from .executors.abc import AbstractRequestExecutor

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class AbstractUDPNetworkServer(AbstractNetworkServer[_RequestT, _ResponseT], Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__socket",
        "__addr",
        "__transaction_lock",
        "__looping",
        "__is_shutdown",
        "__protocol",
        "__selector",
        "__request_executor_factory",
        "__default_send_flags",
        "__default_recv_flags",
        "__protocol",
        "__packets_to_send",
        "__received_datagrams",
        "__unsent_datagrams",
        "__poll_interval",
        "__logger",
    )

    def __init__(
        self,
        address: tuple[str, int] | tuple[str, int, int, int],
        protocol: DatagramProtocol[_ResponseT, _RequestT],
        *,
        family: int = _socket.AF_INET,
        reuse_port: bool = False,
        send_flags: int = 0,
        recv_flags: int = 0,
        request_executor_factory: Callable[[], AbstractRequestExecutor] | None = None,
        selector_factory: Callable[[], BaseSelector] | None = None,
        logger: logging.Logger | None = None,
        poll_interval: float = 0.1,
    ) -> None:
        super().__init__()

        assert isinstance(protocol, DatagramProtocol)

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
        self.__socket: _socket.socket | None = socket
        self.__request_executor_factory: Callable[[], AbstractRequestExecutor] | None = request_executor_factory
        self.__addr: SocketAddress = new_socket_address(socket.getsockname(), socket.family)
        self.__transaction_lock: RLock = RLock()
        self.__looping: bool = False
        self.__is_shutdown: Event = Event()
        self.__is_shutdown.set()
        self.__default_send_flags: int = int(send_flags)
        self.__default_recv_flags: int = int(recv_flags)
        self.__protocol: DatagramProtocol[_ResponseT, _RequestT] = protocol
        self.__unsent_datagrams: deque[tuple[bytes, SocketAddress]] = deque()
        self.__poll_interval: float = poll_interval

        self.__selector: BaseSelector | None
        if selector_factory is None:
            from selectors import DefaultSelector

            self.__selector = DefaultSelector()
        else:
            self.__selector = selector_factory()

        self.__logger: logging.Logger = logger or logging.getLogger(__name__)

    def serve_forever(self) -> None:
        if (socket := self.__socket) is None:
            raise RuntimeError("Closed server")
        if self.running():
            raise RuntimeError("Server already running")

        logger: logging.Logger = self.__logger
        request_executor: AbstractRequestExecutor | None = None
        if self.__request_executor_factory is not None:
            request_executor = self.__request_executor_factory()
            assert isinstance(request_executor, AbstractRequestExecutor)
        selector: BaseSelector | None = self.__selector
        if selector is None:
            raise RuntimeError("server_forever() cannot be called twice")

        with ExitStack() as server_exit_stack:
            server_exit_stack.callback(logger.info, "Server stopped")

            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)

            self.__looping = True

            def _reset_values(self: AbstractUDPNetworkServer[Any, Any]) -> None:
                self.__looping = False
                self.__selector = None

            server_exit_stack.callback(_reset_values, self)

            if request_executor is not None:
                server_exit_stack.callback(request_executor.shutdown)

            selector_key = selector.register(socket, EVENT_READ)
            logger.info("Start serving at %s", self.__addr)

            # pull methods to local namespace
            debug_log = logger.debug
            select = selector.select
            flush_unsent_datagrams = self.__flush_unsent_datagrams
            handle_received_datagram = self.__handle_received_datagram
            service_actions = self.service_actions

            # Pull globals to local namespace
            unsent_datagrams: deque[tuple[bytes, SocketAddress]] = self.__unsent_datagrams
            poll_interval: float = self.__poll_interval
            event_read_mask: int = EVENT_READ
            event_write_mask: int = EVENT_WRITE

            while self.__looping:
                ready: int
                try:
                    ready = select(poll_interval)[0][1]
                except IndexError:
                    ready = 0
                if not self.__looping:
                    break  # type: ignore[unreachable]

                if ready & event_write_mask:
                    debug_log("socket is ready for writing")
                    flush_unsent_datagrams()
                if ready & event_read_mask:
                    debug_log("socket is ready for reading")
                    handle_received_datagram(request_executor)

                service_actions()

                if unsent_datagrams:
                    if not (selector_key.events & event_write_mask):
                        selector_key = selector.modify(
                            selector_key.fileobj,
                            selector_key.events | event_write_mask,
                            selector_key.data,
                        )
                elif selector_key.events & event_write_mask:
                    selector_key = selector.modify(
                        selector_key.fileobj,
                        selector_key.events & ~event_write_mask,
                        selector_key.data,
                    )

                if request_executor is not None:
                    request_executor.service_actions()

    def server_close(self) -> None:
        if not self.__is_shutdown.is_set():
            raise RuntimeError("Cannot close running server. Use shutdown() first")
        if (socket := self.__socket) is None:
            return
        if (selector := self.__selector) is not None:
            self.__selector = None
            selector.close()
        self.__socket = None
        socket.close()

    def service_actions(self) -> None:
        pass

    @final
    def is_closed(self) -> bool:
        return self.__socket is None

    @final
    def running(self) -> bool:
        return not self.__is_shutdown.is_set()

    def __handle_received_datagram(self, request_executor: AbstractRequestExecutor | None) -> None:
        socket: _socket.socket | None = self.__socket
        assert socket is not None
        logger: logging.Logger = self.__logger
        try:
            datagram, client_address = socket.recvfrom(MAX_DATAGRAM_BUFSIZE, self.__default_recv_flags)
        except (TimeoutError, BlockingIOError, InterruptedError):
            return
        client_address = new_socket_address(client_address, socket.family)
        logger.debug("Received a datagram from %s", client_address)

        if not self.accept_request_from(client_address):
            logger.warning("A client (address = %s) was not accepted by verification", client_address)
            return

        try:
            request: _RequestT = self.__protocol.build_packet_from_datagram(datagram)
        except DatagramProtocolParseError as exc:
            logger.info("Malformed request sent by %s", client_address)
            try:
                self.bad_request(client_address, exc.error_type, exc.message, exc.error_info)
            except Exception:
                self.__request_handling_error(client_address)
            return
        except Exception:
            self.__request_handling_error(client_address)
            return
        else:
            del datagram

        logger.info("Processing request sent by %s", client_address)
        try:
            if request_executor is not None:
                request_executor.execute(self.__execute_request, request, client_address, os.getpid())
            else:
                self.__execute_request(request, client_address)
        except Exception:
            self.__request_handling_error(client_address)

    def __execute_request(self, request: _RequestT, client_address: SocketAddress, pid: int | None = None) -> None:
        in_subprocess: bool = pid is not None and pid != os.getpid()
        try:
            self.process_request(request, client_address)
        except Exception:
            self.__request_handling_error(client_address)
            if in_subprocess:
                raise

    @abstractmethod
    def process_request(self, request: _RequestT, client_address: SocketAddress) -> None:
        raise NotImplementedError

    def __request_handling_error(self, client_address: SocketAddress) -> None:
        self.__log_request_handling_error(client_address, _get_exception)
        self.handle_error(client_address, _get_exception)

    def __log_request_handling_error(self, client_address: SocketAddress, exc_info: Callable[[], BaseException | None]) -> None:
        exception = exc_info()
        if exception is None:
            return

        try:
            logger: logging.Logger = self.__logger

            logger.error("-" * 40)
            logger.error("Exception occurred during processing of request from %s", client_address, exc_info=exception)
            logger.error("-" * 40)
        finally:
            del exception

    def handle_error(self, client_address: SocketAddress, exc_info: Callable[[], BaseException | None]) -> None:
        pass

    def shutdown(self) -> None:
        if self.__socket is None:
            raise RuntimeError("Closed server")
        self.__looping = False
        self.__is_shutdown.wait()

    def send_packet(self, address: SocketAddress, packet: _ResponseT) -> None:
        if (socket := self.__socket) is None:
            raise RuntimeError("Closed server")
        logger: logging.Logger = self.__logger
        unsent_datagrams = self.__unsent_datagrams
        flags: int = self.__default_send_flags
        try:
            response: bytes = self.__protocol.make_datagram(packet)
        except Exception:
            self.__logger.exception("Failed to serialize response for %s", address)
            return

        with self.__transaction_lock:
            logger.info("A response will be sent to %s", address)
            if unsent_datagrams:
                logger.debug("-> There is unsent datagrams, queue it.")
                unsent_datagrams.append((response, address))
                return
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
        socket: _socket.socket | None = self.__socket
        assert socket is not None
        logger: logging.Logger = self.__logger
        unsent_datagrams = self.__unsent_datagrams
        flags: int = self.__default_send_flags
        with self.__transaction_lock:
            while unsent_datagrams:
                response, address = unsent_datagrams.popleft()
                logger.debug("Try to send saved datagram to %s", address)
                try:
                    socket.sendto(response, flags, address)
                except (TimeoutError, BlockingIOError, InterruptedError):
                    unsent_datagrams.appendleft((response, address))
                    logger.debug("-> Failed to send datagram, bail out.")
                    return
                except OSError:
                    logger.exception("-> Failed to send datagram")
                    return
                else:
                    logger.debug("-> Datagram successfully sent.")

    def accept_request_from(self, client_address: SocketAddress) -> bool:
        return True

    def bad_request(self, client_address: SocketAddress, error_type: ParseErrorType, message: str, error_info: Any) -> None:
        pass

    @final
    def protocol(self) -> DatagramProtocol[_ResponseT, _RequestT]:
        return self.__protocol

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


def _get_exception() -> BaseException | None:
    return sys.exc_info()[1]
