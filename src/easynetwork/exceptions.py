# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Exceptions definition module"""

from __future__ import annotations

__all__ = [
    "BaseProtocolParseError",
    "ClientClosedError",
    "DatagramProtocolParseError",
    "DeserializeError",
    "IncrementalDeserializeError",
    "PacketConversionError",
    "ServerAlreadyRunning",
    "ServerClosedError",
    "StreamProtocolParseError",
]

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tools.socket import SocketAddress


class ClientClosedError(ConnectionError):
    """Error raised when trying to do an operation on a closed client"""


class ServerClosedError(RuntimeError):
    """Error raised when trying to do an operation on a closed server"""


class ServerAlreadyRunning(RuntimeError):
    """Error raised if serve_forever() is called twice"""


class DeserializeError(Exception):
    def __init__(self, message: str, error_info: Any = None) -> None:
        super().__init__(message)
        self.error_info: Any = error_info


class IncrementalDeserializeError(DeserializeError):
    def __init__(self, message: str, remaining_data: bytes, error_info: Any = None) -> None:
        super().__init__(message, error_info=error_info)
        self.remaining_data: bytes = remaining_data


class PacketConversionError(Exception):
    def __init__(self, message: str, error_info: Any = None) -> None:
        super().__init__(message)
        self.error_info: Any = error_info


class BaseProtocolParseError(Exception):
    def __init__(self, error: DeserializeError | PacketConversionError) -> None:
        super().__init__(f"Error while parsing data: {error}")
        self.error: DeserializeError | PacketConversionError = error


class DatagramProtocolParseError(BaseProtocolParseError):
    sender_address: SocketAddress


class StreamProtocolParseError(BaseProtocolParseError):
    def __init__(self, remaining_data: bytes, error: IncrementalDeserializeError | PacketConversionError) -> None:
        super().__init__(error)
        self.error: IncrementalDeserializeError | PacketConversionError
        self.remaining_data: bytes = remaining_data
