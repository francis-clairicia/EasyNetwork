from __future__ import annotations

from typing import Any, Protocol


class SupportsClosing(Protocol):
    def close(self) -> None: ...

    def is_closed(self) -> bool: ...


class SupportsSending(SupportsClosing, Protocol):
    def send_packet(self, packet: Any, *, timeout: float | None = None) -> None: ...


class SupportsReceiving(SupportsClosing, Protocol):
    def recv_packet(self, *, timeout: float | None = None) -> Any: ...
