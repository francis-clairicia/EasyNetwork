# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
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
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = [
    "create_connection",
    "create_datagram_connection",
    "open_listener_sockets_from_getaddrinfo_result",
    "wait_until_readable",
    "wait_until_writable",
]

import asyncio
import contextlib
import itertools
import math
import socket as _socket
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from typing import Any, cast

from .. import _utils


async def ensure_resolved(
    host: str | None,
    port: int,
    family: int,
    type: int,
    loop: asyncio.AbstractEventLoop,
    proto: int = 0,
    flags: int = 0,
) -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
    try:
        info = _socket.getaddrinfo(
            host, port, family=family, type=type, proto=proto, flags=flags | _socket.AI_NUMERICHOST | _socket.AI_NUMERICSERV
        )
    except _socket.gaierror as exc:
        if exc.errno != _socket.EAI_NONAME:
            raise
        info = await loop.getaddrinfo(host, port, family=family, type=type, proto=proto, flags=flags)
    if not info:
        raise OSError(f"getaddrinfo({host!r}) returned empty list")
    return info


async def resolve_local_addresses(
    hosts: Sequence[str | None],
    port: int,
    socktype: int,
    loop: asyncio.AbstractEventLoop,
) -> Sequence[tuple[int, int, int, str, tuple[Any, ...]]]:
    infos: set[tuple[int, int, int, str, tuple[Any, ...]]] = set(
        itertools.chain.from_iterable(
            await asyncio.gather(
                *[
                    ensure_resolved(
                        host,
                        port,
                        _socket.AF_UNSPEC,
                        socktype,
                        loop,
                        flags=_socket.AI_PASSIVE | _socket.AI_ADDRCONFIG,
                    )
                    for host in hosts
                ]
            )
        )
    )
    return sorted(infos)


async def _create_connection_impl(
    *,
    loop: asyncio.AbstractEventLoop,
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
            socket.setblocking(False)

            if local_addrinfo is not None:
                bind_errors: list[OSError] = []
                try:
                    for lfamily, _, _, _, local_sockaddr in local_addrinfo:
                        # skip local addresses of different family
                        if lfamily != family:
                            continue
                        try:
                            socket.bind(local_sockaddr)
                            break
                        except OSError as exc:
                            msg = f"error while attempting to bind on address {local_sockaddr!r}: {exc.strerror.lower()}"
                            bind_errors.append(OSError(exc.errno, msg).with_traceback(exc.__traceback__))
                    else:  # all bind attempts failed
                        if bind_errors:
                            socket.close()
                            errors.extend(bind_errors)
                            continue
                        raise OSError(f"no matching local address with {family=} found")
                finally:
                    bind_errors.clear()
                    del bind_errors

            await loop.sock_connect(socket, remote_sockaddr)
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


# Taken from asyncio library
def _interleave_addrinfos(
    addrinfos: Sequence[tuple[int, int, int, str, tuple[Any, ...]]]
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


# Taken from anyio project
def _prioritize_ipv6_over_ipv4(
    addrinfos: Sequence[tuple[int, int, int, str, tuple[Any, ...]]]
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


async def _staggered_race_connection_impl(
    *,
    loop: asyncio.AbstractEventLoop,
    remote_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
    local_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None,
    happy_eyeballs_delay: float,
) -> _socket.socket:
    from .tasks import CancelScope

    remote_addrinfo = _interleave_addrinfos(_prioritize_ipv6_over_ipv4(remote_addrinfo))
    winner: _socket.socket | None = cast(_socket.socket | None, None)
    errors: list[OSError | BaseExceptionGroup[OSError]] = []

    async def try_connect(addr: tuple[int, int, int, str, tuple[Any, ...]]) -> None:
        nonlocal winner
        try:
            socket = await _create_connection_impl(loop=loop, remote_addrinfo=[addr], local_addrinfo=local_addrinfo)
        except* OSError as excgrp:
            errors.extend(excgrp.exceptions)
        else:
            if winner is None:
                winner = socket
                connection_scope.cancel()
            else:
                socket.close()

    try:
        with CancelScope() as connection_scope:
            async with asyncio.TaskGroup() as task_group:
                for addr in remote_addrinfo:
                    await asyncio.wait({task_group.create_task(try_connect(addr))}, timeout=happy_eyeballs_delay)

        if winner is None:
            raise BaseExceptionGroup("create_connection() failed", errors)
        return winner
    except BaseException:
        if winner is not None:
            winner.close()
        raise
    finally:
        errors.clear()


async def create_connection(
    host: str,
    port: int,
    loop: asyncio.AbstractEventLoop,
    local_address: tuple[str, int] | None = None,
    *,
    happy_eyeballs_delay: float = math.inf,
) -> _socket.socket:
    remote_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = await ensure_resolved(
        host,
        port,
        family=_socket.AF_UNSPEC,
        type=_socket.SOCK_STREAM,
        loop=loop,
    )
    local_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None = None
    if local_address is not None:
        local_host, local_port = local_address
        local_addrinfo = await ensure_resolved(
            local_host,
            local_port,
            family=_socket.AF_UNSPEC,
            type=_socket.SOCK_STREAM,
            loop=loop,
        )

    return await _staggered_race_connection_impl(
        loop=loop,
        remote_addrinfo=remote_addrinfo,
        local_addrinfo=local_addrinfo,
        happy_eyeballs_delay=happy_eyeballs_delay,
    )


async def create_datagram_connection(
    host: str,
    port: int,
    loop: asyncio.AbstractEventLoop,
    local_address: tuple[str, int] | None = None,
    family: int = _socket.AF_UNSPEC,
) -> _socket.socket:
    remote_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = await ensure_resolved(
        host,
        port,
        family=family,
        type=_socket.SOCK_DGRAM,
        loop=loop,
    )
    local_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None = None
    if local_address is not None:
        local_host, local_port = local_address
        local_addrinfo = await ensure_resolved(
            local_host,
            local_port,
            family=family,
            type=_socket.SOCK_DGRAM,
            loop=loop,
        )

    return await _create_connection_impl(
        loop=loop,
        remote_addrinfo=remote_addrinfo,
        local_addrinfo=local_addrinfo,
    )


def open_listener_sockets_from_getaddrinfo_result(
    infos: Iterable[tuple[int, int, int, str, tuple[Any, ...]]],
    *,
    backlog: int | None,
    reuse_address: bool,
    reuse_port: bool,
) -> list[_socket.socket]:
    sockets: list[_socket.socket] = []
    reuse_address = reuse_address and hasattr(_socket, "SO_REUSEADDR")
    with contextlib.ExitStack() as _whole_context_stack:
        errors: list[OSError] = []
        _whole_context_stack.callback(errors.clear)

        socket_exit_stack = _whole_context_stack.enter_context(contextlib.ExitStack())

        for af, socktype, proto, _, sa in infos:
            try:
                sock = socket_exit_stack.enter_context(contextlib.closing(_socket.socket(af, socktype, proto)))
            except OSError:
                # Assume it's a bad family/type/protocol combination.
                continue
            sockets.append(sock)
            if reuse_address:
                try:
                    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, True)
                except OSError:
                    # Will fail later on bind()
                    pass
            if reuse_port:
                _utils.set_reuseport(sock)
            # Disable IPv4/IPv6 dual stack support (enabled by
            # default on Linux) which makes a single socket
            # listen on both address families.
            if af == _socket.AF_INET6:
                if hasattr(_socket, "IPPROTO_IPV6"):
                    sock.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, True)
                if "%" in sa[0]:
                    addr, scope_id = sa[0].split("%", 1)
                    sa = (addr, sa[1], 0, int(scope_id))
            try:
                sock.bind(sa)
            except OSError as exc:
                errors.append(
                    OSError(
                        exc.errno, f"error while attempting to bind to address {sa!r}: {exc.strerror.lower()}"
                    ).with_traceback(exc.__traceback__)
                )
                continue
            if backlog is not None:
                sock.listen(backlog)

        if errors:
            # No need to call errors.clear(), this is done by exit stack
            raise ExceptionGroup("Error when trying to create listeners", errors)

        # There were no errors, therefore do not close the sockets
        socket_exit_stack.pop_all()

    return sockets


def wait_until_readable(sock: _socket.socket, loop: asyncio.AbstractEventLoop) -> asyncio.Future[None]:
    def on_fut_done(f: asyncio.Future[None]) -> None:
        loop.remove_reader(sock)

    def wakeup(f: asyncio.Future[None]) -> None:
        if not f.done():
            f.set_result(None)

    f = loop.create_future()
    loop.add_reader(sock, wakeup, f)
    f.add_done_callback(on_fut_done)
    return f


def wait_until_writable(sock: _socket.socket, loop: asyncio.AbstractEventLoop) -> asyncio.Future[None]:
    def on_fut_done(f: asyncio.Future[None]) -> None:
        loop.remove_writer(sock)

    def wakeup(f: asyncio.Future[None]) -> None:
        if not f.done():
            f.set_result(None)

    f = loop.create_future()
    loop.add_writer(sock, wakeup, f)
    f.add_done_callback(on_fut_done)
    return f
