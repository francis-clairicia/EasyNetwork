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

import logging
import os
import sys
from abc import ABCMeta, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from functools import partial
from itertools import chain
from selectors import EVENT_READ, EVENT_WRITE, BaseSelector, SelectSelector
from socket import SHUT_WR, SOCK_STREAM, socket as Socket
from threading import Event, RLock
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ContextManager,
    Generic,
    Iterator,
    NamedTuple,
    Sequence,
    TypeAlias,
    TypeVar,
    final,
    overload,
)
from weakref import WeakKeyDictionary, ref

from ..converter import PacketConversionError
from ..protocol import StreamProtocol, StreamProtocolParseError
from ..serializers.exceptions import DeserializeError
from ..tools.socket import AF_INET, SocketAddress, create_server, guess_best_buffer_size, new_socket_address
from ..tools.stream import StreamDataConsumer, StreamDataProducer
from .abc import AbstractNetworkServer
from .executors.abc import AbstractRequestExecutor

if TYPE_CHECKING:
    from selectors import SelectorKey as __DefaultSelectorKey
    from typing import type_check_only

    from _typeshed import OptExcInfo

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
    def transaction(self) -> ContextManager[None]:
        raise NotImplementedError

    @abstractmethod
    def shutdown(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_packet(self, packet: _ResponseT) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_packets(self, *packets: _ResponseT) -> None:
        raise NotImplementedError

    @overload
    @abstractmethod
    def getsockopt(self, __level: int, __optname: int, /) -> int:
        ...

    @overload
    @abstractmethod
    def getsockopt(self, __level: int, __optname: int, __buflen: int, /) -> bytes:
        ...

    @abstractmethod
    def getsockopt(self, *args: int) -> int | bytes:
        raise NotImplementedError

    @overload
    @abstractmethod
    def setsockopt(self, __level: int, __optname: int, __value: int | bytes, /) -> None:
        ...

    @overload
    @abstractmethod
    def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
        ...

    @abstractmethod
    def setsockopt(self, *args: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_closed(self) -> bool:
        raise NotImplementedError

    @property
    @final
    def address(self) -> SocketAddress:
        return self.__addr


StreamProtocolFactory: TypeAlias = Callable[[], StreamProtocol[_ResponseT, _RequestT]]


class AbstractTCPNetworkServer(AbstractNetworkServer[_RequestT, _ResponseT], Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__listener_socket",
        "__addr",
        "__protocol_factory",
        "__request_executor",
        "__closed",
        "__loop",
        "__is_shutdown",
        "__clients",
        "__clients_lock",
        "__server_selector",
        "__default_backlog",
        "__buffered_write",
        "__disable_nagle_algorithm",
        "__send_flags",
        "__recv_flags",
        "__verify_client_pool",
        "__logger",
    )

    def __init__(
        self,
        address: tuple[str, int] | tuple[str, int, int, int],
        protocol_factory: StreamProtocolFactory[_ResponseT, _RequestT],
        *,
        family: int = AF_INET,
        backlog: int | None = None,
        reuse_port: bool = False,
        dualstack_ipv6: bool = False,
        send_flags: int = 0,
        recv_flags: int = 0,
        buffered_write: bool = False,
        disable_nagle_algorithm: bool = False,
        request_executor: AbstractRequestExecutor | None = None,
        selector_factory: Callable[[], BaseSelector] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if not callable(protocol_factory):
            raise TypeError("Invalid arguments")
        assert request_executor is None or isinstance(request_executor, AbstractRequestExecutor)
        send_flags = int(send_flags)
        recv_flags = int(recv_flags)
        super().__init__()
        self.__listener_socket: Socket = create_server(
            address,
            family=family,
            type=SOCK_STREAM,
            backlog=backlog,
            reuse_port=reuse_port,
            dualstack_ipv6=dualstack_ipv6,
        )
        self.__request_executor: AbstractRequestExecutor | None = request_executor
        self.__default_backlog: int | None = backlog
        self.__addr: SocketAddress = new_socket_address(self.__listener_socket.getsockname(), self.__listener_socket.family)
        self.__closed: bool = False
        self.__protocol_factory: StreamProtocolFactory[_ResponseT, _RequestT] = protocol_factory
        if selector_factory is None:
            from selectors import DefaultSelector

            selector_factory = DefaultSelector
        self.__loop: bool = False
        self.__is_shutdown: Event = Event()
        self.__is_shutdown.set()
        self.__clients: WeakKeyDictionary[Socket, _SelectorKeyData[_RequestT, _ResponseT]] = WeakKeyDictionary()
        self.__clients_lock = RLock()
        self.__server_selector: _ServerSocketSelector[_RequestT, _ResponseT] = _ServerSocketSelector(selector_factory)
        self.__send_flags: int = send_flags
        self.__recv_flags: int = recv_flags
        self.__buffered_write: bool = bool(buffered_write)
        self.__disable_nagle_algorithm: bool = bool(disable_nagle_algorithm)
        self.__verify_client_pool: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="TCPNetworkServer[verify_client]",
        )
        self.__logger: logging.Logger = logger or logging.getLogger(__name__)

    def serve_forever(self) -> None:
        self._check_not_closed()
        if self.running():
            raise RuntimeError("Server already running")

        server_selector: _ServerSocketSelector[_RequestT, _ResponseT] = self.__server_selector
        request_executor: AbstractRequestExecutor | None = self.__request_executor
        logger: logging.Logger = self.__logger

        try:
            self.__is_shutdown.clear()
            self.__loop = True

            with server_selector:
                server_selector.add_listener_socket(self.__listener_socket)

                logger.info("Start serving at %s", self.__addr)

                while self.__loop:
                    ready_listeners = server_selector.listener_select()
                    ready_clients = server_selector.clients_select()
                    if not self.__loop:
                        break  # type: ignore[unreachable]

                    for listener_socket in ready_listeners:
                        self.__accept_new_client(listener_socket)

                    for key in (key for key, event in ready_clients if event & EVENT_WRITE):
                        logger.debug("%s is ready for writing", key.data.client.address)
                        self.__flush_client_data(key, only_unsent=True)

                    for key in (key for key, event in ready_clients if event & EVENT_READ):
                        logger.debug("%s is ready for reading", key.data.client.address)
                        self.__receive_data(key)
                    self.__handle_all_clients_requests()

                    if request_executor is not None:
                        request_executor.service_actions()
                    self.service_actions()
                    if self.__buffered_write:
                        for key in self.__server_selector.get_all_client_keys():
                            self.__send_data_to_client(key)
        finally:
            try:
                for key in self.__server_selector.get_all_client_keys():
                    self.__shutdown_client(key.fileobj, from_client=False)
            finally:
                self.__loop = False
                self.__is_shutdown.set()
                logger.info("Server stopped")

    @final
    def is_closed(self) -> bool:
        return self.__closed

    @final
    def running(self) -> bool:
        return not self.__is_shutdown.is_set()

    def service_actions(self) -> None:
        pass

    def __accept_new_client(self, listener_socket: Socket) -> None:
        try:
            client_socket, address = listener_socket.accept()
        except OSError:
            return
        address = new_socket_address(address, client_socket.family)

        self.__logger.info("Accepted new connection (peername = %s)", address)

        future = self.__verify_client_pool.submit(self.verify_new_client, client_socket, address)
        future.add_done_callback(partial(self.__add_client_callback, socket=client_socket, address=address))

    def __add_client_callback(self, future: Future[bool], /, *, socket: Socket, address: SocketAddress) -> None:
        logger: logging.Logger = self.__logger

        try:
            accepted = future.result()
        except BaseException:
            logger.exception("An exception occured when verifying client %s", address)
            with suppress(Exception):
                socket.close()
            return
        finally:
            del future
        if not accepted or not self.__loop:
            if not accepted:
                logger.warning("A client (address = %s) was not accepted by verification", address)
            with suppress(Exception):
                socket.close()
            return

        socket.settimeout(0)

        if self.__disable_nagle_algorithm:
            from socket import IPPROTO_TCP, TCP_NODELAY

            try:
                socket.setsockopt(IPPROTO_TCP, TCP_NODELAY, True)
            except Exception:
                logger.exception("Failed to apply TCP_NODELAY socket option")

        selfref = ref(self)

        def _close_client_hook(socket: Socket) -> None:
            self = selfref()
            if self is None:
                return
            self.__shutdown_client(socket, from_client=True)

        def _flush_client_data_hook(socket: Socket) -> None:
            self = selfref()
            if self is None:
                return
            try:
                key = self.__server_selector.get_client_key(socket)
            except KeyError:
                return
            self.__flush_client_data(key, only_unsent=False)

        def _send_data_to_client_hook(socket: Socket) -> None:
            self = selfref()
            if self is None or self.__buffered_write:
                return
            try:
                key = self.__server_selector.get_client_key(socket)
            except KeyError:
                return
            self.__send_data_to_client(key)

        def _client_is_closed_hook(socket: Socket) -> bool:
            self = selfref()
            if self is None:
                return False
            with self.__clients_lock:
                return socket not in self.__clients

        key_data = _SelectorKeyData(
            protocol=self.__protocol_factory(),
            socket=socket,
            address=address,
            flush=_flush_client_data_hook,
            send=_send_data_to_client_hook,
            on_close=_close_client_hook,
            is_closed=_client_is_closed_hook,
        )
        self.__server_selector.add_client_reader(socket, key_data)
        with self.__clients_lock:
            self.__clients[socket] = key_data

        logger.info("A client (address = %s) was added", address)

    def __receive_data(self, key: _SelectorKey[_RequestT, _ResponseT]) -> None:
        logger: logging.Logger = self.__logger
        socket: Socket = key.fileobj
        key_data: _SelectorKeyData[_RequestT, _ResponseT] = key.data
        client = key_data.client
        data: bytes
        logger.debug("Receiving data from %s", client.address)
        if client.is_closed():
            logger.warning("-> Tried to read on closed client (address = %s)", client.address)
            return
        try:
            data = socket.recv(key_data.recv_size, self.__recv_flags)
        except (BlockingIOError, InterruptedError):
            logger.debug("-> Interruped. Will try later")
        except OSError:
            try:
                self.handle_error(client, sys.exc_info())
            finally:
                self.__shutdown_client(socket, from_client=False)
        else:
            if not data:  # Closed connection (EOF)
                logger.info("-> Remote side closed the connection")
                self.__shutdown_client(socket, from_client=False)
            else:
                logger.debug("-> Received %d bytes", len(data))
                key_data.consumer.feed(data)

    def __handle_all_clients_requests(self) -> None:
        logger: logging.Logger = self.__logger
        request_executor: AbstractRequestExecutor | None = self.__request_executor
        for key in self.__server_selector.get_all_client_keys():
            key_data: _SelectorKeyData[_RequestT, _ResponseT] = key.data
            client = key_data.client
            if client.is_closed() or not key_data.consumer.get_buffer():
                continue
            request: _RequestT
            try:
                request = next(key_data.consumer)
            except StreamProtocolParseError as exc:
                logger.info("Malformed request sent by %s", client.address)
                try:
                    self.bad_request(client, exc.exception)
                except Exception:
                    try:
                        self.handle_error(client, sys.exc_info())
                    finally:
                        self.__shutdown_client(key.fileobj, from_client=False)
                continue
            except StopIteration:  # Not enough data
                logger.debug("Missing data to process request sent by %s", client.address)
                continue
            logger.info("Processing request sent by %s", client.address)
            try:
                if request_executor is not None:
                    request_executor.execute(self.__execute_request, request, key, pid=os.getpid())
                else:
                    self.__execute_request(request, key)
            except Exception as exc:
                if request_executor is not None:
                    raise RuntimeError(f"request_executor.execute() raised an exception: {exc}") from exc
                raise RuntimeError(f"Error when processing request: {exc}") from exc

    def __execute_request(self, request: _RequestT, key: _SelectorKey[_RequestT, _ResponseT], pid: int | None = None) -> None:
        in_subprocess: bool = pid is not None and pid != os.getpid()
        try:
            if in_subprocess:
                self.__execute_in_subprocess_setup(key)
            self.process_request(request, key.data.client)
        except Exception:
            try:
                self.handle_error(key.data.client, sys.exc_info())
            finally:
                self.__shutdown_client(key.fileobj, from_client=True)
        else:
            if in_subprocess:
                self.__flush_client_data(key, only_unsent=False)

    def __execute_in_subprocess_setup(self, key: _SelectorKey[_RequestT, _ResponseT]) -> None:
        self.__listener_socket.close()
        for client in self.get_clients():
            if client is not key.data.client:
                client.close()

    @abstractmethod
    def process_request(self, request: _RequestT, client: ConnectedClient[_ResponseT]) -> None:
        raise NotImplementedError

    def handle_error(self, client: ConnectedClient[Any], exc_info: OptExcInfo) -> None:
        if exc_info == (None, None, None):
            return

        logger: logging.Logger = self.__logger

        logger.error("-" * 40)
        logger.error("Exception occurred during processing of request from %s", client.address, exc_info=exc_info)
        logger.error("-" * 40)

    def __send_data_to_client(self, key: _SelectorKey[_RequestT, _ResponseT]) -> None:
        logger: logging.Logger = self.__logger

        if not key.data.producer.pending_packets():
            return
        logger.info("A response will be sent to %s", key.data.client.address)
        if key.data.unsent_data:  # A previous attempt failed
            logger.debug("-> There is unsent data, bail out.")
            return
        self.__flush_client_data(key, only_unsent=False)

    def __flush_client_data(self, key: _SelectorKey[_RequestT, _ResponseT], *, only_unsent: bool) -> None:
        logger: logging.Logger = self.__logger
        socket: Socket = key.fileobj
        key_data = key.data

        if key_data.client.is_closed():
            return

        logger.debug("Sending data to %s", key_data.client.address)

        with key_data.send_lock:
            data_to_send: bytes = key_data.unsent_data
            key_data.unsent_data = b""
            if not only_unsent:
                data_to_send += b"".join(list(key_data.producer))
            if not data_to_send:
                self.__server_selector.remove_client_writer(socket)
                logger.debug("-> No data to send")
                return
            try:
                nb_bytes_sent = socket.send(data_to_send, self.__send_flags)
            except (TimeoutError, InterruptedError):
                key_data.unsent_data = data_to_send
                self.__server_selector.add_client_writer(socket, key_data)
                logger.debug("-> Failed to send data, bail out.")
            except BlockingIOError as exc:
                try:
                    character_written: int = exc.characters_written
                except AttributeError:
                    character_written = 0
                finally:
                    del exc
                key_data.unsent_data = data_to_send[character_written:]
                self.__server_selector.add_client_writer(socket, key_data)
                logger.debug("-> Failed to send data, bail out.")
            except OSError:
                try:
                    self.handle_error(key_data.client, sys.exc_info())
                finally:
                    self.__shutdown_client(socket, from_client=False)
            else:
                if nb_bytes_sent < len(data_to_send):
                    key_data.unsent_data = data_to_send[nb_bytes_sent:]
                    self.__server_selector.add_client_writer(socket, key_data)
                else:
                    self.__server_selector.remove_client_writer(socket)
                logger.debug("%d byte(s) sent and %d byte(s) queued", nb_bytes_sent, len(key_data.unsent_data))

    def __shutdown_client(self, socket: Socket, *, from_client: bool) -> None:
        logger: logging.Logger = self.__logger

        logger.info("Client shutdown requested")
        with self.__clients_lock:
            self.__clients.pop(socket, None)
        try:
            key = self.__server_selector.unregister_client(socket)
        except KeyError:
            logger.warning("-> Unknown client")
            return
        with suppress(Exception):
            try:
                if from_client:
                    if key.data.unsent_data or key.data.producer.pending_packets():
                        self.__flush_client_data(key, only_unsent=False)
                else:
                    socket.shutdown(SHUT_WR)
            finally:
                socket.close()
        client = key.data.client
        try:
            self.on_disconnect(client)
        except Exception:
            self.handle_error(client, sys.exc_info())
        finally:
            logger.info("%s disconnected", client.address)

    def server_close(self) -> None:
        try:
            if not self.__is_shutdown.is_set():
                raise RuntimeError("Cannot close running server. Use shutdown() first")
            if self.__closed:
                return
            self.__closed = True
            self.__listener_socket.close()
            del self.__listener_socket
        finally:
            if (request_executor := self.__request_executor) is not None:
                request_executor.on_server_close()

    def shutdown(self) -> None:
        self._check_not_closed()
        self.__loop = False
        self.__is_shutdown.wait()

    def verify_new_client(self, client_socket: Socket, address: SocketAddress) -> bool:
        return True

    def bad_request(self, client: ConnectedClient[_ResponseT], exc: DeserializeError | PacketConversionError) -> None:
        pass

    def on_disconnect(self, client: ConnectedClient[_ResponseT]) -> None:
        pass

    def stop_listening(self) -> ContextManager[None]:
        if not self.__loop:
            raise RuntimeError("Server is not running")
        return self.__server_selector.stop_listener_socket_context(self.__listener_socket, self.__default_backlog)

    @final
    def protocol(self) -> StreamProtocol[_ResponseT, _RequestT]:
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
        return self.__listener_socket.getsockopt(*args)

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: int | bytes, /) -> None:
        ...

    @overload
    def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
        ...

    @final
    def setsockopt(self, *args: Any) -> None:
        self._check_not_closed()
        return self.__listener_socket.setsockopt(*args)

    @final
    def get_clients(self) -> Sequence[ConnectedClient[_ResponseT]]:
        with self.__clients_lock:
            self._check_not_closed()
            return tuple(filter(lambda client: not client.is_closed(), (k.client for k in self.__clients.values())))

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
        return self.__send_flags

    @property
    @final
    def recv_flags(self) -> int:
        return self.__recv_flags


if TYPE_CHECKING:

    @type_check_only
    class _SelectorKey(NamedTuple, Generic[_RequestT, _ResponseT]):
        fileobj: Socket
        fd: int
        events: int
        data: _SelectorKeyData[_RequestT, _ResponseT]


class _ServerSocketSelector(Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__factory",
        "__listener_sock_selector",
        "__clients_selectors_list",
        "__clients_selectors_map",
        "__selector_exit_stack",
        "__listener_lock",
        "__clients_lock",
    )

    def __init__(self, factory: Callable[[], BaseSelector]) -> None:
        self.__factory: Callable[[], BaseSelector] = factory
        self.__listener_sock_selector: BaseSelector = factory()
        self.__clients_selectors_list: list[BaseSelector] = [factory()]  # At least one selector
        self.__clients_selectors_map: WeakKeyDictionary[Socket, BaseSelector] = WeakKeyDictionary()
        self.__selector_exit_stack = ExitStack()
        self.__listener_lock = RLock()
        self.__clients_lock = RLock()
        self.__selector_exit_stack.enter_context(self.__listener_sock_selector)
        self.__selector_exit_stack.enter_context(self.__clients_selectors_list[0])

    def __enter__(self) -> None:
        return

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        with self.__listener_lock, self.__clients_lock:
            try:
                self.__selector_exit_stack.close()
            finally:
                self.__clients_selectors_list.clear()
                self.__clients_selectors_map.clear()

    def add_listener_socket(self, socket: Socket) -> None:
        with self.__listener_lock:
            self.__listener_sock_selector.register(socket, EVENT_READ)

    @contextmanager
    def stop_listener_socket_context(self, socket: Socket, default_backlog: int | None = None) -> Iterator[None]:
        key: __DefaultSelectorKey | None
        selector: BaseSelector = self.__listener_sock_selector
        with self.__listener_lock:
            try:
                key = selector.unregister(socket)
            except KeyError:
                key = None
        if key is None:
            yield
            return
        try:
            socket.listen(0)
            yield
        finally:
            if default_backlog is None:
                socket.listen()
            else:
                socket.listen(default_backlog)
            with self.__listener_lock:
                selector.register(key.fileobj, key.events, key.data)

    def listener_select(self) -> list[Socket]:
        with self.__listener_lock:
            if not self.__listener_sock_selector.get_map():
                return []
            return [key.fileobj for key, _ in self.__listener_sock_selector.select(timeout=0)]  # type: ignore[misc]

    def unregister_client(self, socket: Socket) -> _SelectorKey[_RequestT, _ResponseT]:
        with self.__clients_lock:
            client_selector = self.__clients_selectors_map.pop(socket)
            return client_selector.unregister(socket)  # type: ignore[return-value]

    def add_client_reader(self, socket: Socket, data: _SelectorKeyData[_RequestT, _ResponseT]) -> None:
        with self.__clients_lock:
            try:
                client_selector = self.__clients_selectors_map[socket]
            except KeyError:
                self.__clients_selectors_map[socket] = client_selector = self.__get_client_selector_for_new_client()
                client_selector.register(socket, EVENT_READ, data)
            else:
                self.__add_event_mask_or_register(socket, client_selector, EVENT_READ, data)

    def remove_client_reader(self, socket: Socket) -> None:
        with self.__clients_lock:
            client_selector = self.__clients_selectors_map[socket]
            self.__remove_event_mask_or_unregister(socket, client_selector, EVENT_READ)

    def add_client_writer(self, socket: Socket, data: _SelectorKeyData[_RequestT, _ResponseT]) -> None:
        with self.__clients_lock:
            try:
                client_selector = self.__clients_selectors_map[socket]
            except KeyError:
                self.__clients_selectors_map[socket] = client_selector = self.__get_client_selector_for_new_client()
                client_selector.register(socket, EVENT_WRITE, data)
            else:
                self.__add_event_mask_or_register(socket, client_selector, EVENT_WRITE, data)

    def remove_client_writer(self, socket: Socket) -> None:
        with self.__clients_lock:
            client_selector = self.__clients_selectors_map[socket]
            self.__remove_event_mask_or_unregister(socket, client_selector, EVENT_WRITE)

    def __get_client_selector_for_new_client(self) -> BaseSelector:
        # SelectSelector have a limit of file descriptor to manage, and the register() is not blocked if the limit is reached
        # because the ValueError is raised when calling select.select() and FD_SETSIZE value cannot be retrieved on Python side.
        # FD_SETSIZE is usually around 1024, so it is assumed that exceeding the limit will possibly cause the selector to fail.
        client_selector: BaseSelector = self.__clients_selectors_list[-1]
        if isinstance(client_selector, SelectSelector):
            if len(client_selector.get_map()) >= 512:  # Keep a margin from the 1024 ceiling, just to be sure
                client_selector = self.__factory()
                self.__clients_selectors_list.append(client_selector)
                self.__selector_exit_stack.enter_context(client_selector)
        return client_selector

    @staticmethod
    def __add_event_mask_or_register(socket: Socket, selector: BaseSelector, event: int, data: Any) -> None:
        try:
            actual_key: __DefaultSelectorKey = selector.get_key(socket)
        except KeyError:
            selector.register(socket, event, data)
            return
        if not (actual_key.events & event):
            selector.modify(socket, actual_key.events | event, data)

    @staticmethod
    def __remove_event_mask_or_unregister(socket: Socket, selector: BaseSelector, event: int) -> None:
        try:
            key: __DefaultSelectorKey = selector.get_key(socket)
        except KeyError:
            return

        new_events: int = key.events & ~event
        if not new_events:
            selector.unregister(socket)
        else:
            selector.modify(socket, new_events, key.data)

    def clients_select(self) -> list[tuple[_SelectorKey[_RequestT, _ResponseT], int]]:
        with self.__clients_lock:
            return list(
                chain.from_iterable(
                    client_selector.select(timeout=0)  # type: ignore[misc]
                    for client_selector in self.__clients_selectors_list
                    if client_selector.get_map()
                )
            )

    def get_client_key(self, socket: Socket) -> _SelectorKey[_RequestT, _ResponseT]:
        with self.__clients_lock:
            client_selector = self.__clients_selectors_map[socket]
            return client_selector.get_key(socket)  # type: ignore[return-value]

    def get_all_client_keys(self) -> list[_SelectorKey[_RequestT, _ResponseT]]:
        with self.__clients_lock:
            return list(chain.from_iterable(s.get_map().values() for s in self.__clients_selectors_list))  # type: ignore[misc]


@dataclass(init=False, slots=True)
class _SelectorKeyData(Generic[_RequestT, _ResponseT]):
    producer: StreamDataProducer[_ResponseT]
    consumer: StreamDataConsumer[_RequestT]
    recv_size: int
    client: ConnectedClient[_ResponseT]
    unsent_data: bytes
    send_lock: RLock

    def __init__(
        self,
        *,
        protocol: StreamProtocol[_ResponseT, _RequestT],
        socket: Socket,
        address: SocketAddress,
        flush: Callable[[Socket], None],
        send: Callable[[Socket], None],
        on_close: Callable[[Socket], None],
        is_closed: Callable[[Socket], bool],
    ) -> None:
        self.producer = StreamDataProducer(protocol)
        self.consumer = StreamDataConsumer(protocol, on_error="raise")
        self.recv_size = guess_best_buffer_size(socket)
        self.client = self.__ConnectedTCPClient(
            producer=self.producer,
            socket=socket,
            address=address,
            flush=flush,
            send=send,
            on_close=on_close,
            is_closed=is_closed,
        )
        self.unsent_data = b""
        self.send_lock = RLock()

    @final
    class __ConnectedTCPClient(ConnectedClient[_ResponseT]):
        __slots__ = ("__p", "__s", "__transaction_lock", "__flush", "__send", "__on_close", "__is_closed")

        def __init__(
            self,
            *,
            producer: StreamDataProducer[_ResponseT],
            socket: Socket,
            address: SocketAddress,
            flush: Callable[[Socket], None],
            send: Callable[[Socket], None],
            on_close: Callable[[Socket], None],
            is_closed: Callable[[Socket], bool],
        ) -> None:
            super().__init__(address)
            self.__p: StreamDataProducer[_ResponseT] = producer
            self.__s: Socket | None = socket
            self.__flush: Callable[[Socket], None] = flush
            self.__send: Callable[[Socket], None] = send
            self.__on_close: Callable[[Socket], None] = on_close
            self.__is_closed: Callable[[Socket], bool] = is_closed
            self.__transaction_lock = RLock()

        def close(self) -> None:
            with self.__transaction_lock:
                socket = self.__s
                self.__s = None
                if socket is not None and not self.__is_closed(socket):
                    self.__on_close(socket)

        @contextmanager
        def transaction(self) -> Iterator[None]:
            with self.__transaction_lock:
                yield

        def shutdown(self) -> None:
            with self.__transaction_lock:
                socket = self.__s
                self.__s = None
                if socket is not None and not self.__is_closed(socket):
                    try:
                        self.__flush(socket)
                    finally:
                        try:
                            socket.shutdown(SHUT_WR)
                        except OSError:
                            pass
                        finally:
                            self.__on_close(socket)

        def send_packet(self, packet: _ResponseT) -> None:
            with self.__transaction_lock:
                socket = self.__check_not_closed()
                self.__p.queue(packet)
                self.__send(socket)

        def send_packets(self, *packets: _ResponseT) -> None:
            with self.__transaction_lock:
                socket = self.__check_not_closed()
                self.__p.queue(*packets)
                self.__send(socket)

        @overload
        def getsockopt(self, __level: int, __optname: int, /) -> int:
            ...

        @overload
        def getsockopt(self, __level: int, __optname: int, __buflen: int, /) -> bytes:
            ...

        def getsockopt(self, *args: int) -> int | bytes:
            with self.__transaction_lock:
                socket = self.__check_not_closed()
                return socket.getsockopt(*args)

        @overload
        def setsockopt(self, __level: int, __optname: int, __value: int | bytes, /) -> None:
            ...

        @overload
        def setsockopt(self, __level: int, __optname: int, __value: None, __optlen: int, /) -> None:
            ...

        def setsockopt(self, *args: Any) -> None:
            with self.__transaction_lock:
                socket = self.__check_not_closed()
                return socket.setsockopt(*args)

        def __check_not_closed(self) -> Socket:
            socket = self.__s
            if socket is None or self.__is_closed(socket):
                self.__s = None
                raise RuntimeError("Closed client")
            return socket

        def is_closed(self) -> bool:
            with self.__transaction_lock:
                return (socket := self.__s) is None or self.__is_closed(socket)
