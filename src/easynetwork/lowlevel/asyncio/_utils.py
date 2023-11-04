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

__all__ = ["create_connection", "open_listener_sockets_from_getaddrinfo_result"]

import asyncio
import contextlib
import socket as _socket
from collections.abc import Iterable, Sequence
from typing import Any

from easynetwork.lowlevel._utils import set_reuseport as _set_reuseport


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


async def create_connection(
    host: str,
    port: int,
    loop: asyncio.AbstractEventLoop,
    local_address: tuple[str, int] | None = None,
    socktype: int = _socket.SOCK_STREAM,
) -> _socket.socket:
    remote_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = await ensure_resolved(
        host,
        port,
        family=_socket.AF_UNSPEC,
        type=socktype,
        loop=loop,
    )
    local_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None = None
    if local_address is not None:
        local_host, local_port = local_address
        local_addrinfo = await ensure_resolved(
            local_host,
            local_port,
            family=_socket.AF_UNSPEC,
            type=socktype,
            loop=loop,
        )

    errors: list[OSError] = []
    for family, _, proto, _, remote_sockaddr in remote_addrinfo:
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
                _set_reuseport(sock)
            # Disable IPv4/IPv6 dual stack support (enabled by
            # default on Linux) which makes a single socket
            # listen on both address families.
            if _socket.has_ipv6 and af == _socket.AF_INET6 and hasattr(_socket, "IPPROTO_IPV6"):
                sock.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, True)
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
            raise ExceptionGroup("Error when trying to create TCP listeners", errors)

        # There were no errors, therefore do not close the sockets
        socket_exit_stack.pop_all()

    return sockets
