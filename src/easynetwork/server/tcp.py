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

import os
import sys
from abc import ABCMeta, abstractmethod
from collections import defaultdict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from itertools import chain
from selectors import EVENT_READ, EVENT_WRITE, BaseSelector, SelectorKey, SelectSelector
from socket import SHUT_WR, SOCK_STREAM, socket as Socket
from threading import Event, RLock
from typing import TYPE_CHECKING, Any, Callable, Final, Generic, Iterator, Sequence, TypeAlias, TypeVar, final, overload
from weakref import WeakKeyDictionary

from ..protocol import StreamProtocol
from ..tools.socket import AF_INET, SocketAddress, create_server, guess_best_buffer_size, new_socket_address
from ..tools.stream import StreamDataConsumer, StreamDataConsumerError, StreamDataProducerReader
from .abc import AbstractNetworkServer
from .executors.abc import AbstractRequestExecutor

if TYPE_CHECKING:
    from _typeshed import OptExcInfo

_RequestT = TypeVar("_RequestT")
_ResponseT = TypeVar("_ResponseT")


class ConnectedClient(Generic[_ResponseT], metaclass=ABCMeta):
    __slots__ = ("__addr", "__transaction_lock", "__weakref__")

    def __init__(self, address: SocketAddress) -> None:
        super().__init__()
        self.__addr: SocketAddress = address
        self.__transaction_lock = RLock()

    def __repr__(self) -> str:
        return f"<connected client with address {self.__addr} at {id(self):#x}{' closed' if self.closed else ''}>"

    @final
    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.__transaction_lock:
            yield

    def shutdown(self) -> None:
        with self.transaction():
            if not self.closed:
                try:
                    self.flush()
                finally:
                    self.close()

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_packet(self, packet: _ResponseT) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_packets(self, *packets: _ResponseT) -> None:
        raise NotImplementedError

    @abstractmethod
    def flush(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def closed(self) -> bool:
        raise NotImplementedError

    @property
    @final
    def address(self) -> SocketAddress:
        return self.__addr


StreamProtocolFactory: TypeAlias = Callable[[], StreamProtocol[_ResponseT, _RequestT]]


class AbstractTCPNetworkServer(AbstractNetworkServer[_RequestT, _ResponseT], Generic[_RequestT, _ResponseT]):
    __slots__ = (
        "__socket",
        "__addr",
        "__protocol_factory",
        "__selector_factory",
        "__request_executor",
        "__closed",
        "__lock",
        "__loop",
        "__is_shutdown",
        "__clients",
        "__server_selector",
        "__default_backlog",
        "__buffered_write",
        "__send_flags",
        "__recv_flags",
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
        request_executor: AbstractRequestExecutor | None = None,
        selector_factory: Callable[[], BaseSelector] | None = None,
    ) -> None:
        if not callable(protocol_factory):
            raise TypeError("Invalid arguments")
        assert request_executor is None or isinstance(request_executor, AbstractRequestExecutor)
        send_flags = int(send_flags)
        recv_flags = int(recv_flags)
        super().__init__()
        self.__socket: Socket = create_server(
            address,
            family=family,
            type=SOCK_STREAM,
            backlog=backlog,
            reuse_port=reuse_port,
            dualstack_ipv6=dualstack_ipv6,
        )
        self.__request_executor: AbstractRequestExecutor | None = request_executor
        self.__default_backlog: int | None = backlog
        self.__addr: SocketAddress = new_socket_address(self.__socket.getsockname(), self.__socket.family)
        self.__closed: bool = False
        self.__protocol_factory: StreamProtocolFactory[_ResponseT, _RequestT] = protocol_factory
        self.__selector_factory: Callable[[], BaseSelector]
        if selector_factory is None:
            from selectors import DefaultSelector

            self.__selector_factory = DefaultSelector
        else:
            self.__selector_factory = selector_factory
        self.__lock: RLock = RLock()
        self.__loop: bool = False
        self.__is_shutdown: Event = Event()
        self.__is_shutdown.set()
        self.__clients: WeakKeyDictionary[Socket, ConnectedClient[_ResponseT]] = WeakKeyDictionary()
        self.__server_selector: BaseSelector
        self.__send_flags: int = send_flags
        self.__recv_flags: int = recv_flags
        self.__buffered_write: bool = bool(buffered_write)

    def serve_forever(self) -> None:
        with self.__lock:
            self._check_not_closed()
            if self.running():
                raise RuntimeError("Server already running")
            self.__is_shutdown.clear()
            self.__server_selector = self.__selector_factory()
            self.__loop = True

        # SelectSelector have a limit of file descriptor to manage, and the register() is not blocked if the limit is reached
        # because the ValueError is raised when calling select.select() and FD_SETSIZE value cannot be retrieved on Python side.
        # FD_SETSIZE is usually around 1024, so it is assumed that exceeding the limit will possibly cause the selector to fail.
        client_selectors: deque[BaseSelector] = deque([self.__selector_factory()])  # At least one selector
        client_selectors_stack = ExitStack()
        client_selectors_map: WeakKeyDictionary[Socket, BaseSelector] = WeakKeyDictionary()

        buffered_write: Final[bool] = self.__buffered_write

        request_executor: AbstractRequestExecutor | None = self.__request_executor

        server_socket: Final[Socket] = self.__socket
        select_lock: Final[RLock] = RLock()

        def select() -> dict[int, deque[SelectorKey]]:
            ready: defaultdict[int, deque[SelectorKey]] = defaultdict(deque)
            for s in chain((self.__server_selector,), client_selectors):
                if not s.get_map():  # Empty selector, bail out
                    continue
                for key, events in s.select(timeout=0):
                    for mask in {EVENT_READ, EVENT_WRITE}:
                        if events & mask:
                            ready[mask].append(key)
            return ready

        def unregister_from_selector(socket: Socket) -> SelectorKey:
            try:
                return client_selectors_map[socket].unregister(socket)
            finally:
                client_selectors_map.pop(socket, None)

        def get_client_key_from_selector(socket: Socket) -> SelectorKey:
            return client_selectors_map[socket].get_key(socket)

        def selector_client_keys() -> list[SelectorKey]:
            return [key for key in chain.from_iterable(s.get_map().values() for s in client_selectors)]

        def add_client(future: Future[bool], socket: Socket, address: SocketAddress) -> None:
            try:
                accepted = future.result()
                socket.settimeout(0)
            except Exception:
                import traceback

                traceback.print_exc()
                with suppress(Exception):
                    socket.close()
                return
            except BaseException:
                socket.close()
                raise
            if not accepted:
                with suppress(Exception):
                    socket.close()
                return
            key_data = _SelectorKeyData(
                protocol=self.__protocol_factory(),
                socket=socket,
                address=address,
                flush=_flush_client_data_hook,
                on_close=_close_client_hook,
                is_closed=_client_is_closed_hook,
                flush_on_send=not buffered_write,
            )
            with select_lock:
                self.__clients[socket] = key_data.client
                client_selector = client_selectors[-1]
                if isinstance(client_selector, SelectSelector):
                    if len(client_selector.get_map()) >= 1000:  # Keep a margin from the 1024 ceiling, just to be sure
                        client_selector = self.__selector_factory()
                        client_selectors.append(client_selector)
                        client_selectors_stack.enter_context(client_selector)
                client_selector.register(socket, EVENT_READ | EVENT_WRITE, key_data)
                client_selectors_map[socket] = client_selector

        def _close_client_hook(socket: Socket) -> None:
            shutdown_client(socket, from_client=True)

        def _flush_client_data_hook(socket: Socket) -> None:
            with select_lock:
                return flush_queue(socket)

        def _client_is_closed_hook(socket: Socket) -> bool:
            return socket not in self.__clients

        def new_client() -> None:
            try:
                client_socket, address = server_socket.accept()
            except OSError:
                return
            address = new_socket_address(address, client_socket.family)
            future = verify_client_thread_pool.submit(self.verify_new_client, client_socket, address)
            future.add_done_callback(lambda future: add_client(future, client_socket, address))

        def receive_requests(ready: Sequence[SelectorKey]) -> None:
            for key in list(ready):
                socket: Socket = key.fileobj  # type: ignore[assignment]
                if socket is server_socket:
                    new_client()
                    continue
                key_data: _SelectorKeyData[_RequestT, _ResponseT] = key.data
                client = key_data.client
                data: bytes
                if client.closed:
                    continue
                try:
                    data = socket.recv(key_data.chunk_size, self.__recv_flags)
                except (BlockingIOError, InterruptedError):
                    pass
                except OSError:
                    shutdown_client(socket, from_client=False)
                    self.handle_error(client, sys.exc_info())
                else:
                    if not data:  # Closed connection (EOF)
                        shutdown_client(socket, from_client=False)
                        continue
                    key_data.consumer.feed(data)

        def process_requests() -> None:
            for key in selector_client_keys():
                key_data: _SelectorKeyData[_RequestT, _ResponseT] = key.data
                client = key_data.client
                if client.closed:
                    continue
                request: _RequestT
                try:
                    request = next(key_data.consumer)
                except StreamDataConsumerError as exc:
                    try:
                        self.bad_request(client, exc)
                    except Exception:
                        self.handle_error(client, sys.exc_info())
                    continue
                except StopIteration:  # Not enough data
                    continue
                try:
                    if request_executor is not None:
                        request_executor.execute(self.__execute_request, request, client, {"pid": os.getpid()})
                    else:
                        self.__execute_request(request, client, {})
                except Exception as exc:
                    if request_executor is not None:
                        raise RuntimeError(f"request_executor.execute() raised an exception: {exc}") from exc
                    raise RuntimeError(f"Error when processing request: {exc}") from exc

        def send_responses(ready: Sequence[SelectorKey]) -> None:
            data: bytes
            for key in list(ready):
                socket: Socket = key.fileobj  # type: ignore[assignment]
                key_data: _SelectorKeyData[_RequestT, _ResponseT] = key.data
                client = key_data.client

                if client.closed:
                    continue
                with key_data.send_lock:
                    try:
                        data = key_data.pop_data_to_send(read_all=False)
                    except Exception:
                        self.handle_error(client, sys.exc_info())
                        continue
                    if not data:
                        continue
                    _send_data_to_socket(socket, data, key_data)

        def flush_queue(socket: Socket) -> None:
            key_data: _SelectorKeyData[_RequestT, _ResponseT]
            try:
                key_data = get_client_key_from_selector(socket).data
            except KeyError:
                return
            with key_data.send_lock:
                data: bytes = key_data.pop_data_to_send(read_all=True)
                if data:
                    return _send_data_to_socket(socket, data, key_data)

        def _send_data_to_socket(
            socket: Socket,
            data: bytes,
            key_data: _SelectorKeyData[_RequestT, _ResponseT],
        ) -> None:
            try:
                nb_bytes_sent = socket.send(data, self.__send_flags)
            except InterruptedError:
                key_data.unsent_data = data
            except BlockingIOError as exc:
                try:
                    character_written: int = exc.characters_written
                except AttributeError:
                    character_written = 0
                finally:
                    del exc
                if character_written > 0:
                    key_data.unsent_data = data[character_written:]
            except OSError:
                shutdown_client(socket, from_client=False)
                self.handle_error(key_data.client, sys.exc_info())
            else:
                if nb_bytes_sent < len(data):
                    key_data.unsent_data = data[nb_bytes_sent:]

        def shutdown_client(socket: Socket, *, from_client: bool) -> None:
            self.__clients.pop(socket, None)
            key_data: _SelectorKeyData[_RequestT, _ResponseT]
            if from_client:
                with select_lock:
                    with suppress(Exception):
                        flush_queue(socket)
                    try:
                        key = unregister_from_selector(socket)
                    except KeyError:
                        return
            else:
                try:
                    key = unregister_from_selector(socket)
                except KeyError:
                    return
            for key_sequences in ready.values():
                if key in key_sequences:
                    key_sequences.remove(key)
            with suppress(Exception):
                try:
                    if not from_client:
                        socket.shutdown(SHUT_WR)
                finally:
                    socket.close()
            key_data = key.data
            client = key_data.client
            try:
                self.on_disconnect(client)
            except Exception:
                self.handle_error(client, sys.exc_info())

        def remove_closed_clients() -> None:
            for key in selector_client_keys():
                socket: Socket = key.fileobj  # type: ignore[assignment]
                try:
                    socket.getpeername()
                except OSError:  # Broken connection
                    shutdown_client(socket, from_client=False)

        def destroy_all_clients() -> None:
            for key in selector_client_keys():
                socket: Socket = key.fileobj  # type: ignore[assignment]
                shutdown_client(socket, from_client=False)

        # TODO: Better lock handling (fix potential dead locks)
        try:
            with (
                self.__server_selector,
                client_selectors_stack,
                ThreadPoolExecutor(max_workers=2, thread_name_prefix="TCPServer[verify_client]") as verify_client_thread_pool,
            ):
                self.__server_selector.register(server_socket, EVENT_READ)
                client_selectors_stack.enter_context(client_selectors[0])
                try:
                    while self.__loop:
                        with select_lock:
                            ready = select()
                        if not self.__loop:
                            break  # type: ignore[unreachable]
                        with self.__lock:
                            receive_requests(ready.get(EVENT_READ, ()))
                            process_requests()
                            if request_executor is not None:
                                request_executor.service_actions()
                            self.service_actions()
                            send_responses(ready.get(EVENT_WRITE, ()))
                            remove_closed_clients()
                finally:
                    with self.__lock:
                        destroy_all_clients()
        finally:
            with self.__lock:
                del self.__server_selector
                client_selectors.clear()
                client_selectors_map.clear()
                self.__loop = False
                self.__is_shutdown.set()

    @final
    def running(self) -> bool:
        return not self.__is_shutdown.is_set()

    def service_actions(self) -> None:
        pass

    def __execute_request(self, request: _RequestT, client: ConnectedClient[_ResponseT], ctx: dict[str, Any]) -> None:
        try:
            self.process_request(request, client)
        except Exception:
            self.handle_error(client, sys.exc_info())
            client.close()
        finally:
            if "pid" in ctx and ctx["pid"] != os.getpid():  # Executed in a subprocess
                if not client.closed:
                    client.flush()

    @abstractmethod
    def process_request(self, request: _RequestT, client: ConnectedClient[_ResponseT]) -> None:
        raise NotImplementedError

    def handle_error(self, client: ConnectedClient[Any], exc_info: OptExcInfo) -> None:
        from sys import stderr
        from traceback import print_exception

        if exc_info == (None, None, None):
            return

        print("-" * 40, file=stderr)
        print(f"Exception occurred during processing of request from {client.address}", file=stderr)
        print_exception(*exc_info, file=stderr)
        print("-" * 40, file=stderr)

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
            if (request_executor := self.__request_executor) is not None:
                request_executor.on_server_close()

    def shutdown(self) -> None:
        self._check_not_closed()
        with self.__lock:
            self.__loop = False
        self.__is_shutdown.wait()

    def verify_new_client(self, client_socket: Socket, address: SocketAddress) -> bool:
        return True

    def bad_request(self, client: ConnectedClient[_ResponseT], exc: StreamDataConsumerError) -> None:
        pass

    def on_disconnect(self, client: ConnectedClient[_ResponseT]) -> None:
        pass

    @contextmanager
    def stop_listening(self) -> Iterator[None]:
        if not self.__loop:
            raise RuntimeError("Server is not running")
        selector: BaseSelector = self.__server_selector
        server_socket: Socket = self.__socket
        key: SelectorKey | None
        with self.__lock:
            try:
                key = selector.unregister(server_socket)
            except KeyError:
                key = None
        if key is None:
            yield
            return
        try:
            server_socket.listen(0)
            yield
        finally:
            if self.__loop:
                default_backlog: int | None = self.__default_backlog
                if default_backlog is None:
                    server_socket.listen()
                else:
                    server_socket.listen(default_backlog)
                with self.__lock:
                    selector.register(key.fileobj, key.events, key.data)

    def protocol(self) -> StreamProtocol[_ResponseT, _RequestT]:
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

    @final
    def get_clients(self) -> Sequence[ConnectedClient[_ResponseT]]:
        with self.__lock:
            self._check_not_closed()
            return tuple(filter(lambda client: not client.closed, self.__clients.values()))

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
        return self.__send_flags

    @property
    @final
    def recv_flags(self) -> int:
        return self.__recv_flags


@dataclass(init=False, slots=True)
class _SelectorKeyData(Generic[_RequestT, _ResponseT]):
    producer: StreamDataProducerReader[_ResponseT]
    consumer: StreamDataConsumer[_RequestT]
    chunk_size: int
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
        on_close: Callable[[Socket], None],
        is_closed: Callable[[Socket], bool],
        flush_on_send: bool,
    ) -> None:
        self.producer = StreamDataProducerReader(protocol)
        self.consumer = StreamDataConsumer(protocol, on_error="raise")
        self.chunk_size = guess_best_buffer_size(socket)
        self.client = self.__ConnectedTCPClient(
            producer=self.producer,
            socket=socket,
            address=address,
            flush=flush,
            on_close=on_close,
            is_closed=is_closed,
            flush_on_send=flush_on_send,
        )
        self.unsent_data = b""
        self.send_lock = RLock()

    def pop_data_to_send(self, *, read_all: bool) -> bytes:
        data, self.unsent_data = self.unsent_data, b""
        if read_all:
            data += self.producer.read(-1)
        elif (chunk_size_to_produce := self.chunk_size - len(data)) > 0:
            data += self.producer.read(chunk_size_to_produce)
        elif chunk_size_to_produce < 0:
            data, self.unsent_data = data[: self.chunk_size], data[self.chunk_size :]
        return data

    @final
    class __ConnectedTCPClient(ConnectedClient[_ResponseT]):
        __slots__ = ("__p", "__s", "__flush", "__flush_on_send", "__on_close", "__is_closed")

        def __init__(
            self,
            *,
            producer: StreamDataProducerReader[_ResponseT],
            socket: Socket,
            address: SocketAddress,
            flush: Callable[[Socket], None],
            on_close: Callable[[Socket], None],
            is_closed: Callable[[Socket], bool],
            flush_on_send: bool,
        ) -> None:
            super().__init__(address)
            self.__p: StreamDataProducerReader[_ResponseT] = producer
            self.__s: Socket | None = socket
            self.__flush: Callable[[Socket], None] = flush
            self.__on_close: Callable[[Socket], None] = on_close
            self.__is_closed: Callable[[Socket], bool] = is_closed
            self.__flush_on_send: bool = flush_on_send

        def close(self) -> None:
            with self.transaction():
                socket = self.__s
                self.__s = None
                if socket is not None and not self.__is_closed(socket):
                    self.__on_close(socket)

        def shutdown(self) -> None:
            with self.transaction():
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
            with self.transaction():
                socket = self.__check_not_closed()
                self.__p.queue(packet)
                if self.__flush_on_send:
                    self.__flush(socket)

        def send_packets(self, *packets: _ResponseT) -> None:
            with self.transaction():
                socket = self.__check_not_closed()
                self.__p.queue(*packets)
                if self.__flush_on_send:
                    self.__flush(socket)

        def flush(self) -> None:
            with self.transaction():
                socket = self.__check_not_closed()
                return self.__flush(socket)

        def __check_not_closed(self) -> Socket:
            socket = self.__s
            if socket is None or self.__is_closed(socket):
                self.__s = None
                raise RuntimeError("Closed client")
            return socket

        @property
        def closed(self) -> bool:
            return (socket := self.__s) is None or self.__is_closed(socket)
