# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server abstract base classes module"""

from __future__ import annotations

__all__ = ["AbstractUDPNetworkServer"]

import collections as _collections
import contextlib as _contextlib
import logging as _logging
import os as _os
import selectors as _selectors
import socket as _socket
import sys as _sys
import threading as _threading
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor
from typing import Any, Callable, Generic, TypeVar, final

from ..protocol import DatagramProtocol, DatagramProtocolParseError, ParseErrorType
from ..tools.socket import MAX_DATAGRAM_BUFSIZE, SocketAddress, new_socket_address
from .abc import AbstractNetworkServer

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class AbstractUDPNetworkServer(AbstractNetworkServer[_RequestT, _ResponseT], Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__socket",
        "__internal_lock",
        "__looping",
        "__is_shutdown",
        "__protocol",
        "__selector_factory",
        "__server_selector",
        "__unsent_datagrams",
        "__poll_interval",
        "__thread_pool_size",
        "__logger",
    )

    def __init__(
        self,
        address: tuple[str, int] | tuple[str, int, int, int],
        protocol: DatagramProtocol[_ResponseT, _RequestT],
        *,
        family: int = _socket.AF_INET,
        reuse_port: bool = False,
        selector_factory: Callable[[], _selectors.BaseSelector] | None = None,
        poll_interval: float = 0.1,
        thread_pool_size: int | None = 0,
        logger: _logging.Logger | None = None,
    ) -> None:
        super().__init__()

        assert isinstance(protocol, DatagramProtocol)

        if family not in (_socket.AF_INET, _socket.AF_INET6):
            raise ValueError("Only AF_INET and AF_INET6 families are supported")

        self.__socket: _socket.socket | None = None
        socket = _create_udp_server(address, family, reuse_port)
        try:
            socket.setblocking(False)
            self.__thread_pool_size: int | None = int(thread_pool_size) if thread_pool_size is not None else None
            self.__internal_lock: _threading.RLock = _threading.RLock()
            self.__looping: bool = False
            self.__is_shutdown: _threading.Event = _threading.Event()
            self.__is_shutdown.set()
            self.__protocol: DatagramProtocol[_ResponseT, _RequestT] = protocol
            self.__unsent_datagrams: _collections.deque[tuple[bytes, SocketAddress]] = _collections.deque()
            self.__poll_interval: float = float(poll_interval)
            if selector_factory is None:
                selector_factory = _selectors.DefaultSelector
            self.__selector_factory: Callable[[], _selectors.BaseSelector] = selector_factory
            self.__server_selector: _selectors.BaseSelector | None = None
            self.__logger: _logging.Logger = logger or _logging.getLogger(__name__)
        except BaseException:
            try:
                socket.close()
            finally:
                raise

        self.__socket = socket

    def __del__(self) -> None:
        try:
            socket: _socket.socket | None = self.__socket
        except AttributeError:
            return
        self.__socket = None
        if socket is not None:
            socket.close()

    @final
    def is_closed(self) -> bool:
        return self.__socket is None

    @final
    def running(self) -> bool:
        return not self.__is_shutdown.is_set()

    def server_close(self) -> None:
        with self.__internal_lock:
            if (socket := self.__socket) is None:
                return
            if (selector := self.__server_selector) is not None:
                try:
                    selector.unregister(socket)
                except KeyError:
                    pass
            self.__socket = None
            socket.close()

    def shutdown(self) -> None:
        self.__looping = False
        self.__is_shutdown.wait()

    def serve_forever(self) -> None:
        if (socket := self.__socket) is None:
            raise RuntimeError("Closed server")
        if self.running():
            raise RuntimeError("Server already running")

        with _contextlib.ExitStack() as server_exit_stack:
            # Final log
            server_exit_stack.callback(self.__logger.info, "Server stopped")
            ###########

            # Wake up server
            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)
            ################

            # Setup selector
            server_selector: _selectors.BaseSelector = self.__selector_factory()
            self.__looping = True
            self.__server_selector = server_selector

            def _reset_values(self: AbstractUDPNetworkServer[Any, Any]) -> None:
                self.__server_selector = None
                self.__looping = False

            server_exit_stack.callback(_reset_values, self)
            server_exit_stack.callback(server_selector.close)
            ################

            # Setup client requests' thread pool
            request_executor: _ThreadPoolExecutor | None = None
            if self.__thread_pool_size is None or self.__thread_pool_size != 0:
                request_executor = _ThreadPoolExecutor(
                    max_workers=self.__thread_pool_size,
                    thread_name_prefix=f"{self.__class__.__name__}[request_executor]",
                )
                server_exit_stack.callback(request_executor.shutdown, wait=True, cancel_futures=False)
            ####################################

            # Enable socket
            server_selector.register(socket, _selectors.EVENT_READ)
            self.__logger.info("Start serving at %s", ", ".join(map(str, self.get_addresses())))
            #################

            # Pull methods to local namespace
            flush_unsent_datagrams = self._flush_unsent_datagrams
            handle_received_datagram = self._handle_received_datagram
            service_actions = self.service_actions
            #################################

            # Pull globals to local namespace
            poll_interval: float = self.__poll_interval
            unsent_datagrams: _collections.deque[tuple[bytes, SocketAddress]] = self.__unsent_datagrams
            EVENT_READ: int = _selectors.EVENT_READ
            EVENT_WRITE: int = _selectors.EVENT_WRITE
            #################################

            # Main loop
            while self.__looping:
                ready: int
                with self.__internal_lock:
                    if server_selector.get_map():
                        ready = next((event for key, event in server_selector.select(poll_interval) if key.fileobj is socket), 0)
                    else:
                        ready = 0
                if not self.__looping:  # shutdown() called during select()
                    break  # type: ignore[unreachable]

                if ready & EVENT_WRITE:
                    flush_unsent_datagrams()
                if ready & EVENT_READ:
                    handle_received_datagram(request_executor)

                service_actions()

                with self.__internal_lock:
                    try:
                        selector_key = server_selector.get_key(socket)
                    except KeyError:  # server_closed() called
                        continue
                    else:
                        if unsent_datagrams:
                            if not (selector_key.events & EVENT_WRITE):
                                server_selector.modify(selector_key.fileobj, selector_key.events | EVENT_WRITE, selector_key.data)
                        elif selector_key.events & EVENT_WRITE:
                            server_selector.modify(selector_key.fileobj, selector_key.events & ~EVENT_WRITE, selector_key.data)

    def service_actions(self) -> None:
        pass

    def _handle_received_datagram(self, request_executor: _ThreadPoolExecutor | None) -> None:
        with self.__internal_lock:
            socket: _socket.socket | None = self.__socket
            if socket is None:
                return
            logger: _logging.Logger = self.__logger
            try:
                datagram, client_address = socket.recvfrom(MAX_DATAGRAM_BUFSIZE)
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
            logger.debug("Malformed request sent by %s", client_address)
            try:
                self.bad_request(client_address, exc.error_type, exc.message, exc.error_info)
            except Exception:
                self.handle_error(client_address, _get_exception)
            return
        except Exception:
            self.handle_error(client_address, _get_exception)
            return
        else:
            del datagram

        logger.debug("Processing request sent by %s", client_address)
        if request_executor is None:
            self._execute_request(request, client_address)
        else:
            try:
                request_executor.submit(self._execute_request, request, client_address)
            except RuntimeError:  # shutdown() has been called()
                pass

    def _execute_request(self, request: _RequestT, client_address: SocketAddress) -> None:
        try:
            self.process_request(request, client_address)
        except Exception:
            self.handle_error(client_address, _get_exception)

    def accept_request_from(self, client_address: SocketAddress) -> bool:
        return True

    @abstractmethod
    def process_request(self, request: _RequestT, client_address: SocketAddress) -> None:
        raise NotImplementedError

    def bad_request(self, client_address: SocketAddress, error_type: ParseErrorType, message: str, error_info: Any) -> None:
        pass

    def handle_error(self, client_address: SocketAddress, exc_info: Callable[[], BaseException | None]) -> None:
        exception = exc_info()
        if exception is None:
            return

        try:
            logger: _logging.Logger = self.__logger

            logger.error("-" * 40)
            logger.error("Exception occurred during processing of request from %s", client_address, exc_info=exception)
            logger.error("-" * 40)
        finally:
            del exception

    def send_packet_to(self, packet: _ResponseT, client_address: SocketAddress) -> None:
        try:
            response: bytes = self.__protocol.make_datagram(packet)
        except Exception:
            self.handle_error(client_address, _get_exception)
            return
        with self.__internal_lock:
            if self.__server_selector is None:
                raise RuntimeError("server is not running")
            if (socket := self.__socket) is None:  # server_close() called, bail out silently
                return
            logger: _logging.Logger = self.__logger
            unsent_datagrams = self.__unsent_datagrams

            if unsent_datagrams:
                logger.debug("A response has been queued for %s", client_address)
                unsent_datagrams.append((response, client_address))
                return
            logger.debug("A response will be sent to %s", client_address)
            try:
                socket.sendto(response, client_address)
            except (TimeoutError, BlockingIOError, InterruptedError):
                logger.debug("Failed to send datagram to %s, queue it.", client_address)
                unsent_datagrams.append((response, client_address))
            except OSError:
                logger.exception("Failed to send datagram to %s", client_address)
            else:
                logger.debug("Datagram successfully sent to %s.", client_address)

    def _flush_unsent_datagrams(self) -> None:
        with self.__internal_lock:
            if self.__server_selector is None:
                raise RuntimeError("server is not running")
            if (socket := self.__socket) is None:  # server_close() called, bail out silently
                return
            logger: _logging.Logger = self.__logger
            unsent_datagrams = self.__unsent_datagrams
            while unsent_datagrams:
                response, client_address = unsent_datagrams.popleft()
                logger.debug("Try to send saved datagram to %s", client_address)
                try:
                    socket.sendto(response, client_address)
                except (TimeoutError, BlockingIOError, InterruptedError):
                    unsent_datagrams.appendleft((response, client_address))
                    logger.debug("Failed to send datagram to %s, bail out.", client_address)
                    return
                except OSError:
                    logger.exception("Failed to send datagram to %s", client_address)
                    return
                else:
                    logger.debug("Datagram successfully sent to %s.", client_address)

    @final
    def protocol(self) -> DatagramProtocol[_ResponseT, _RequestT]:
        return self.__protocol

    @final
    def get_address(self) -> SocketAddress | None:
        if (socket := self.__socket) is None:
            return None
        return new_socket_address(socket.getsockname(), socket.family)

    @final
    def get_addresses(self) -> tuple[SocketAddress, ...]:
        address = self.get_address()
        if address is None:
            return ()
        return (address,)

    @property
    @final
    def logger(self) -> _logging.Logger:
        return self.__logger


def _create_udp_server(address: tuple[str, int] | tuple[str, int, int, int], family: int, reuse_port: bool) -> _socket.socket:
    socket = _socket.socket(family, _socket.SOCK_DGRAM)
    try:
        if _os.name not in ("nt", "cygwin") and hasattr(_socket, "SO_REUSEADDR"):
            try:
                socket.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            except OSError:
                pass

        if reuse_port:
            if not hasattr(_socket, "SO_REUSEPORT"):
                raise ValueError("SO_REUSEPORT not supported on this platform")
            socket.setsockopt(_socket.SOL_SOCKET, getattr(_socket, "SO_REUSEPORT"), 1)

        if _socket.has_ipv6 and family == _socket.AF_INET6:
            try:
                socket.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, 1)
            except (OSError, AttributeError):
                pass

        socket.bind(address)
    except BaseException:
        socket.close()
        raise

    return socket


def _get_exception() -> BaseException | None:
    return _sys.exc_info()[1]
