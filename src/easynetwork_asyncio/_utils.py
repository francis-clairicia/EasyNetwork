# -*- coding: utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["create_connection", "create_datagram_socket"]

import asyncio
import socket as _socket
from typing import Any, Sequence

from easynetwork.tools._utils import set_reuseport as _set_reuseport


async def _ensure_resolved(
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


async def _create_socket_from_getaddrinfo_result(
    socktype: int,
    local_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None,
    remote_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None,
    loop: asyncio.AbstractEventLoop,
    reuse_port: bool,
) -> _socket.socket:
    assert local_addrinfo or remote_addrinfo, "Either 'local_addrinfo' or 'remote_addrinfo' must be defined (and not empty)"
    assert all(
        type_ == socktype for info in (local_addrinfo or (), remote_addrinfo or ()) for _, type_, _, _, _ in info
    ), f"socket type mismatch with those in getaddrinfo() result ({socktype=!r})"

    ## Taken from asyncio.base_events module
    ## c.f. https://github.com/python/cpython/blob/v3.11.2/Lib/asyncio/base_events.py#L1325

    # join address by (family, protocol)
    addr_infos: dict[tuple[int, int], list[tuple[Any, ...] | None]] = {}  # Using order preserving dict
    for idx, infos in ((0, local_addrinfo), (1, remote_addrinfo)):
        if infos is not None:
            for af, _, proto, _, address in infos:
                key = (af, proto)
                if key not in addr_infos:
                    addr_infos[key] = [None, None]
                addr_infos[key][idx] = address

    # each addr has to have info for each (family, proto) pair
    addr_pairs_info = [
        (key, addr_pair)
        for key, addr_pair in addr_infos.items()
        if not ((local_addrinfo and addr_pair[0] is None) or (remote_addrinfo and addr_pair[1] is None))
    ]

    errors: list[OSError] = []

    for (af, proto), (local_address, remote_address) in addr_pairs_info:
        socket: _socket.socket | None = None
        try:
            socket = _socket.socket(af, socktype, proto)
            socket.setblocking(False)

            if reuse_port:
                _set_reuseport(socket)

            if local_address is not None:
                try:
                    socket.bind(local_address)
                except OSError as exc:
                    msg = f"error while attempting to bind on address {local_address!r}: {exc.strerror.lower()}"
                    raise OSError(exc.errno, msg).with_traceback(exc.__traceback__) from None

            if remote_address is not None:
                await loop.sock_connect(socket, remote_address)

            errors.clear()
            return socket
        except OSError as exc:
            errors.append(exc)
            if socket is not None:
                socket.close()
            continue
        except BaseException:
            if socket is not None:
                socket.close()
            raise

    if errors:
        try:
            raise ExceptionGroup("Errors while attempting to create socket", errors)
        finally:
            errors = []

    raise OSError("No matching local/remote pair according to family and proto found")


async def create_connection(
    host: str,
    port: int,
    loop: asyncio.AbstractEventLoop,
    local_address: tuple[str, int] | None = None,
) -> _socket.socket:
    remote_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = await _ensure_resolved(
        host,
        port,
        family=_socket.AF_UNSPEC,
        type=_socket.SOCK_STREAM,
        loop=loop,
    )
    local_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None = None
    if local_address is not None:
        local_host, local_port = local_address
        local_addrinfo = await _ensure_resolved(
            local_host,
            local_port,
            family=_socket.AF_UNSPEC,
            type=_socket.SOCK_STREAM,
            loop=loop,
        )

    return await _create_socket_from_getaddrinfo_result(
        _socket.SOCK_STREAM,
        local_addrinfo=local_addrinfo,
        remote_addrinfo=remote_addrinfo,
        loop=loop,
        reuse_port=False,
    )


async def create_datagram_socket(
    loop: asyncio.AbstractEventLoop,
    local_address: tuple[str | None, int] | None = None,
    remote_address: tuple[str, int] | None = None,
    reuse_port: bool = False,
) -> _socket.socket:
    if local_address is None:
        local_address = (None, 0)
    local_host, local_port = local_address
    if local_host == "":
        local_host = None
    local_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] = await _ensure_resolved(
        local_host,
        local_port,
        family=_socket.AF_UNSPEC,
        type=_socket.SOCK_DGRAM,
        loop=loop,
        flags=_socket.AI_PASSIVE,
    )
    remote_addrinfo: Sequence[tuple[int, int, int, str, tuple[Any, ...]]] | None = None
    if remote_address is not None:
        remote_host, remote_port = remote_address
        remote_addrinfo = await _ensure_resolved(
            remote_host,
            remote_port,
            family=_socket.AF_UNSPEC,
            type=_socket.SOCK_DGRAM,
            loop=loop,
        )

    return await _create_socket_from_getaddrinfo_result(
        _socket.SOCK_DGRAM,
        local_addrinfo=local_addrinfo,
        remote_addrinfo=remote_addrinfo,
        loop=loop,
        reuse_port=reuse_port,
    )
