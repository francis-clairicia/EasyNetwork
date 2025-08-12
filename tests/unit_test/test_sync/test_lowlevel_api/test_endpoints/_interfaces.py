from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class SupportsClosing(Protocol):
    def close(self) -> None: ...

    def is_closed(self) -> bool: ...


class SupportsSending(SupportsClosing, Protocol):
    def send_packet(self, packet: Any, *, timeout: float | None = None) -> None: ...

    def send_packet_with_ancillary(self, packet: Any, ancillary_data: Any, *, timeout: float | None = None) -> None: ...


class SupportsReceiving(SupportsClosing, Protocol):
    def recv_packet(self, *, timeout: float | None = None) -> Any: ...

    def recv_packet_with_ancillary(
        self,
        ancillary_bufsize: int,
        ancillary_data_received: Callable[[Any], object],
        *,
        timeout: float | None = None,
    ) -> Any: ...
