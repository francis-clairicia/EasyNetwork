# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""asyncio engine for easynetwork.async
"""

from __future__ import annotations

__all__ = ["DatagramServer"]

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Coroutine, final

from easynetwork.api_async.backend.abc import AbstractAsyncDatagramServerAdapter
from easynetwork.tools.socket import SocketProxy

if TYPE_CHECKING:
    import asyncio.trsock

    from _typeshed import ReadableBuffer

    from ..backend import AsyncioBackend
    from .endpoint import DatagramEndpoint


@final
class DatagramServer(AbstractAsyncDatagramServerAdapter):
    __slots__ = (
        "__backend",
        "__endpoint",
        "__datagram_received_cb",
        "__error_received_cb",
        "__loop",
        "__serving_task",
        "__closed",
    )

    def __init__(
        self,
        backend: AsyncioBackend,
        endpoint: DatagramEndpoint,
        datagram_received_cb: Callable[[bytes, tuple[Any, ...]], Coroutine[Any, Any, Any]],
        error_received_cb: Callable[[Exception], Coroutine[Any, Any, Any]],
    ) -> None:
        super().__init__()
        self.__backend: AsyncioBackend = backend
        self.__endpoint: DatagramEndpoint = endpoint
        self.__loop: asyncio.AbstractEventLoop = endpoint.get_loop()
        self.__datagram_received_cb: Callable[[bytes, tuple[Any, ...]], Coroutine[Any, Any, Any]] = datagram_received_cb
        self.__error_received_cb: Callable[[Exception], Coroutine[Any, Any, Any]] = error_received_cb
        self.__serving_task: asyncio.Task[None] | None = None
        self.__closed: bool = False

    async def __server_mainloop(self) -> None:
        async with asyncio.TaskGroup() as tg:
            while True:
                try:
                    datagram, address = await self.__endpoint.recvfrom()
                except Exception as exc:
                    tg.create_task(self.__error_received_cb(exc))
                    if self.__endpoint.is_closing():
                        break
                else:
                    tg.create_task(self.__datagram_received_cb(datagram, address))

    async def close(self) -> None:
        self.__closed = True

        serving_task = self.__serving_task
        if serving_task is not None:
            self.__serving_task = None
            if not serving_task.done():
                serving_task.cancel()
            self.__endpoint.close()

        await self.__endpoint.wait_closed()

    def is_serving(self) -> bool:
        serving_task = self.__serving_task
        return serving_task is not None and not serving_task.done()

    async def serve_forever(self) -> None:
        if self.__serving_task is not None:
            raise RuntimeError(f"server {self!r} is already being awaited on serve_forever()")

        self.__serving_task = self.__loop.create_task(self.__server_mainloop())
        try:
            await self.__serving_task
        except asyncio.CancelledError:
            try:
                await self.close()
            finally:
                raise
        finally:
            self.__serving_task = None

    async def sendto(self, data: ReadableBuffer, address: tuple[Any, ...], /) -> None:
        assert address is not None
        if self.__closed:
            raise RuntimeError(f"server {self!r} is closed")
        if not self.is_serving():
            raise RuntimeError(f"server {self!r} is not started")
        with memoryview(data).toreadonly() as data_view:
            await self.__endpoint.sendto(data_view, address)

    def get_backend(self) -> AsyncioBackend:
        return self.__backend

    def socket(self) -> SocketProxy | None:
        socket: asyncio.trsock.TransportSocket | None
        if self.__closed or self.__endpoint.is_closing() or (socket := self.__endpoint.get_extra_info("socket")) is None:
            return None
        return SocketProxy(socket)
