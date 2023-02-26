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

import contextlib as _contextlib
import functools as _functools
import logging as _logging
import selectors as _selectors
import socket as _socket
import sys as _sys
import threading as _threading
from abc import ABCMeta, abstractmethod
from concurrent.futures import Future as _Future, ThreadPoolExecutor as _ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar, final
from weakref import WeakSet as _WeakSet

from ..client.tcp import TCPNetworkClient
from ..protocol import ParseErrorType, StreamProtocol, StreamProtocolParseError
from ..tools._utils import check_real_socket_state as _check_real_socket_state
from ..tools.socket import MAX_STREAM_BUFSIZE, SocketAddress, SocketProxy, new_socket_address
from ..tools.stream import StreamDataConsumer, StreamDataProducer
from .abc import AbstractNetworkServer

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
        "__listener_lock",
        "__protocol",
        "__looping",
        "__is_shutdown",
        "__server_selector",
        "__selector_factory",
        "__selector_poll_interval",
        "__disable_nagle_algorithm",
        "__thread_pool_size",
        "__logger",
    )

    max_recv_size: int = MAX_STREAM_BUFSIZE  # Buffer size passed to recv().

    def __init__(
        self,
        address: tuple[str, int] | tuple[str, int, int, int],
        protocol: StreamProtocol[_ResponseT, _RequestT],
        *,
        family: int = _socket.AF_INET,
        backlog: int | None = None,
        reuse_port: bool = False,
        dualstack_ipv6: bool = False,
        disable_nagle_algorithm: bool = False,
        selector_factory: Callable[[], _selectors.BaseSelector] | None = None,
        poll_interval: float = 0.1,
        thread_pool_size: int | None = 0,
        logger: _logging.Logger | None = None,
    ) -> None:
        super().__init__()
        assert isinstance(protocol, StreamProtocol)

        if family not in (_socket.AF_INET, _socket.AF_INET6):
            raise ValueError("Only AF_INET and AF_INET6 families are supported")

        self.__listener_socket: _socket.socket | None = None
        listener_socket: _socket.socket = _socket.create_server(
            address,
            family=family,
            backlog=backlog,
            reuse_port=reuse_port,
            dualstack_ipv6=dualstack_ipv6,
        )
        try:
            listener_socket.setblocking(False)
            self.__listener_lock = _threading.RLock()
            self.__thread_pool_size: int | None = int(thread_pool_size) if thread_pool_size is not None else None
            self.__protocol: StreamProtocol[_ResponseT, _RequestT] = protocol
            self.__looping: bool = False
            self.__is_shutdown: _threading.Event = _threading.Event()
            self.__is_shutdown.set()
            if selector_factory is None:
                selector_factory = _selectors.DefaultSelector
            self.__selector_factory: Callable[[], _selectors.BaseSelector] = selector_factory
            self.__server_selector: _ServerSocketSelector[_RequestT, _ResponseT] | None = None
            self.__selector_poll_interval: float = float(poll_interval)
            self.__disable_nagle_algorithm: bool = bool(disable_nagle_algorithm)
            self.__logger: _logging.Logger = logger or _logging.getLogger(__name__)
        except BaseException:
            try:
                listener_socket.close()
            finally:
                raise

        self.__listener_socket = listener_socket

    def __del__(self) -> None:
        try:
            listener_socket: _socket.socket | None = self.__listener_socket
        except AttributeError:
            return
        self.__listener_socket = None
        if listener_socket is not None:
            listener_socket.close()

    @final
    def is_closed(self) -> bool:
        return self.__listener_socket is None

    @final
    def running(self) -> bool:
        return not self.__is_shutdown.is_set()

    def server_close(self) -> None:
        with self.__listener_lock:
            if (listener_socket := self.__listener_socket) is None:
                return
            if (server_selector := self.__server_selector) is not None:
                try:
                    server_selector.remove_listener_socket(listener_socket)
                except KeyError:
                    pass
            self.__listener_socket = None
            listener_socket.close()

    def shutdown(self) -> None:
        self.__looping = False
        self.__is_shutdown.wait()

    def serve_forever(self) -> None:
        if (listener_socket := self.__listener_socket) is None:
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
            server_selector: _ServerSocketSelector[_RequestT, _ResponseT] = _ServerSocketSelector(
                factory=self.__selector_factory,
                poll_interval=self.__selector_poll_interval,
            )
            self.__looping = True
            self.__server_selector = server_selector

            def _reset_values(self: AbstractTCPNetworkServer[Any, Any]) -> None:
                self.__server_selector = None
                self.__looping = False

            server_exit_stack.callback(_reset_values, self)
            server_exit_stack.callback(server_selector.close)
            ################

            # Setup client verification's thread pool
            verify_client_executor: _ThreadPoolExecutor = _ThreadPoolExecutor(
                max_workers=1,  # Do not need more than that
                thread_name_prefix=f"{self.__class__.__name__}[verify_client]",
            )
            server_exit_stack.callback(verify_client_executor.shutdown, wait=True, cancel_futures=True)
            #########################################

            # Setup client requests' thread pool
            request_executor: _ThreadPoolExecutor | None = None
            if self.__thread_pool_size is None or self.__thread_pool_size != 0:
                request_executor = _ThreadPoolExecutor(
                    max_workers=self.__thread_pool_size,
                    thread_name_prefix=f"{self.__class__.__name__}[request_executor]",
                )
                server_exit_stack.callback(request_executor.shutdown, wait=True, cancel_futures=False)
            ####################################

            # Enable listener
            server_selector.add_listener_socket(listener_socket)
            self.__logger.info("Start serving at %s", ", ".join(map(str, self.get_addresses())))
            #################

            # Pull methods to local namespace
            select = server_selector.select
            get_clients_with_pending_requests = server_selector.get_clients_with_pending_requests
            accept_new_client = self._accept_new_client
            service_actions = self.service_actions
            #################################

            # Pull globals to local namespace
            EVENT_READ: int = _selectors.EVENT_READ
            EVENT_WRITE: int = _selectors.EVENT_WRITE
            #################################

            # Main loop
            while self.__looping:
                ready = select()
                if not self.__looping:  # shutdown() called during select()
                    break  # type: ignore[unreachable]

                for listener_socket in ready["listeners"]:
                    accept_new_client(listener_socket, verify_client_executor)

                for client, event in ready["clients"]:
                    if event & EVENT_WRITE:
                        client.ready_for_writing()
                    if event & EVENT_READ:
                        client.ready_for_reading()

                for client in get_clients_with_pending_requests():
                    client.process_pending_request(request_executor)

                service_actions()

    def service_actions(self) -> None:
        pass

    def _accept_new_client(
        self,
        listener_socket: _socket.socket,
        verify_client_executor: _ThreadPoolExecutor,
    ) -> None:
        with self.__listener_lock:
            if self.__listener_socket is None:  # all listeners are closed
                return
            try:
                client_socket, address = listener_socket.accept()
            except OSError:
                return
        address = new_socket_address(address, client_socket.family)

        self.__logger.info("Accepted new connection (address = %s)", address)

        future = verify_client_executor.submit(self._verify_client_task, client_socket, address)
        try:
            future.add_done_callback(_functools.partial(self._add_client_callback, socket=client_socket, address=address))
        finally:
            del future

    def _add_client_callback(
        self,
        future: _Future[tuple[bool, bytes]],
        *,
        socket: _socket.socket,
        address: SocketAddress,
    ) -> None:
        from concurrent.futures import CancelledError

        logger: _logging.Logger = self.__logger

        try:
            accepted, remaining_data = future.result()
            server_selector: _ServerSocketSelector[_RequestT, _ResponseT] | None = self.__server_selector
            assert server_selector is not None
        except CancelledError:  # shutdown requested
            socket.close()
            return
        except BaseException:
            logger.exception("An exception occured when verifying client %s", address)
            socket.close()
            return
        finally:
            del future
        if not accepted:
            logger.warning("A client (address = %s) was not accepted by verification", address)
            socket.close()
            return

        socket.setblocking(False)

        if self.__disable_nagle_algorithm:
            try:
                socket.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, True)
            except Exception:
                logger.warning("Failed to disable Nagle algorithm")

        client = _ClientPayload(
            socket=socket,
            address=address,
            server=self,
            selector=server_selector,
        )
        server_selector.register_client(client)
        server_selector.add_client_for_reading(client)
        client._consumer.feed(remaining_data)
        self.on_connection(client._api)

    def _verify_client_task(self, client_socket: _socket.socket, address: SocketAddress) -> tuple[bool, bytes]:
        with TCPNetworkClient(client_socket, protocol=self.__protocol, give=False) as client:
            accepted = self.verify_new_client(client, address)
            return accepted, client._get_buffer()

    def verify_new_client(self, client: TCPNetworkClient[_ResponseT, _RequestT], address: SocketAddress) -> bool:
        return True

    def on_connection(self, client: ConnectedClient[_ResponseT]) -> None:
        pass

    def on_disconnection(self, client: ConnectedClient[_ResponseT]) -> None:
        pass

    @abstractmethod
    def process_request(self, request: _RequestT, client: ConnectedClient[_ResponseT]) -> None:
        raise NotImplementedError

    def bad_request(self, client: ConnectedClient[_ResponseT], error_type: ParseErrorType, message: str, error_info: Any) -> None:
        pass

    def handle_error(self, client: ConnectedClient[Any], exc_info: Callable[[], BaseException | None]) -> None:
        exception = exc_info()
        if exception is None:
            return

        try:
            logger: _logging.Logger = self.__logger

            logger.error("-" * 40)
            logger.error("Exception occurred during processing of request from %s", client.address, exc_info=exception)
            logger.error("-" * 40)
        finally:
            del exception

    @final
    def protocol(self) -> StreamProtocol[_ResponseT, _RequestT]:
        return self.__protocol

    @final
    def get_addresses(self) -> tuple[SocketAddress, ...]:
        if (listener := self.__listener_socket) is None:
            return ()
        return (new_socket_address(listener.getsockname(), listener.family),)

    @property
    @final
    def logger(self) -> _logging.Logger:
        return self.__logger


if TYPE_CHECKING:
    from typing import TypedDict as _TypedDict

    @type_check_only
    class _ServerSocketSelectResult(_TypedDict, Generic[_RequestT, _ResponseT]):
        listeners: list[_socket.socket]
        clients: list[tuple[_ClientPayload[_RequestT, _ResponseT], int]]


class _ServerSocketSelector(Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__listener_selector",
        "__poll_interval",
        "__clients_set",
        "__client_selector",
        "__client_to_selector_map",
        "__selector_exit_stack",
        "__listener_lock",
        "__clients_lock",
    )

    EVENT_READ = _selectors.EVENT_READ
    EVENT_WRITE = _selectors.EVENT_WRITE

    def __init__(
        self,
        factory: Callable[[], _selectors.BaseSelector],
        poll_interval: float,
    ) -> None:
        poll_interval = float(poll_interval)
        if poll_interval < 0:
            raise ValueError("'poll_interval': Negative value")
        self.__listener_selector: _selectors.BaseSelector = factory()
        self.__client_selector: _selectors.BaseSelector = factory()
        self.__clients_set: _WeakSet[_ClientPayload[_RequestT, _ResponseT]] = _WeakSet()
        self.__selector_exit_stack: _contextlib.ExitStack = _contextlib.ExitStack()
        self.__listener_lock: _threading.RLock = _threading.RLock()
        self.__clients_lock: _threading.RLock = _threading.RLock()
        self.__poll_interval: float = poll_interval
        self.__selector_exit_stack.callback(self.__clients_set.clear)
        self.__selector_exit_stack.enter_context(self.__listener_selector)
        self.__selector_exit_stack.enter_context(self.__client_selector)

    def close(self) -> None:
        # All remaining clients must be closed before
        for client in list(self.__clients_set):
            self.__selector_exit_stack.callback(client.close)
        return self.__selector_exit_stack.close()

    def select(self) -> _ServerSocketSelectResult[_RequestT, _ResponseT]:
        ready_clients = self.__clients_select(self.__poll_interval)
        if self.__clients_set:
            ready_listeners = self.__listeners_select(0)
        else:
            ready_listeners = self.__listeners_select(self.__poll_interval)
        return {
            "listeners": ready_listeners,
            "clients": ready_clients,
        }

    def add_listener_socket(self, socket: _socket.socket) -> None:
        with self.__listener_lock:
            self.__listener_selector.register(socket, self.EVENT_READ)

    def remove_listener_socket(self, socket: _socket.socket) -> None:
        with self.__listener_lock:
            self.__listener_selector.unregister(socket)

    def __listeners_select(self, timeout: float) -> list[_socket.socket]:
        with self.__listener_lock:
            if not self.__listener_selector.get_map():
                return []
            return [key.fileobj for key, _ in self.__listener_selector.select(timeout=timeout)]  # type: ignore[misc]

    def register_client(self, client: _ClientPayload[_RequestT, _ResponseT]) -> None:
        with self.__clients_lock:
            self.__clients_set.add(client)

    def unregister_client(self, client: _ClientPayload[_RequestT, _ResponseT]) -> None:
        with self.__clients_lock:
            client_selector = self.__client_selector
            self.__clients_set.discard(client)
            try:
                client_selector.unregister(client)
            except KeyError:
                pass

    def add_client_for_reading(self, client: _ClientPayload[_RequestT, _ResponseT]) -> None:
        return self.__add_client(client, self.EVENT_READ)

    def remove_client_for_reading(self, client: _ClientPayload[_RequestT, _ResponseT]) -> None:
        return self.__remove_client(client, self.EVENT_READ)

    def add_client_for_writing(self, client: _ClientPayload[_RequestT, _ResponseT]) -> None:
        return self.__add_client(client, self.EVENT_WRITE)

    def remove_client_for_writing(self, client: _ClientPayload[_RequestT, _ResponseT]) -> None:
        return self.__remove_client(client, self.EVENT_WRITE)

    def __add_client(self, client: _ClientPayload[_RequestT, _ResponseT], event_mask: int) -> None:
        with self.__clients_lock:
            if client not in self.__clients_set:
                raise KeyError(client)
            client_selector = self.__client_selector
            try:
                events: int = client_selector.get_key(client).events
            except KeyError:
                client_selector.register(client, event_mask)
                return
            client_selector.modify(client, events | event_mask)

    def __remove_client(self, client: _ClientPayload[_RequestT, _ResponseT], event_mask: int) -> None:
        with self.__clients_lock:
            if client not in self.__clients_set:
                raise KeyError(client)
            client_selector = self.__client_selector
            try:
                events: int = client_selector.get_key(client).events
            except KeyError:
                return
            events = events & ~event_mask
            if events:
                client_selector.modify(client, events)
            else:
                client_selector.unregister(client)

    def __clients_select(self, timeout: float) -> list[tuple[_ClientPayload[_RequestT, _ResponseT], int]]:
        # TODO: Handle SelectSelector() side effect ?
        # (c.f. https://codeghar.com/blog/use-select-in-python-socket-programming-at-your-own-risk.html)

        with self.__clients_lock:
            if not self.__client_selector.get_map():
                return []
            return [(key.fileobj, event) for key, event in self.__client_selector.select(timeout=timeout)]  # type: ignore[misc]

    def has_client(self, client: _ClientPayload[_RequestT, _ResponseT]) -> bool:
        with self.__clients_lock:
            return client in self.__clients_set

    def get_all_registered_clients(self) -> list[_ClientPayload[_RequestT, _ResponseT]]:
        with self.__clients_lock:
            return list(self.__clients_set)

    def get_clients_with_pending_requests(self) -> list[_ClientPayload[_RequestT, _ResponseT]]:
        with self.__clients_lock:
            return list(
                filter(
                    lambda client: client._request_future is None and client._consumer.get_buffer(),
                    self.__clients_set,
                )
            )


class _ClientPayload(Generic[_RequestT, _ResponseT]):
    """Helper class to manage a client socket"""

    __slots__ = (
        "_socket",
        "_api",
        "_producer",
        "_consumer",
        "_lock",
        "_request_future",
        "_unsent_data",
        "_server",
        "_selector",
        "_logger",
        "__weakref__",
    )

    def __init__(
        self,
        socket: _socket.socket,
        address: SocketAddress,
        server: AbstractTCPNetworkServer[_RequestT, _ResponseT],
        selector: _ServerSocketSelector[_RequestT, _ResponseT],
    ) -> None:
        protocol = server.protocol()
        self._socket: _socket.socket | None = socket
        self._consumer: StreamDataConsumer[_RequestT] = StreamDataConsumer(protocol)
        self._producer: StreamDataProducer[_ResponseT] = StreamDataProducer(protocol)
        self._lock = _threading.RLock()
        self._request_future: _Future[None] | None = None
        self._unsent_data: bytearray = bytearray()
        self._server: AbstractTCPNetworkServer[_RequestT, _ResponseT] = server
        self._logger: _logging.Logger = server.logger
        self._selector: _ServerSocketSelector[_RequestT, _ResponseT] = selector
        self._api: _ClientPayload._ConnectedClientAPI[_ResponseT] = self._ConnectedClientAPI(self, address)

    def fileno(self) -> int:  # Needed for selector
        with self._lock:
            if (socket := self._socket) is None:
                return -1
            return socket.fileno()

    def close(self) -> None:
        with self._lock:
            if (socket := self._socket) is None:
                return
            with _contextlib.suppress(Exception), _contextlib.ExitStack() as stack:
                stack.callback(self._logger.info, "%s disconnected", self._api.address)
                stack.callback(self._server.on_disconnection, self._api)
                stack.callback(setattr, self, "_server", None)  # Explicit reference break
                stack.callback(setattr, self, "_socket", None)
                stack.callback(socket.close)
                stack.callback(socket.shutdown, _socket.SHUT_WR)
                stack.callback(self._api._put_to_closed_state)
                stack.callback(self._selector.unregister_client, self)
                stack.callback(self._flush_unsent_data_and_packets, closing_context=True)

    def ready_for_reading(self) -> None:
        with self._lock:
            if (socket := self._socket) is None:
                return
            logger: _logging.Logger = self._logger
            data: bytes
            logger.debug("Receiving data from %s", self._api.address)
            try:
                data = socket.recv(self._server.max_recv_size)
                if not data:  # Closed connection (EOF)
                    raise ConnectionAbortedError
            except (TimeoutError, BlockingIOError, InterruptedError):
                logger.debug("Blocking IO error when reading %s. Will try later.", self._api.address)
                return
            except ConnectionError:
                self.close()
                return
            except OSError:
                self._request_error_handling_and_close()
                return
            logger.debug("Received %d bytes from %s", len(data), self._api.address)
            self._consumer.feed(data)

    def ready_for_writing(self) -> None:
        with self._lock:
            if self._socket is None:
                return
            self._flush_unsent_data_and_packets(closing_context=False)

    def process_pending_request(self, request_executor: _ThreadPoolExecutor | None) -> None:
        request_future: _Future[None] | None = None
        with self._lock:
            if self._socket is None:
                return
            if self._request_future is not None:
                return
            logger: _logging.Logger = self._logger
            request: _RequestT
            try:
                try:
                    request = next(self._consumer)
                except StopIteration:  # Not enough data
                    return
                except StreamProtocolParseError as exc:
                    logger.debug("Malformed request sent by %s", self._api.address)
                    self._server.bad_request(self._api, exc.error_type, exc.message, exc.error_info)
                    return
                logger.debug("Processing request sent by %s", self._api.address)
                if request_executor is not None:
                    try:
                        self._request_future = request_future = request_executor.submit(self._execute_request, request)
                    except RuntimeError:  # shutdown() asked
                        return
                    self._selector.remove_client_for_reading(self)
            except Exception:
                self._request_error_handling_and_close()
                return

        # Blocking operation out of lock scope (deadlock possible if not)

        if request_future is None:
            self._execute_request(request)
        else:
            try:
                request_future.add_done_callback(self._request_task_done)
            finally:
                del request_future

    def _execute_request(self, request: _RequestT) -> None:
        try:
            self._server.process_request(request, self._api)
        except Exception:
            self._request_error_handling_and_close()

    def _request_task_done(self, future: _Future[None]) -> None:
        try:
            with self._lock:
                assert future is self._request_future
                self._request_future = None
                if not future.cancelled():
                    try:
                        self._selector.add_client_for_reading(self)
                    except KeyError:  # Closed client
                        pass
        finally:
            del future

    def _flush_unsent_data_and_packets(self, *, closing_context: bool) -> None:
        socket: _socket.socket | None = self._socket
        assert socket is not None

        logger: _logging.Logger = self._logger
        unsent_data: bytearray = self._unsent_data
        if unsent_data:
            logger.debug("Try sending remaining data to %s", self._api.address)
            try:
                nb_bytes_sent = socket.send(unsent_data)
                _check_real_socket_state(socket)
            except (TimeoutError, BlockingIOError, InterruptedError):
                logger.debug("Failed to send data, bail out.")
                if not closing_context:
                    self._selector.add_client_for_writing(self)
                return
            except ConnectionError:
                if not closing_context:
                    self.close()
                return
            except OSError:
                if not closing_context:
                    self._request_error_handling_and_close()
                return
            del unsent_data[:nb_bytes_sent]
            if unsent_data:
                self._selector.add_client_for_writing(self)
                logger.debug("%d byte(s) sent to %s and %d byte(s) queued", nb_bytes_sent, self._api.address, len(unsent_data))
                return
            logger.debug("%d byte(s) sent to %s", nb_bytes_sent, self._api.address)
        if not closing_context:
            self._selector.remove_client_for_writing(self)
        if self._producer.pending_packets():
            logger.debug("Try sending queued packets to %s", self._api.address)
            self._send_queued_packets(closing_context=closing_context)

    def _send_queued_packets(self, *, closing_context: bool) -> None:
        socket: _socket.socket | None = self._socket
        assert socket is not None

        logger: _logging.Logger = self._logger
        unsent_data: bytearray = self._unsent_data
        socket_send = socket.send
        total_nb_bytes_sent: int = 0

        for chunk in self._producer:
            try:
                nb_bytes_sent = socket_send(chunk)
                _check_real_socket_state(socket)
            except (TimeoutError, BlockingIOError, InterruptedError):
                unsent_data.extend(chunk)
                if not closing_context:
                    self._selector.add_client_for_writing(self)
                break
            except ConnectionError:
                if not closing_context:
                    self.close()
                return
            except OSError:
                if not closing_context:
                    self._request_error_handling_and_close()
                return

            total_nb_bytes_sent += nb_bytes_sent
            if nb_bytes_sent < len(chunk):
                unsent_data.extend(chunk[nb_bytes_sent:])
                if not closing_context:
                    self._selector.add_client_for_writing(self)
                break
        logger.debug("%d byte(s) sent to %s and %d byte(s) queued", total_nb_bytes_sent, self._api.address, len(unsent_data))

    def _request_error_handling_and_close(self) -> None:
        try:
            self._server.handle_error(self._api, _get_exception)
        finally:
            self.close()

    @final
    class _ConnectedClientAPI(ConnectedClient[_ResponseT]):
        __slots__ = ("__client_ref", "__socket_proxy", "__h")

        def __init__(self, client: _ClientPayload[_RequestT, _ResponseT], address: SocketAddress) -> None:
            super().__init__(address)

            import weakref

            assert client._socket is not None

            self.__client_ref: Callable[[], _ClientPayload[_RequestT, _ResponseT] | None] = weakref.ref(client)
            self.__socket_proxy: SocketProxy = SocketProxy(client._socket, lock=client._lock)
            self.__h: int

        def __hash__(self) -> int:
            try:
                return self.__h
            except AttributeError:
                self.__h = h = hash(self.__client_ref)
                return h

        def is_closed(self) -> bool:
            return self.__client_ref() is None

        def close(self) -> None:
            client = self.__client_ref()
            if client is None:
                return
            client.close()

        def _put_to_closed_state(self) -> None:
            self.__client_ref = lambda: None

        def send_packet(self, packet: _ResponseT) -> None:
            client = self.__client_ref()
            if client is None:
                return
            with client._lock:
                if client._socket is None:  # Other thread closed the client, bail out silently
                    return
                client._producer.queue(packet)
                if client._unsent_data:  # A previous attempt failed
                    client._logger.debug("A response has been queued for %s", self.address)
                else:
                    client._logger.debug("A response will be sent to %s", self.address)
                    client._send_queued_packets(closing_context=False)

        @property
        def socket(self) -> SocketProxy:
            return self.__socket_proxy


def _get_exception() -> BaseException | None:
    return _sys.exc_info()[1]
