from __future__ import annotations

from typing import Any, Protocol

from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend


class HaveBackend(Protocol):
    def backend(self) -> AsyncBackend: ...


class SupportsClosing(Protocol):
    async def aclose(self) -> None: ...

    def is_closing(self) -> bool: ...


class SupportsSending(SupportsClosing, Protocol):
    async def send_packet(self, packet: Any) -> None: ...


class SupportsReceiving(SupportsClosing, Protocol):
    async def recv_packet(self) -> Any: ...
