# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""DNS Resolver module."""

from __future__ import annotations

__all__ = ["BaseAsyncDNSResolver"]

import itertools
import math
import socket as _socket
from abc import ABCMeta, abstractmethod
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any, cast

from .... import _utils
from ..abc import AsyncBackend, IEvent


class BaseAsyncDNSResolver(metaclass=ABCMeta):
    __slots__ = ()

    @abstractmethod
    async def connect_socket(self, socket: _socket.socket, address: tuple[str, int] | tuple[str, int, int, int]) -> None:
        raise NotImplementedError

    async def ensure_resolved(
        self,
        backend: AsyncBackend,
        host: str | None,
        port: int,
        family: int,
        type: int,
        proto: int = 0,
        flags: int = 0,
    ) -> Sequence[tuple[int, int, int, str, tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes]]]:
        info: Sequence[tuple[int, int, int, str, tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes]]] | None
        try:
            info = _socket.getaddrinfo(
                host, port, family=family, type=type, proto=proto, flags=flags | _socket.AI_NUMERICHOST | _socket.AI_NUMERICSERV
            )
        except _socket.gaierror as exc:
            if exc.errno != _socket.EAI_NONAME:
                raise
            info = None
        if info is None:
            info = await backend.getaddrinfo(host, port, family=family, type=type, proto=proto, flags=flags)
        if not info:
            raise OSError(f"getaddrinfo({host!r}) returned empty list")
        return info

    async def resolve_listener_addresses(
        self,
        backend: AsyncBackend,
        hosts: Sequence[str | None],
        port: int,
        socktype: int,
    ) -> Sequence[tuple[int, int, int, str, tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes]]]:
        infos = set(
            itertools.chain.from_iterable(
                await backend.gather(
                    *[
                        self.ensure_resolved(
                            backend,
                            host,
                            port,
                            _socket.AF_UNSPEC,
                            socktype,
                            flags=_socket.AI_PASSIVE | _socket.AI_ADDRCONFIG,
                        )
                        for host in hosts
                    ]
                )
            )
        )
        return sorted(infos)

    async def create_stream_connection(
        self,
        backend: AsyncBackend,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = None,
        happy_eyeballs_delay: float = math.inf,
    ) -> _socket.socket:
        remote_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = await self.ensure_resolved(
            backend,
            host,
            port,
            family=_socket.AF_UNSPEC,
            type=_socket.SOCK_STREAM,
        )
        local_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None = None
        if local_address is not None:
            local_host, local_port = local_address
            local_addrinfo = await self.ensure_resolved(
                backend,
                local_host,
                local_port,
                family=_socket.AF_UNSPEC,
                type=_socket.SOCK_STREAM,
            )

        return await self._staggered_race_connection_impl(
            backend=backend,
            remote_addrinfo=remote_addrinfo,
            local_addrinfo=local_addrinfo,
            happy_eyeballs_delay=happy_eyeballs_delay,
        )

    async def create_datagram_connection(
        self,
        backend: AsyncBackend,
        host: str,
        port: int,
        *,
        local_address: tuple[str, int] | None = None,
        family: int = _socket.AF_UNSPEC,
    ) -> _socket.socket:
        if family != _socket.AF_UNSPEC:
            _utils.check_inet_socket_family(family)
        remote_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = await self.ensure_resolved(
            backend,
            host,
            port,
            family=family,
            type=_socket.SOCK_DGRAM,
        )
        local_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None = None
        if local_address is not None:
            local_host, local_port = local_address
            local_addrinfo = await self.ensure_resolved(
                backend,
                local_host,
                local_port,
                family=family,
                type=_socket.SOCK_DGRAM,
            )

        return await self._create_connection_impl(
            remote_addrinfo=remote_addrinfo,
            local_addrinfo=local_addrinfo,
        )

    async def _create_connection_impl(
        self,
        *,
        remote_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
        local_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None,
    ) -> _socket.socket:
        errors: list[OSError] = []
        for family, socktype, proto, _, remote_sockaddr in remote_addrinfo:
            try:
                socket = _socket.socket(family, socktype, proto)
            except OSError as exc:
                errors.append(exc)
                continue
            except BaseException:
                errors.clear()
                raise
            try:
                if local_addrinfo is not None:
                    bind_errors: list[OSError] = []
                    try:
                        for lfamily, _, _, _, local_sockaddr in local_addrinfo:
                            # skip local addresses of different family
                            if lfamily != family:
                                continue
                            try:
                                socket.bind(local_sockaddr)
                            except OSError as exc:
                                bind_errors.append(_utils.convert_socket_bind_error(exc, local_sockaddr))
                            else:
                                break
                        else:  # all bind attempts failed
                            if bind_errors:
                                socket.close()
                                errors.extend(bind_errors)
                                continue
                            raise OSError(f"no matching local address with {family=} found")
                    finally:
                        bind_errors.clear()

                socket.setblocking(False)
                await self.connect_socket(socket, remote_sockaddr)
                errors.clear()
                return socket
            except OSError as exc:
                socket.close()
                errors.append(exc)
                continue
            except BaseException:
                errors.clear()
                socket.close()
                raise

        assert errors  # nosec assert_used
        try:
            raise ExceptionGroup("create_connection() failed", errors)
        finally:
            errors.clear()

    # Taken from anyio project (https://github.com/agronholm/anyio/tree/4.2.0)
    async def _staggered_race_connection_impl(
        self,
        backend: AsyncBackend,
        *,
        remote_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
        local_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None,
        happy_eyeballs_delay: float,
    ) -> _socket.socket:
        remote_addrinfo = _interleave_addrinfos(_prioritize_ipv6_over_ipv4(remote_addrinfo))
        winner: _socket.socket | None = cast(_socket.socket | None, None)
        errors: list[OSError | BaseExceptionGroup[OSError]] = []

        async def try_connect(addr: tuple[int, int, int, str, tuple[Any, ...]], done: IEvent) -> None:
            nonlocal winner
            try:
                socket = await self._create_connection_impl(remote_addrinfo=[addr], local_addrinfo=local_addrinfo)
            except* OSError as excgrp:
                errors.extend(excgrp.exceptions)
            else:
                if winner is None:
                    winner = socket
                    connection_scope.cancel()
                else:
                    socket.close()
            finally:
                done.set()
                del done

        try:
            with backend.open_cancel_scope() as connection_scope:
                async with backend.create_task_group() as task_group:
                    for addr in remote_addrinfo:
                        done = backend.create_event()
                        task_group.start_soon(try_connect, addr, done)
                        with backend.move_on_after(happy_eyeballs_delay):
                            await done.wait()

            if winner is None:
                raise BaseExceptionGroup("create_connection() failed", errors)
            return winner
        except BaseException:
            if winner is not None:
                winner.close()
            raise
        finally:
            errors.clear()


# Taken from asyncio library (https://github.com/python/cpython/tree/v3.12.0/Lib/asyncio)
def _interleave_addrinfos(
    addrinfos: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
    """Interleave list of addrinfo tuples by family."""
    # Group addresses by family
    addrinfos_by_family: OrderedDict[int, list[tuple[Any, ...]]] = OrderedDict()
    for addr in addrinfos:
        family = addr[0]
        if family not in addrinfos_by_family:
            addrinfos_by_family[family] = []
        addrinfos_by_family[family].append(addr)
    addrinfos_lists = list(addrinfos_by_family.values())
    return [addr for addr in itertools.chain.from_iterable(itertools.zip_longest(*addrinfos_lists)) if addr is not None]


# Taken from anyio project (https://github.com/agronholm/anyio/tree/4.2.0)
def _prioritize_ipv6_over_ipv4(
    addrinfos: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
    # Organize the list so that the first address is an IPv6 address (if available)
    # and the second one is an IPv4 addresses. The rest can be in whatever order.
    v6_found = v4_found = False
    reordered: list[tuple[int, int, int, str, tuple[Any, ...]]] = []
    for addr in addrinfos:
        family = addr[0]
        if family == _socket.AF_INET6 and not v6_found:
            v6_found = True
            reordered.insert(0, addr)
        elif family == _socket.AF_INET and not v4_found and v6_found:
            v4_found = True
            reordered.insert(1, addr)
        else:
            reordered.append(addr)
    return reordered
