# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server abstract base classes module"""

from __future__ import annotations

__all__ = [
    "AbstractTCPNetworkServer",
    "ConnectedClient",
]

import concurrent.futures
import errno
import logging
import os
import socket as _socket
import sys
from abc import ABCMeta, abstractmethod
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from functools import partial
from itertools import chain
from selectors import EVENT_READ, EVENT_WRITE, BaseSelector, SelectSelector
from threading import Event, RLock
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar, final
from weakref import WeakKeyDictionary

from ..client.tcp import TCPNetworkClient
from ..protocol import ParseErrorType, StreamProtocol, StreamProtocolParseError
from ..tools._utils import check_real_socket_state as _check_real_socket_state
from ..tools.socket import MAX_STREAM_BUFSIZE, SocketAddress, SocketProxy, new_socket_address
from ..tools.stream import StreamDataConsumer, StreamDataProducer
from .abc import AbstractNetworkServer
from .executors.abc import AbstractRequestExecutor

if TYPE_CHECKING:
    from typing import type_check_only

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class ConnectedClient(Generic[_ResponseT], metaclass=ABCMeta):
    __slots__ = ("__addr", "__weakref__")

    def __init__(self, address: SocketAddress) -> None:
        super().__init__()
        self.__addr: SocketAddress = address

    def __repr__(self) -> str:
        return f"<connected client with address {self.__addr} at {id(self):#x}{' closed' if self.is_closed() else ''}>"

    @abstractmethod
    def is_closed(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def shutdown(self, how: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def flush(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_packet(self, packet: _ResponseT) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def socket(self) -> SocketProxy:
        raise NotImplementedError

    @property
    @final
    def address(self) -> SocketAddress:
        return self.__addr


class AbstractTCPNetworkServer(AbstractNetworkServer[_RequestT, _ResponseT], Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__listener_socket",
        "__addr",
        "__protocol",
        "__request_executor_factory",
        "__looping",
        "__is_shutdown",
        "__server_selector",
        "__disable_nagle_algorithm",
        "__busy_clients",
        "__send_flags",
        "__recv_flags",
        "__verify_client_pool",
        "__logger",
    )

    max_recv_size: int = MAX_STREAM_BUFSIZE  # Buffer size passed to recv().

    def __init__(
        self,
        address: tuple[str, int] | tuple[str, int, int, int],
        protocol: StreamProtocol[_ResponseT, _RequestT],
        *,
        server_name: str = "",
        family: int = _socket.AF_INET,
        backlog: int | None = None,
        reuse_port: bool = False,
        dualstack_ipv6: bool = False,
        send_flags: int = 0,
        recv_flags: int = 0,
        disable_nagle_algorithm: bool = False,
        request_executor_factory: Callable[[], AbstractRequestExecutor] | None = None,
        selector_factory: Callable[[], BaseSelector] | None = None,
        poll_interval: float = 0.1,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__()
        assert isinstance(protocol, StreamProtocol)

        self.__listener_socket: _socket.socket | None = _socket.create_server(
            address,
            family=family,
            backlog=backlog,
            reuse_port=reuse_port,
            dualstack_ipv6=dualstack_ipv6,
        )
        self.__request_executor_factory: Callable[[], AbstractRequestExecutor] | None = request_executor_factory
        self.__addr: SocketAddress = new_socket_address(self.__listener_socket.getsockname(), self.__listener_socket.family)
        self.__protocol: StreamProtocol[_ResponseT, _RequestT] = protocol
        self.__looping: bool = False
        self.__is_shutdown: Event = Event()
        self.__is_shutdown.set()
        if selector_factory is None:
            from selectors import DefaultSelector

            selector_factory = DefaultSelector
        self.__server_selector: _ServerSocketSelector[_RequestT, _ResponseT] | None = _ServerSocketSelector(
            selector_factory,
            poll_interval=poll_interval,
        )
        self.__send_flags: int = send_flags
        self.__recv_flags: int = recv_flags
        self.__disable_nagle_algorithm: bool = bool(disable_nagle_algorithm)
        self.__verify_client_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,  # Do not need more than that
            thread_name_prefix=f"{server_name or 'TCPNetworkServer'}[verify_client]",
        )
        self.__busy_clients: set[_socket.socket] = set()
        self.__logger: logging.Logger = logger or logging.getLogger(__name__)

    def serve_forever(self) -> None:
        if (listener_socket := self.__listener_socket) is None:
            raise RuntimeError("Closed server")
        if self.running():
            raise RuntimeError("Server already running")

        server_selector: _ServerSocketSelector[_RequestT, _ResponseT] | None = self.__server_selector
        if server_selector is None:
            raise RuntimeError("server_forever() cannot be called twice")

        request_executor: AbstractRequestExecutor | None = None
        if self.__request_executor_factory is not None:
            request_executor = self.__request_executor_factory()
            assert isinstance(request_executor, AbstractRequestExecutor)
        logger: logging.Logger = self.__logger

        with ExitStack() as server_exit_stack:
            server_exit_stack.callback(logger.info, "Server stopped")

            self.__is_shutdown.clear()
            server_exit_stack.callback(self.__is_shutdown.set)

            self.__looping = True

            def _reset_values(self: AbstractTCPNetworkServer[Any, Any]) -> None:
                self.__looping = False
                self.__server_selector = None

            server_exit_stack.callback(_reset_values, self)

            server_exit_stack.callback(self.__verify_client_pool.shutdown, wait=True, cancel_futures=False)
            if request_executor is not None:
                server_exit_stack.callback(request_executor.shutdown)

            server_exit_stack.callback(server_selector.close)

            server_selector.add_listener_socket(listener_socket)
            logger.info("Start serving at %s", self.__addr)

            # Pull methods to local namespace
            debug_log = logger.debug
            select = server_selector.select
            accept_new_client = self.__accept_new_client
            receive_data = self.__receive_data
            handle_all_client_requests = self.__handle_all_client_requests
            service_actions = self.service_actions

            # Pull globals to local namespace
            event_read_mask: int = EVENT_READ
            event_write_mask: int = EVENT_WRITE

            while self.__looping:
                ready = select()
                if not self.__looping:
                    break  # type: ignore[unreachable]

                for listener_socket in ready["listeners"]:
                    accept_new_client(listener_socket)

                for socket, event, key_data in ready["clients"]:
                    with key_data.lock:
                        client = key_data.client
                        if client.is_closed():
                            continue
                        if event & event_write_mask:
                            debug_log("%s is ready for writing", client.address)
                            with suppress(OSError):
                                client.flush()
                        if event & event_read_mask:
                            debug_log("%s is ready for reading", client.address)
                            receive_data(socket, key_data)
                handle_all_client_requests(request_executor)

                service_actions()
                if request_executor is not None:
                    request_executor.service_actions()

    @final
    def is_closed(self) -> bool:
        return self.__listener_socket is None

    @final
    def running(self) -> bool:
        return not self.__is_shutdown.is_set()

    def service_actions(self) -> None:
        pass

    def __accept_new_client(self, listener_socket: _socket.socket) -> None:
        try:
            client_socket, address = listener_socket.accept()
        except OSError:
            return
        address = new_socket_address(address, client_socket.family)

        self.__logger.info("Accepted new connection (peername = %s)", address)

        future = self.__verify_client_pool.submit(self.__verify_client_task, client_socket, address)
        try:
            future.add_done_callback(partial(self.__add_client_callback, socket=client_socket, address=address))
        finally:
            del future

    def __add_client_callback(
        self,
        future: concurrent.futures.Future[tuple[bool, bytes]],
        *,
        socket: _socket.socket,
        address: SocketAddress,
    ) -> None:
        logger: logging.Logger = self.__logger

        try:
            accepted, remaining_data = future.result()
        except BaseException:
            logger.exception("An exception occured when verifying client %s", address)
            with suppress(Exception):
                socket.close()
            return
        finally:
            del future
        if not accepted or not self.__looping:
            if not accepted:
                logger.warning("A client (address = %s) was not accepted by verification", address)
            with suppress(Exception):
                socket.close()
            return

        socket.settimeout(0)

        if self.__disable_nagle_algorithm:
            try:
                socket.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, True)
            except Exception:
                logger.exception("Failed to apply TCP_NODELAY socket option")

        server_selector = self.__server_selector
        assert server_selector is not None

        key_data = _SelectorKeyData(
            protocol=self.__protocol,
            socket=socket,
            address=address,
            server_selector=server_selector,
            on_close=self.on_disconnection,
            logger=logger,
            send_flags=self.__send_flags,
        )
        key_data.consumer.feed(remaining_data)
        server_selector.register_client(socket, key_data)
        server_selector.add_client_for_reading(socket)
        logger.info("A client (address = %s) was added", address)
        self.on_connection(key_data.client)

    def __receive_data(self, socket: _socket.socket, key_data: _SelectorKeyData[_RequestT, _ResponseT]) -> None:
        logger: logging.Logger = self.__logger
        data: bytes
        logger.debug("Receiving data from %s", socket.getsockname())
        try:
            data = socket.recv(self.max_recv_size, self.__recv_flags)
        except (TimeoutError, BlockingIOError, InterruptedError):
            logger.debug("-> Interruped. Will try later")
            return
        except OSError:
            self.__request_handling_error_and_close_client(key_data.client, shutdown=True)
            return
        if not data:  # Closed connection (EOF)
            logger.info("-> Remote side closed the connection")
            self.__request_handling_error_and_close_client(key_data.client, shutdown=True)
            return
        logger.debug("-> Received %d bytes", len(data))
        key_data.consumer.feed(data)

    def __handle_all_client_requests(self, request_executor: AbstractRequestExecutor | None) -> None:
        server_selector = self.__server_selector
        assert server_selector is not None
        logger: logging.Logger = self.__logger
        busy_clients: set[_socket.socket] = self.__busy_clients
        for socket, key_data in server_selector.get_all_registered_clients():
            client = key_data.client
            try:
                if socket in busy_clients or client.is_closed():
                    continue
                request: _RequestT
                try:
                    request = next(key_data.consumer)
                except StopIteration:  # Not enough data
                    continue
                except StreamProtocolParseError as exc:
                    logger.info("Malformed request sent by %s", client.address)
                    self.bad_request(client, exc.error_type, exc.message, exc.error_info)
                    continue
                logger.info("Processing request sent by %s", client.address)
                with ExitStack() as stack:
                    server_selector.remove_client_for_reading(socket)
                    busy_clients.add(socket)
                    stack.callback(busy_clients.discard, socket)
                    stack.callback(self.__add_client_for_reading_unless_closed, server_selector, socket)
                    if request_executor is not None:
                        fut = request_executor.execute(self.__execute_request, request, client, os.getpid())
                        fut.add_done_callback(stack.pop_all().close)
                        del fut
                    else:
                        self.__execute_request(request, client)
            except Exception:
                self.__request_handling_error_and_close_client(client, shutdown=True)

    def __execute_request(
        self,
        request: _RequestT,
        client: ConnectedClient[_ResponseT],
        pid: int | None = None,
    ) -> None:
        in_subprocess: bool = pid is not None and pid != os.getpid()
        with ExitStack() as stack:
            if in_subprocess:
                stack.callback(self.__flush_unless_closed, client)
            try:
                self.process_request(request, client)
            except Exception:
                if in_subprocess:
                    raise
                self.__request_handling_error_and_close_client(client, shutdown=True)

    @staticmethod
    def __add_client_for_reading_unless_closed(selector: _ServerSocketSelector[Any, Any], socket: _socket.socket) -> None:
        try:
            selector.add_client_for_reading(socket)
        except KeyError:  # unregistered client
            pass

    @staticmethod
    def __flush_unless_closed(client: ConnectedClient[_ResponseT]) -> None:
        if not client.is_closed():
            client.flush()

    @abstractmethod
    def process_request(self, request: _RequestT, client: ConnectedClient[_ResponseT]) -> None:
        raise NotImplementedError

    def __request_handling_error_and_close_client(self, client: ConnectedClient[Any], *, shutdown: bool) -> None:
        self.__log_request_handling_error(client, _get_exception)
        try:
            self.handle_error(client, _get_exception)
        finally:
            try:
                if shutdown:
                    client.shutdown(_socket.SHUT_WR)
            except OSError:
                pass
            finally:
                client.close()

    def __log_request_handling_error(self, client: ConnectedClient[Any], exc_info: Callable[[], BaseException | None]) -> None:
        exception = exc_info()
        if exception is None:
            return

        try:
            logger: logging.Logger = self.__logger

            logger.error("-" * 40)
            logger.error("Exception occurred during processing of request from %s", client.address, exc_info=exception)
            logger.error("-" * 40)
        finally:
            del exception

    def handle_error(self, client: ConnectedClient[_ResponseT], exc_info: Callable[[], BaseException | None]) -> None:
        pass

    def server_close(self) -> None:
        if not self.__is_shutdown.is_set():
            raise RuntimeError("Cannot close running server. Use shutdown() first")
        if (listener_socket := self.__listener_socket) is None:
            return
        if (server_selector := self.__server_selector) is not None:
            self.__server_selector = None
            server_selector.close()
        self.__listener_socket = None
        listener_socket.close()

    def shutdown(self) -> None:
        if self.__listener_socket is None:
            raise RuntimeError("Closed server")
        self.__looping = False
        self.__is_shutdown.wait()

    def __verify_client_task(self, client_socket: _socket.socket, address: SocketAddress) -> tuple[bool, bytes]:
        with TCPNetworkClient(client_socket, protocol=self.__protocol, give=False) as client:
            accepted = self.verify_new_client(client, address)
            return accepted, client._get_buffer()

    def verify_new_client(self, client: TCPNetworkClient[_ResponseT, _RequestT], address: SocketAddress) -> bool:
        return True

    def bad_request(self, client: ConnectedClient[_ResponseT], error_type: ParseErrorType, message: str, error_info: Any) -> None:
        pass

    def on_connection(self, client: ConnectedClient[_ResponseT]) -> None:
        pass

    def on_disconnection(self, client: ConnectedClient[_ResponseT]) -> None:
        pass

    @final
    def protocol(self) -> StreamProtocol[_ResponseT, _RequestT]:
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
        return self.__send_flags

    @property
    @final
    def recv_flags(self) -> int:
        return self.__recv_flags


if TYPE_CHECKING:
    from typing import TypedDict as _TypedDict

    @type_check_only
    class _ServerSocketSelectResult(_TypedDict, Generic[_RequestT, _ResponseT]):
        listeners: list[_socket.socket]
        clients: list[tuple[_socket.socket, int, _SelectorKeyData[_RequestT, _ResponseT]]]


class _ServerSocketSelector(Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__factory",
        "__listener_selector",
        "__poll_interval",
        "__clients_selectors_list",
        "__client_to_selector_map",
        "__client_data_map",
        "__selector_exit_stack",
        "__listener_lock",
        "__clients_lock",
    )

    def __init__(
        self,
        factory: Callable[[], BaseSelector],
        poll_interval: float,
    ) -> None:
        poll_interval = float(poll_interval)
        if poll_interval < 0:
            raise ValueError("'poll_interval': Negative value")
        self.__factory: Callable[[], BaseSelector] = factory
        self.__listener_selector: BaseSelector = factory()
        self.__clients_selectors_list: list[BaseSelector] = [factory()]  # At least one selector
        self.__client_to_selector_map: WeakKeyDictionary[_socket.socket, BaseSelector] = WeakKeyDictionary()
        self.__client_data_map: WeakKeyDictionary[_socket.socket, _SelectorKeyData[_RequestT, _ResponseT]] = WeakKeyDictionary()
        self.__selector_exit_stack = ExitStack()
        self.__listener_lock = RLock()
        self.__clients_lock = RLock()
        self.__poll_interval = poll_interval
        self.__selector_exit_stack.callback(self.__client_data_map.clear)
        self.__selector_exit_stack.callback(self.__client_to_selector_map.clear)
        self.__selector_exit_stack.callback(self.__clients_selectors_list.clear)
        self.__selector_exit_stack.enter_context(self.__listener_selector)
        self.__selector_exit_stack.enter_context(self.__clients_selectors_list[0])

    def close(self) -> None:
        return self.__selector_exit_stack.close()

    def select(self) -> _ServerSocketSelectResult[_RequestT, _ResponseT]:
        ready_clients = self.__clients_select(self.__poll_interval)
        ready_listeners = self.__listeners_select(0)
        return {
            "listeners": ready_listeners,
            "clients": ready_clients,
        }

    def add_listener_socket(self, socket: _socket.socket) -> None:
        with self.__listener_lock:
            self.__listener_selector.register(socket, EVENT_READ)

    def remove_listener_socket(self, socket: _socket.socket) -> None:
        with self.__listener_lock:
            self.__listener_selector.unregister(socket)

    def __listeners_select(self, timeout: float) -> list[_socket.socket]:
        with self.__listener_lock:
            if not self.__listener_selector.get_map():
                return []
            return [key.fileobj for key, _ in self.__listener_selector.select(timeout=timeout)]  # type: ignore[misc]

    def register_client(self, socket: _socket.socket, data: _SelectorKeyData[_RequestT, _ResponseT]) -> None:
        with self.__clients_lock:
            self.__client_data_map[socket] = data

    def unregister_client(self, socket: _socket.socket) -> _SelectorKeyData[_RequestT, _ResponseT]:
        with self.__clients_lock:
            data = self.__client_data_map.pop(socket)
            client_selector = self.__client_to_selector_map.pop(socket, None)
            if client_selector is not None:
                with suppress(KeyError):
                    client_selector.unregister(socket)
            return data

    def add_client_for_reading(self, socket: _socket.socket) -> None:
        return self.__add_client(socket, EVENT_READ)

    def remove_client_for_reading(self, socket: _socket.socket) -> None:
        return self.__remove_client(socket, EVENT_READ)

    def add_client_for_writing(self, socket: _socket.socket) -> None:
        return self.__add_client(socket, EVENT_WRITE)

    def remove_client_for_writing(self, socket: _socket.socket) -> None:
        return self.__remove_client(socket, EVENT_WRITE)

    def __add_client(self, socket: _socket.socket, event_mask: int) -> None:
        with self.__clients_lock:
            data = self.__client_data_map[socket]
            try:
                client_selector = self.__client_to_selector_map[socket]
            except KeyError:  # No selectors before
                self.__client_to_selector_map[socket] = client_selector = self.__get_available_client_selector()
            try:
                events: int = client_selector.get_key(socket).events
            except KeyError:
                client_selector.register(socket, event_mask, data)
                return
            client_selector.modify(socket, events | event_mask, data)

    def __remove_client(self, socket: _socket.socket, event_mask: int) -> None:
        with self.__clients_lock:
            data = self.__client_data_map[socket]
            try:
                client_selector = self.__client_to_selector_map[socket]
                events: int = client_selector.get_key(socket).events
            except KeyError:
                return
            events = events & ~event_mask
            if events:
                client_selector.modify(socket, events, data)
            else:
                client_selector.unregister(socket)
                del self.__client_to_selector_map[socket]

    def __get_available_client_selector(self) -> BaseSelector:
        # SelectSelector have a limit of file descriptor to manage, and the register() is not blocked if the limit is reached
        # because the ValueError is raised when calling select.select() and FD_SETSIZE value cannot be retrieved on Python side.
        # FD_SETSIZE is usually around 1024, so it is assumed that exceeding the limit will possibly cause the selector to fail.
        for client_selector in self.__clients_selectors_list:
            if not isinstance(client_selector, SelectSelector):
                break
            if len(client_selector.get_map()) < 512:  # Keep a margin from the 1024 ceiling, just to be sure
                break
        else:  # All selectors are "full"
            client_selector = self.__factory()
            self.__selector_exit_stack.enter_context(client_selector)
            self.__clients_selectors_list.append(client_selector)
        return client_selector

    def __clients_select(self, timeout: float) -> list[tuple[_socket.socket, int, _SelectorKeyData[_RequestT, _ResponseT]]]:
        with self.__clients_lock:
            return [
                (key.fileobj, event, key.data)  # type: ignore[misc]
                for key, event in chain.from_iterable(
                    client_selector.select(timeout=timeout if idx == 0 else 0)
                    for idx, client_selector in enumerate(filter(lambda s: s.get_map(), self.__clients_selectors_list))
                )
            ]

    def has_client(self, socket: _socket.socket) -> bool:
        with self.__clients_lock:
            return socket in self.__client_data_map

    def get_all_registered_clients(self) -> list[tuple[_socket.socket, _SelectorKeyData[_RequestT, _ResponseT]]]:
        with self.__clients_lock:
            return list(self.__client_data_map.items())


@dataclass(init=False, slots=True)
class _SelectorKeyData(Generic[_RequestT, _ResponseT]):
    consumer: StreamDataConsumer[_RequestT]
    client: ConnectedClient[_ResponseT]
    lock: RLock

    def __init__(
        self,
        *,
        protocol: StreamProtocol[_ResponseT, _RequestT],
        socket: _socket.socket,
        address: SocketAddress,
        server_selector: _ServerSocketSelector[_RequestT, _ResponseT],
        on_close: Callable[[ConnectedClient[_ResponseT]], Any],
        logger: logging.Logger,
        send_flags: int,
    ) -> None:
        self.consumer = StreamDataConsumer(protocol)
        self.lock = RLock()
        self.client = self.__ConnectedTCPClient(
            producer=StreamDataProducer(protocol),
            socket=socket,
            address=address,
            server_selector=server_selector,
            lock=self.lock,
            on_close=on_close,
            logger=logger,
            send_flags=send_flags,
        )

    @final
    class __ConnectedTCPClient(ConnectedClient[_ResponseT]):
        __slots__ = (
            "__producer",
            "__socket",
            "__socket_proxy",
            "__server_selector",
            "__lock",
            "__unsent_data",
            "__on_close",
            "__logger",
            "__send_flags",
        )

        def __init__(
            self,
            *,
            producer: StreamDataProducer[_ResponseT],
            socket: _socket.socket,
            address: SocketAddress,
            server_selector: _ServerSocketSelector[Any, _ResponseT],
            lock: RLock,
            on_close: Callable[[ConnectedClient[_ResponseT]], Any],
            logger: logging.Logger,
            send_flags: int,
        ) -> None:
            super().__init__(address)
            self.__lock: RLock = lock
            self.__producer: StreamDataProducer[_ResponseT] = producer
            self.__socket: _socket.socket | None = socket
            self.__socket_proxy: SocketProxy = SocketProxy(socket, lock=self.__lock)
            self.__server_selector: _ServerSocketSelector[Any, _ResponseT] = server_selector
            self.__unsent_data: bytes = b""
            self.__on_close: Callable[[ConnectedClient[_ResponseT]], Any] = on_close
            self.__send_flags: int = send_flags
            self.__logger: logging.Logger = logger

        def close(self) -> None:
            with self.__lock:
                socket = self.__socket
                self.__socket = None
                if socket is None:
                    return
                logger: logging.Logger = self.__logger
                logger.info("Client shutdown requested")
                try:
                    self.__server_selector.unregister_client(socket)
                except KeyError:
                    return
                with suppress(Exception):
                    socket.close()
                try:
                    self.__on_close(self)
                except Exception:
                    logger.exception("Error when calling self.on_disconnect()")
                finally:
                    logger.info("%s disconnected", self.address)

        def shutdown(self, how: int) -> None:
            with self.__lock:
                socket = self.__check_not_closed()
                try:
                    if how != _socket.SHUT_RD:
                        self.flush()
                except OSError:
                    pass
                finally:
                    socket.shutdown(how)

        def flush(self) -> None:
            with self.__lock:
                socket = self.__check_not_closed()
                logger: logging.Logger = self.__logger
                unsent_data: bytes = self.__unsent_data
                self.__unsent_data = b""
                if unsent_data:
                    logger.debug("Try sending remaining data to %s", self.address)
                    try:
                        nb_bytes_sent = socket.send(unsent_data, self.__send_flags)
                        _check_real_socket_state(socket)
                    except (TimeoutError, BlockingIOError, InterruptedError):
                        self.__unsent_data = unsent_data
                        self.__server_selector.add_client_for_writing(socket)
                        logger.debug("-> Failed to send data, bail out.")
                        return
                    if nb_bytes_sent < len(unsent_data):
                        self.__unsent_data = unsent_data[nb_bytes_sent:]
                        self.__server_selector.add_client_for_writing(socket)
                        logger.debug("-> %d byte(s) sent and %d byte(s) queued", nb_bytes_sent, len(self.__unsent_data))
                        return
                self.__server_selector.remove_client_for_writing(socket)
                self.__send_queued_packets()

        def send_packet(self, packet: _ResponseT) -> None:
            with self.__lock:
                self.__check_not_closed()
                self.__producer.queue(packet)
                logger: logging.Logger = self.__logger
                logger.info("A response will be sent to %s", self.address)
                if self.__unsent_data:  # A previous attempt failed
                    logger.debug("-> There is unsent data, bail out.")
                    return
                self.__send_queued_packets()

        def __send_queued_packets(self) -> None:
            logger: logging.Logger = self.__logger
            socket: _socket.socket | None = self.__socket
            assert socket is not None
            socket_send = socket.send
            send_flags: int = self.__send_flags
            total_nb_bytes_sent: int = 0
            for chunk in self.__producer:
                try:
                    nb_bytes_sent = socket_send(chunk, send_flags)
                    _check_real_socket_state(socket)
                except (TimeoutError, BlockingIOError, InterruptedError):
                    self.__unsent_data = chunk
                    self.__server_selector.add_client_for_writing(socket)
                    logger.debug("-> Failed to send data, bail out.")
                    break
                total_nb_bytes_sent += nb_bytes_sent
                if nb_bytes_sent < len(chunk):
                    self.__unsent_data = chunk[nb_bytes_sent:]
                    self.__server_selector.add_client_for_writing(socket)
                    break
            logger.debug("-> %d byte(s) sent and %d byte(s) queued", total_nb_bytes_sent, len(self.__unsent_data))

        def __check_not_closed(self) -> _socket.socket:
            socket = self.__socket
            if socket is None:
                raise OSError(errno.EPIPE, os.strerror(errno.EPIPE))
            return socket

        def is_closed(self) -> bool:
            with self.__lock:
                return self.__socket is None

        @property
        def socket(self) -> SocketProxy:
            return self.__socket_proxy


def _get_exception() -> BaseException | None:
    return sys.exc_info()[1]
