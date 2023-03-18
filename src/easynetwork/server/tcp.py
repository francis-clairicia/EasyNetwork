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
import logging as _logging
import selectors as _selectors
import socket as _socket
import sys as _sys
import threading as _threading
from abc import ABCMeta, abstractmethod
from concurrent.futures import Future as _Future, ThreadPoolExecutor as _ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable, Generic, Iterator, TypeVar, final
from weakref import WeakSet as _WeakSet

from ..exceptions import StreamProtocolParseError
from ..protocol import StreamProtocol
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
        "__listener_addr",
        "__protocol",
        "__looping",
        "__is_shutdown",
        "__is_up",
        "__server_selector",
        "__selector_factory",
        "__selector_poll_interval",
        "__disable_nagle_algorithm",
        "__incremental_write",
        "__thread_pool_size",
        "__logger",
    )

    max_recv_size: int = MAX_STREAM_BUFSIZE  # Buffer size passed to recv().

    def __init__(
        self,
        host: str,
        port: int,
        protocol: StreamProtocol[_ResponseT, _RequestT],
        *,
        family: int = _socket.AF_INET,
        backlog: int | None = None,
        reuse_port: bool = False,
        dualstack_ipv6: bool = False,
        incremental_write: bool = False,
        disable_nagle_algorithm: bool = False,
        selector_factory: Callable[[], _selectors.BaseSelector] | None = None,
        poll_interval: float = 0.1,
        thread_pool_size: int = 0,
        logger: _logging.Logger | None = None,
    ) -> None:
        super().__init__()
        assert isinstance(protocol, StreamProtocol)

        if family not in (_socket.AF_INET, _socket.AF_INET6):
            raise ValueError("Only AF_INET and AF_INET6 families are supported")

        self.__listener_socket: _socket.socket | None = None
        listener_socket: _socket.socket = _socket.create_server(
            (host, port),
            family=family,
            backlog=backlog,
            reuse_port=reuse_port,
            dualstack_ipv6=dualstack_ipv6,
        )
        try:
            listener_socket.setblocking(False)
            self.__listener_lock = _threading.RLock()
            self.__listener_addr: SocketAddress = new_socket_address(listener_socket.getsockname(), listener_socket.family)
            self.__thread_pool_size: int = int(thread_pool_size)
            self.__protocol: StreamProtocol[_ResponseT, _RequestT] = protocol
            self.__looping: bool = False
            self.__is_shutdown: _threading.Event = _threading.Event()
            self.__is_shutdown.set()
            self.__is_up: _threading.Event = _threading.Event()
            self.__is_up.clear()
            if selector_factory is None:
                selector_factory = _selectors.DefaultSelector
            self.__selector_factory: Callable[[], _selectors.BaseSelector] = selector_factory
            self.__server_selector: _ServerSocketSelector[_RequestT, _ResponseT] | None = None
            self.__selector_poll_interval: float = float(poll_interval)
            self.__incremental_write: bool = bool(incremental_write)
            self.__disable_nagle_algorithm: bool = bool(disable_nagle_algorithm)
            self.__logger: _logging.Logger = logger or _logging.getLogger(__name__)
        except BaseException:
            try:
                listener_socket.close()
            finally:
                raise

        self.__listener_socket = listener_socket

    def __del__(self) -> None:  # pragma: no cover
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

    @final
    def wait_for_server_to_be_up(self, timeout: float | None = None) -> bool:
        return self.__is_up.wait(timeout=timeout)

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
        if not self.__is_shutdown.is_set():
            raise RuntimeError("Server is already running")

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

            def _reset_selector(self: AbstractTCPNetworkServer[Any, Any]) -> None:
                self.__server_selector = None

            self.__server_selector = server_selector
            server_exit_stack.callback(_reset_selector, self)
            server_exit_stack.callback(server_selector.close)
            ################

            # Setup client requests' thread pool
            request_executor: _ThreadPoolExecutor | None = None
            if self.__thread_pool_size != 0:
                request_executor = _ThreadPoolExecutor(
                    max_workers=self.__thread_pool_size if self.__thread_pool_size != -1 else None,
                    thread_name_prefix=f"{self.__class__.__name__}[request_executor]",
                )
                server_exit_stack.callback(request_executor.shutdown, wait=True, cancel_futures=False)
                server_exit_stack.callback(self.__logger.info, "Server loop break, waiting for thread pool to be closed...")
            ####################################

            # Enable listener
            server_selector.add_listener_socket(listener_socket)
            self.__logger.info("Start serving at %s", self.__listener_addr)
            #################

            # Pull methods to local namespace
            select = server_selector.select
            nb_listeners = server_selector.nb_listeners
            nb_clients = server_selector.nb_clients
            get_clients_with_pending_requests = server_selector.get_clients_with_pending_requests
            accept_new_client = self._accept_new_client
            #################################

            # Pull globals to local namespace
            EVENT_READ: int = _selectors.EVENT_READ
            EVENT_WRITE: int = _selectors.EVENT_WRITE
            #################################

            # Server is up
            def _reset_loop_state(self: AbstractTCPNetworkServer[Any, Any]) -> None:
                self.__looping = False

            self.__looping = True
            server_exit_stack.callback(_reset_loop_state, self)
            self.__is_up.set()
            server_exit_stack.callback(self.__is_up.clear)
            ##############

            # Main loop
            while self.__looping:
                if nb_listeners() < 1 and nb_clients() < 1:
                    break
                ready = select()
                if not self.__looping:  # shutdown() called during select()
                    break  # type: ignore[unreachable]

                for listener_socket in ready["listeners"]:
                    accept_new_client(listener_socket)

                for client, event in ready["clients"]:
                    if event & EVENT_WRITE:
                        client.ready_for_writing()
                    if event & EVENT_READ:
                        client.ready_for_reading()

                for client in get_clients_with_pending_requests():
                    client.process_pending_request(request_executor)

                self.service_actions()

    def service_actions(self) -> None:
        pass

    def _accept_new_client(self, listener_socket: _socket.socket) -> None:
        if (server_selector := self.__server_selector) is None:
            raise RuntimeError("Closed server")

        logger: _logging.Logger = self.__logger

        with self.__listener_lock:
            try:
                client_socket, address = listener_socket.accept()
            except OSError:  # listener closed while waiting for lock
                return
        address = new_socket_address(address, client_socket.family)

        logger.info("Accepted new connection (address = %s)", address)

        client_socket.setblocking(False)

        if self.__disable_nagle_algorithm:
            try:
                client_socket.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, True)
            except Exception:
                pass

        client = _ClientPayload(
            socket=client_socket,
            address=address,
            server=self,
            selector=server_selector,
            incremental_write=self.__incremental_write,
        )
        server_selector.register_client(client)
        server_selector.add_client_for_reading(client)

        try:
            self.on_connection(client._api)
        except BaseException:
            logger.exception("Error occured when verifying client %s", address)
            client._api.close()
            return

    def on_connection(self, client: ConnectedClient[_ResponseT]) -> None:
        pass  # pragma: no cover

    def on_disconnection(self, client: ConnectedClient[_ResponseT]) -> None:
        pass  # pragma: no cover

    @abstractmethod
    def process_request(self, request: _RequestT, client: ConnectedClient[_ResponseT]) -> None:
        raise NotImplementedError

    def bad_request(
        self,
        client: ConnectedClient[_ResponseT],
        error_type: StreamProtocolParseError.ParseErrorType,
        message: str,
        error_info: Any,
    ) -> None:
        pass  # pragma: no cover

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
    def get_address(self) -> SocketAddress:
        return self.__listener_addr

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
        "__weakref__",
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
        for client in self.__clients_set:
            self.__selector_exit_stack.callback(client._api.close)
        return self.__selector_exit_stack.close()

    def select(self) -> _ServerSocketSelectResult[_RequestT, _ResponseT]:
        if self.__clients_set:
            ready_clients = self.__clients_select(self.__poll_interval)
            ready_listeners = self.__listeners_select(0)
        else:
            ready_clients = self.__clients_select(0)
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

    def nb_listeners(self) -> int:
        with self.__listener_lock:
            return len(self.__listener_selector.get_map())

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

    def nb_clients(self) -> int:
        with self.__clients_lock:
            return len(self.__clients_set)

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
        "_incremental_write",
        "__weakref__",
    )

    def __init__(
        self,
        socket: _socket.socket,
        address: SocketAddress,
        server: AbstractTCPNetworkServer[_RequestT, _ResponseT],
        selector: _ServerSocketSelector[_RequestT, _ResponseT],
        incremental_write: bool,
    ) -> None:
        import weakref

        protocol = server.protocol()
        self._socket: _socket.socket | None = socket
        self._consumer: StreamDataConsumer[_RequestT] = StreamDataConsumer(protocol)
        self._producer: StreamDataProducer[_ResponseT] = StreamDataProducer(protocol)
        self._lock = _threading.RLock()
        self._request_future: _Future[None] | None = None
        self._unsent_data: bytearray = bytearray()
        self._server: AbstractTCPNetworkServer[_RequestT, _ResponseT] = weakref.proxy(server)
        self._logger: _logging.Logger = server.logger
        self._selector: _ServerSocketSelector[_RequestT, _ResponseT] = weakref.proxy(selector)
        self._api: _ClientPayload._ConnectedClientAPI[_ResponseT] = self._ConnectedClientAPI(self, address)
        self._incremental_write: bool = incremental_write

    def fileno(self) -> int:  # Needed for selector
        with self._lock:
            if (socket := self._socket) is None:
                return -1
            return socket.fileno()

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
                self._erase_all_data_and_packets_to_send()
                self._api.close()
                return
            except OSError:
                self._erase_all_data_and_packets_to_send()
                self._request_error_handling_and_close(close_client_before=True)
                return
            logger.debug("Received %d bytes from %s", len(data), self._api.address)
            self._consumer.feed(data)

    def ready_for_writing(self) -> None:
        with self._lock:
            if (socket := self._socket) is None:
                return
            logger: _logging.Logger = self._logger
            unsent_data: bytearray = self._unsent_data
            if unsent_data:
                logger.debug("Try sending remaining data to %s", self._api.address)
                try:
                    nb_bytes_sent = socket.send(unsent_data)
                    _check_real_socket_state(socket)
                except (TimeoutError, BlockingIOError, InterruptedError):
                    logger.debug("Failed to send data, bail out.")
                    self._selector.add_client_for_writing(self)
                    return
                except ConnectionError:
                    self._erase_all_data_and_packets_to_send()
                    self._api.close()
                    return
                except OSError:
                    self._erase_all_data_and_packets_to_send()
                    self._request_error_handling_and_close(close_client_before=True)
                    return
                del unsent_data[:nb_bytes_sent]
                if unsent_data:
                    self._selector.add_client_for_writing(self)
                    logger.debug(
                        "%d byte(s) sent to %s and %d byte(s) queued", nb_bytes_sent, self._api.address, len(unsent_data)
                    )
                    return
                logger.debug("%d byte(s) sent to %s", nb_bytes_sent, self._api.address)
            self._selector.remove_client_for_writing(self)
            if self._producer.pending_packets():
                logger.debug("Try sending queued packets to %s", self._api.address)
                self._send_queued_packets()

    def process_pending_request(self, request_executor: _ThreadPoolExecutor | None) -> None:
        with self._lock:
            if self._socket is None:
                return
            if self._request_future is not None:
                return
            logger: _logging.Logger = self._logger
            try:
                try:
                    request: _RequestT = next(self._consumer)
                except StopIteration:  # Not enough data
                    return
                except StreamProtocolParseError as exc:
                    logger.debug("Malformed request sent by %s", self._api.address)
                    self._server.bad_request(self._api, exc.error_type, exc.message, exc.error_info)
                    return
                logger.debug("Processing request sent by %s", self._api.address)
                request_future: _Future[None] | None
                if request_executor is None:
                    request_future = None
                else:
                    try:
                        request_future = request_executor.submit(self._execute_request, request)
                    except RuntimeError:  # shutdown() asked
                        return
                    self._request_future = request_future
            except Exception:
                self._request_error_handling_and_close(close_client_before=False)
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
        except BaseException:
            self._request_error_handling_and_close(close_client_before=False)

    def _request_task_done(self, future: _Future[None]) -> None:
        try:
            with self._lock:
                assert future is self._request_future
                assert future.done()
                self._request_future = None
        finally:
            del future

    def _send_queued_packets(self) -> None:
        socket: _socket.socket | None = self._socket
        assert socket is not None

        logger: _logging.Logger = self._logger
        unsent_data: bytearray = self._unsent_data
        socket_send = socket.send
        total_nb_bytes_sent: int = 0

        chunk_iterator: Iterator[bytes]
        if self._incremental_write:
            chunk_iterator = self._producer
        else:
            chunk_iterator = iter([b"".join(list(self._producer))])

        for chunk in chunk_iterator:
            try:
                nb_bytes_sent = socket_send(chunk)
                _check_real_socket_state(socket)
            except (TimeoutError, BlockingIOError, InterruptedError):
                unsent_data.extend(chunk)
                self._selector.add_client_for_writing(self)
                break
            except ConnectionError:
                self._erase_all_data_and_packets_to_send()
                self._api.close()
                return
            except OSError:
                self._erase_all_data_and_packets_to_send()
                self._request_error_handling_and_close(close_client_before=True)
                return

            total_nb_bytes_sent += nb_bytes_sent
            if nb_bytes_sent < len(chunk):
                unsent_data.extend(chunk[nb_bytes_sent:])
                self._selector.add_client_for_writing(self)
                break
        logger.debug("%d byte(s) sent to %s and %d byte(s) queued", total_nb_bytes_sent, self._api.address, len(unsent_data))

    def _erase_all_data_and_packets_to_send(self) -> None:
        self._unsent_data.clear()
        self._producer.clear()

    def _send_all_unsent_data_and_packets_before_close(self) -> None:
        socket: _socket.socket | None = self._socket
        assert socket is not None

        unsent_data: bytes = bytes(self._unsent_data)
        self._unsent_data.clear()

        try:
            unsent_data = b"".join([unsent_data, *self._producer])
        except Exception:
            pass

        if unsent_data:
            self._logger.debug("Try sending remaining data to %s before closing", self._api.address)
            try:
                socket.sendall(unsent_data)
            except OSError:
                return

    def _request_error_handling_and_close(self, *, close_client_before: bool) -> None:
        if close_client_before:
            exc: BaseException | None = _get_exception()
            exc_cb: Callable[[], BaseException | None] = lambda: exc
            try:
                try:
                    self._api.close()
                finally:
                    self._server.handle_error(self._api, exc_cb)
            finally:
                del exc_cb, exc
        else:
            try:
                self._server.handle_error(self._api, _get_exception)
            finally:
                self._api.close()

    @final
    class _ConnectedClientAPI(ConnectedClient[_ResponseT]):
        __slots__ = ("__client_ref", "__socket_proxy", "__h")

        def __init__(self, client: _ClientPayload[_RequestT, _ResponseT], address: SocketAddress) -> None:
            super().__init__(address)

            import weakref

            assert client._socket is not None

            self.__client_ref: Callable[[], _ClientPayload[_RequestT, _ResponseT] | None] = weakref.ref(client)
            self.__socket_proxy: SocketProxy = SocketProxy(client._socket, lock=client._lock)
            self.__h: int = hash(client)

        def __hash__(self) -> int:
            return self.__h

        def is_closed(self) -> bool:
            return self.__client_ref() is None

        def close(self) -> None:
            client = self.__client_ref()
            if client is None:
                return
            self.__client_ref = lambda: None

            with client._lock:
                if (socket := client._socket) is None:
                    return

                with _contextlib.suppress(BaseException), _contextlib.ExitStack() as stack:
                    stack.callback(client._logger.info, "%s disconnected", self.address)
                    stack.callback(client._lock.acquire)  # Re-acquire lock after calling server.on_disconnection()
                    stack.callback(client._server.on_disconnection, self)
                    stack.callback(client._lock.release)  # Release lock before calling server.on_disconnection()
                    stack.callback(setattr, client, "_socket", None)
                    stack.callback(socket.close)
                    stack.callback(socket.shutdown, _socket.SHUT_WR)
                    stack.callback(client._consumer.clear)
                    stack.callback(client._selector.unregister_client, client)
                    stack.callback(client._send_all_unsent_data_and_packets_before_close)

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
                    client._send_queued_packets()

        @property
        def socket(self) -> SocketProxy:
            return self.__socket_proxy


def _get_exception() -> BaseException | None:
    return _sys.exc_info()[1]
